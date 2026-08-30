"""Кабинет: данные рождения, пересчёт карты, удаление аккаунта."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q

from core.models import NatalChart, OnboardingSession, Order, Profile, WaitlistLead
from core.services.geo import GeoLookupError
from core.services.natal import NatalCalcError
from core.services.natal_common import public_natal_error
from core.services.onboarding_astro import calculate_and_store_chart


class BirthUpdateError(Exception):
    def __init__(self, message: str, field: str = "detail"):
        super().__init__(message)
        self.message = message
        self.field = field


def _parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    dotted = raw.replace("/", ".")
    if dotted.count(".") == 2 and not dotted[:4].isdigit():
        day_s, month_s, year_s = dotted.split(".")
        try:
            return date(int(year_s), int(month_s), int(day_s))
        except ValueError as exc:
            raise BirthUpdateError("Дата рождения выглядит неверно.", "birth_date") from exc
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise BirthUpdateError("Дата рождения выглядит неверно.", "birth_date") from exc


def _parse_time(value: Any) -> Optional[time]:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(float(parts[2])) if len(parts) > 2 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError) as exc:
        raise BirthUpdateError("Время рождения выглядит неверно.", "birth_time") from exc


def _parse_coord(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BirthUpdateError("Не получилось понять координаты города.", "birth_place") from exc


def _fmt_date(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _fmt_time(value: Optional[time]) -> Optional[str]:
    return value.strftime("%H:%M") if value else None


def _fmt_coord(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _latest_order(user: User) -> Optional[Order]:
    qs = Order.objects.filter(Q(user=user) | Q(session__user=user)).select_related("session")
    paid = qs.filter(status=Order.Status.PAID).order_by("-paid_at", "-created_at").first()
    return paid or qs.order_by("-created_at").first()


def _latest_session(user: User) -> Optional[OnboardingSession]:
    order = _latest_order(user)
    if order and order.session_id:
        return order.session
    return OnboardingSession.objects.filter(user=user).order_by("-updated_at").first()


def birth_snapshot(user: User) -> dict[str, Any]:
    profile = getattr(user, "profile", None)
    session = _latest_session(user)
    chart = (
        NatalChart.objects.filter(Q(user=user) | Q(session__user=user))
        .order_by("-updated_at")
        .first()
    )

    birth_date = (
        (profile.birth_date if profile else None)
        or (session.birth_date if session else None)
        or (chart.birth_date if chart else None)
    )
    birth_time = profile.birth_time if profile else None
    if birth_time is None and session is not None:
        birth_time = session.birth_time
    if birth_time is None and chart is not None:
        birth_time = chart.birth_time

    birth_place = (
        ((profile.birth_place if profile else "") or "").strip()
        or ((session.birth_place if session else "") or "").strip()
        or ((chart.birth_place if chart else "") or "").strip()
    )
    birth_lat = (
        (profile.birth_lat if profile else None)
        or (session.birth_lat if session else None)
        or (chart.birth_lat if chart else None)
    )
    birth_lng = (
        (profile.birth_lng if profile else None)
        or (session.birth_lng if session else None)
        or (chart.birth_lng if chart else None)
    )
    timezone_name = (
        ((profile.timezone if profile else "") or "").strip()
        or ((session.timezone if session else "") or "").strip()
        or ((chart.timezone if chart else "") or "").strip()
    )
    return {
        "birth_date": _fmt_date(birth_date),
        "birth_time": _fmt_time(birth_time),
        "birth_place": birth_place,
        "birth_lat": _fmt_coord(birth_lat),
        "birth_lng": _fmt_coord(birth_lng),
        "timezone": timezone_name,
        "has_birth_time": bool(birth_time),
    }


def _invalidate_paid_reports(user: User) -> None:
    from core.services.report_jobs import kickoff_paid_report_for_order

    orders = Order.objects.filter(
        Q(user=user) | Q(session__user=user),
        status=Order.Status.PAID,
    )
    for order in orders:
        order.interpretive = {}
        order.save(update_fields=["interpretive", "updated_at"])
        kickoff_paid_report_for_order(order, retry_failed=True)


@transaction.atomic
def update_user_birth(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    birth_date = _parse_date(payload.get("birth_date"))
    if birth_date is None:
        raise BirthUpdateError("Нужна дата рождения.", "birth_date")

    unknown_time = _truthy(payload.get("unknown_time"))
    birth_time = None if unknown_time else _parse_time(payload.get("birth_time"))
    birth_place = str(payload.get("birth_place") or "").strip()
    birth_lat = _parse_coord(payload.get("birth_lat"))
    birth_lng = _parse_coord(payload.get("birth_lng"))
    timezone_name = str(payload.get("timezone") or "").strip()

    if not birth_place and (birth_lat is None or birth_lng is None):
        raise BirthUpdateError(
            "Нужен город рождения — по нему берём таймзону для точной Луны и Солнца.",
            "birth_place",
        )

    session = _latest_session(user)
    profile, _ = Profile.objects.get_or_create(user=user)

    chart = None
    if session is not None:
        chart = NatalChart.objects.filter(session=session).first()
    if chart is None:
        chart = (
            NatalChart.objects.filter(Q(user=user) | Q(session__user=user))
            .order_by("-updated_at")
            .first()
        )

    fields = {
        "user": user,
        "birth_date": birth_date,
        "birth_time": birth_time,
        "birth_place": birth_place,
        "birth_lat": birth_lat,
        "birth_lng": birth_lng,
        "timezone": timezone_name,
        "status": NatalChart.Status.PENDING,
        "error_message": "",
    }
    if chart is None:
        chart = NatalChart(session=session, **fields)
    else:
        if session is not None and chart.session_id is None:
            chart.session = session
        for key, value in fields.items():
            setattr(chart, key, value)
    chart.save()

    try:
        chart = calculate_and_store_chart(chart)
    except GeoLookupError as exc:
        raise BirthUpdateError(str(exc), "astro") from exc
    except NatalCalcError as exc:
        raise BirthUpdateError(public_natal_error(exc), "astro") from exc

    profile.birth_date = chart.birth_date
    profile.birth_time = chart.birth_time
    profile.birth_place = chart.birth_place
    profile.birth_lat = chart.birth_lat
    profile.birth_lng = chart.birth_lng
    profile.timezone = chart.timezone or ""
    profile.save(
        update_fields=[
            "birth_date",
            "birth_time",
            "birth_place",
            "birth_lat",
            "birth_lng",
            "timezone",
            "updated_at",
        ]
    )

    if session is not None:
        session.birth_date = chart.birth_date
        session.birth_time = chart.birth_time
        session.birth_place = chart.birth_place
        session.birth_lat = chart.birth_lat
        session.birth_lng = chart.birth_lng
        session.timezone = chart.timezone or ""
        session.user = user
        session.save(
            update_fields=[
                "birth_date",
                "birth_time",
                "birth_place",
                "birth_lat",
                "birth_lng",
                "timezone",
                "user",
                "updated_at",
            ]
        )

    _invalidate_paid_reports(user)
    return birth_snapshot(user)


@transaction.atomic
def delete_user_account(user: User) -> None:
    email = (user.email or "").strip().lower()
    session_ids = list(
        OnboardingSession.objects.filter(Q(user=user) | Q(waitlist_lead__user=user)).values_list(
            "id", flat=True
        )
    )
    Order.objects.filter(Q(user=user) | Q(session_id__in=session_ids)).delete()
    OnboardingSession.objects.filter(id__in=session_ids).delete()
    WaitlistLead.objects.filter(Q(user=user) | Q(email__iexact=email)).delete()
    user.delete()
