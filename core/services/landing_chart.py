"""Лендинг: Swiss-колесо без интерпретации и без завершения шага birth."""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any, Optional

from core.models import NatalChart, OnboardingSession
from core.services.geo import GeoLookupError, resolve_birth_geo
from core.services.natal import NatalCalcError, calculate_natal
from core.services.natal_common import public_natal_error
from core.services.onboarding_astro import _parse_date, _parse_time
from core.services.report_facts import chart_wheel, natal_aspects
from django.utils import timezone


def natal_from_chart_data(chart_data: dict[str, Any] | None) -> dict[str, Any]:
    natal = dict(chart_data or {})
    natal.pop("insight", None)
    return natal


def wheel_from_natal(natal: dict[str, Any]) -> dict[str, Any]:
    return chart_wheel(natal, natal_aspects(natal))


def _same_birth(
    chart: NatalChart,
    *,
    birth_date: date,
    birth_time: Optional[time],
    latitude: float,
    longitude: float,
) -> bool:
    if chart.status != NatalChart.Status.READY or not chart.chart_data:
        return False
    if chart.birth_date != birth_date:
        return False
    stored_time = chart.birth_time
    if (stored_time is None) != (birth_time is None):
        return False
    if stored_time is not None and birth_time is not None and stored_time != birth_time:
        return False
    if chart.birth_lat is None or chart.birth_lng is None:
        return False
    return (
        abs(float(chart.birth_lat) - latitude) < 1e-4
        and abs(float(chart.birth_lng) - longitude) < 1e-4
    )


def _payload(session: OnboardingSession, wheel: dict[str, Any]) -> dict[str, Any]:
    birth_time = session.birth_time
    return {
        "token": str(session.token),
        "has_birth_time": bool(wheel.get("has_birth_time")),
        "wheel": wheel,
        "birth": {
            "birth_date": session.birth_date.isoformat() if session.birth_date else None,
            "birth_time": birth_time.strftime("%H:%M") if birth_time else None,
            "birth_place": session.birth_place or "",
            "birth_lat": float(session.birth_lat) if session.birth_lat is not None else None,
            "birth_lng": float(session.birth_lng) if session.birth_lng is not None else None,
            "timezone": session.timezone or "",
        },
    }


def wheel_for_session(session: OnboardingSession) -> dict[str, Any]:
    chart = NatalChart.objects.filter(session=session).first()
    if chart is None or chart.status != NatalChart.Status.READY:
        raise LookupError("chart_missing")
    natal = natal_from_chart_data(chart.chart_data)
    if not natal:
        raise LookupError("chart_missing")
    return _payload(session, wheel_from_natal(natal))


def calculate_landing_wheel(
    *,
    token: str | None,
    birth_date: str | date,
    birth_time: str | time | None,
    unknown_time: bool,
    birth_place: str,
    birth_lat: float | None,
    birth_lng: float | None,
    timezone_name: str,
    user=None,
) -> dict[str, Any]:
    session = None
    if token:
        try:
            session = OnboardingSession.objects.filter(token=uuid.UUID(str(token))).first()
        except (ValueError, TypeError):
            session = None
    if session is None:
        session = OnboardingSession.objects.create()
    if user is not None and getattr(user, "is_authenticated", False) and not session.user_id:
        session.user = user
        session.save(update_fields=["user"])

    existing = NatalChart.objects.filter(session=session).first()
    if existing and existing.status == NatalChart.Status.READY and existing.chart_data:
        natal = natal_from_chart_data(existing.chart_data)
        return _payload(session, wheel_from_natal(natal))

    parsed_date = _parse_date(birth_date)
    parsed_time = None if unknown_time else _parse_time(birth_time)
    geo = resolve_birth_geo(
        place=birth_place or None,
        latitude=float(birth_lat) if birth_lat not in (None, "") else None,
        longitude=float(birth_lng) if birth_lng not in (None, "") else None,
        timezone=timezone_name or None,
    )

    session.birth_date = parsed_date
    session.birth_time = parsed_time
    session.birth_place = geo.place
    session.birth_lat = geo.latitude
    session.birth_lng = geo.longitude
    session.timezone = geo.timezone
    session.save(
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

    chart = NatalChart.objects.filter(session=session).first()
    if chart and _same_birth(
        chart,
        birth_date=parsed_date,
        birth_time=parsed_time,
        latitude=geo.latitude,
        longitude=geo.longitude,
    ):
        natal = natal_from_chart_data(chart.chart_data)
        return _payload(session, wheel_from_natal(natal))

    chart, _created = NatalChart.objects.update_or_create(
        session=session,
        defaults={
            "user": session.user,
            "birth_date": parsed_date,
            "birth_time": parsed_time,
            "birth_place": geo.place,
            "birth_lat": geo.latitude,
            "birth_lng": geo.longitude,
            "timezone": geo.timezone,
            "status": NatalChart.Status.PENDING,
            "error_message": "",
        },
    )
    if session.user_id and chart.user_id != session.user_id:
        chart.user = session.user
        chart.save(update_fields=["user"])

    try:
        natal = calculate_natal(
            birth_date=parsed_date,
            birth_time=parsed_time,
            latitude=geo.latitude,
            longitude=geo.longitude,
            timezone_name=geo.timezone,
            place=geo.place,
        )
    except NatalCalcError as exc:
        chart.status = NatalChart.Status.FAILED
        chart.error_message = str(exc)
        chart.chart_data = {}
        chart.calculated_at = None
        chart.save(
            update_fields=["status", "error_message", "chart_data", "calculated_at", "updated_at"]
        )
        raise

    chart.chart_data = natal
    chart.status = NatalChart.Status.READY
    chart.error_message = ""
    chart.calculated_at = timezone.now()
    chart.save()
    return _payload(session, wheel_from_natal(natal))


__all__ = [
    "GeoLookupError",
    "NatalCalcError",
    "calculate_landing_wheel",
    "public_natal_error",
    "wheel_for_session",
]
