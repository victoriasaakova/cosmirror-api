"""Локальные фикстуры для /dev/. Не вызываются вне DEBUG."""

from __future__ import annotations

from io import StringIO
from datetime import date, time
from decimal import Decimal

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from core.models import (
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    OnboardingStepAnswer,
    Order,
    Profile,
    WaitlistLead,
)
from core.services.onboarding_astro import build_chart_and_insight
from core.services.orders import _product, _request_hash

# Данные Виктории для локального прогона отчёта.
DEV_REPORT_NAME = "Вика"
DEV_REPORT_DISPLAY_NAME = "Виктория"
DEV_REPORT_EMAIL = "saakovka@gmail.com"
DEV_REPORT_TELEGRAM = "victoriss"
DEV_REPORT_BIRTH_DATE = date(1995, 5, 26)
DEV_REPORT_BIRTH_TIME = time(19, 25)
DEV_REPORT_PLACE = "Гдыня, Польша"
DEV_REPORT_LAT = Decimal("54.516498")
DEV_REPORT_LNG = Decimal("18.540274")
DEV_REPORT_TZ = "Europe/Warsaw"

DEV_REPORT_QUIZ = {
    "name": {"name": DEV_REPORT_NAME},
    "gender": {"gender": "female"},
    "age": {"age": "25-34"},
    "life_stage": {"life_stage": "one-sphere"},
    "focus": {"focus": ["love", "path"]},
    "goal": {"intent": "potential"},
    "astrolevel": {"chart_knowledge": "natal-chart"},
    "questions": {"astrology_trigger": "understand-self"},
}


def seed_dev_paid_report(user) -> Order:
    """Сессия + натал + оплаченный заказ, чтобы кабинет сразу открыл отчёт."""
    session = _seed_dev_session(user, completed=True)
    lead = session.waitlist_lead
    if lead is None:
        lead = _upsert_lead(user)
    return _create_paid_order(user, session, lead)


def seed_dev_free_cabinet(user) -> OnboardingSession:
    """Натал есть, заказа нет: бесплатный кабинет с замками."""
    session = _seed_dev_session(user, completed=True)
    if session.current_step_slug != "account":
        session.current_step_slug = "account"
        session.save(update_fields=["current_step_slug", "updated_at"])
    return session


def seed_dev_insight_funnel(user) -> OnboardingSession:
    """Квиз и карта готовы, заказа нет: сразу инсайт → оферта → оплата."""
    return _seed_dev_session(user, completed=False)


def _seed_dev_session(user, *, completed: bool) -> OnboardingSession:
    if not OnboardingStep.objects.filter(slug="name", is_active=True).exists():
        call_command("seed_onboarding", stdout=StringIO(), verbosity=0)

    with transaction.atomic():
        _sync_dev_profile(user, onboarding_completed=completed)
        lead = _upsert_lead(user)
        session = _create_session(user, lead, completed=completed)
        _write_quiz_answers(session)
        _store_chart(user, session)
        return session


def _sync_dev_profile(user, *, onboarding_completed: bool = True) -> None:
    user.email = DEV_REPORT_EMAIL
    user.first_name = DEV_REPORT_DISPLAY_NAME
    user.save(update_fields=["email", "first_name"])
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.display_name = DEV_REPORT_DISPLAY_NAME
    profile.telegram = DEV_REPORT_TELEGRAM
    profile.birth_date = DEV_REPORT_BIRTH_DATE
    profile.birth_time = DEV_REPORT_BIRTH_TIME
    profile.birth_place = DEV_REPORT_PLACE
    profile.birth_lat = DEV_REPORT_LAT
    profile.birth_lng = DEV_REPORT_LNG
    profile.timezone = DEV_REPORT_TZ
    profile.registration_status = Profile.RegistrationStatus.ACTIVE
    profile.onboarding_completed = onboarding_completed
    profile.save()


def _upsert_lead(user) -> WaitlistLead:
    lead, _ = WaitlistLead.objects.update_or_create(
        email=DEV_REPORT_EMAIL,
        defaults={
            "name": DEV_REPORT_NAME,
            "telegram": DEV_REPORT_TELEGRAM,
            "user": user,
            "source": "local-dev",
        },
    )
    return lead


def _create_session(
    user, lead: WaitlistLead, *, completed: bool = True
) -> OnboardingSession:
    now = timezone.now()
    return OnboardingSession.objects.create(
        user=user,
        waitlist_lead=lead,
        status=(
            OnboardingSession.Status.COMPLETED
            if completed
            else OnboardingSession.Status.IN_PROGRESS
        ),
        current_step_slug="contacts",
        birth_date=DEV_REPORT_BIRTH_DATE,
        birth_time=DEV_REPORT_BIRTH_TIME,
        birth_place=DEV_REPORT_PLACE,
        birth_lat=DEV_REPORT_LAT,
        birth_lng=DEV_REPORT_LNG,
        timezone=DEV_REPORT_TZ,
        completed_at=now if completed else None,
    )


def _write_quiz_answers(session: OnboardingSession) -> None:
    slugs = list(DEV_REPORT_QUIZ.keys()) + ["birth", "contacts"]
    steps = {step.slug: step for step in OnboardingStep.objects.filter(slug__in=slugs)}
    payloads = {
        **DEV_REPORT_QUIZ,
        "birth": {
            "birth_date": DEV_REPORT_BIRTH_DATE.isoformat(),
            "birth_time": DEV_REPORT_BIRTH_TIME.strftime("%H:%M"),
            "birth_place": DEV_REPORT_PLACE,
            "birth_lat": float(DEV_REPORT_LAT),
            "birth_lng": float(DEV_REPORT_LNG),
            "timezone": DEV_REPORT_TZ,
        },
        "contacts": {
            "name": DEV_REPORT_NAME,
            "email": DEV_REPORT_EMAIL,
            "telegram": DEV_REPORT_TELEGRAM,
            "pd_consent": True,
            "offer_consent": True,
        },
    }
    for slug, payload in payloads.items():
        step = steps.get(slug)
        if step is None:
            continue
        OnboardingStepAnswer.objects.create(
            session=session,
            step=step,
            payload=payload,
            completed=True,
        )


def _store_chart(user, session: OnboardingSession) -> NatalChart:
    bundle = build_chart_and_insight(
        birth_date=DEV_REPORT_BIRTH_DATE,
        birth_time=DEV_REPORT_BIRTH_TIME,
        birth_place=DEV_REPORT_PLACE,
        birth_lat=DEV_REPORT_LAT,
        birth_lng=DEV_REPORT_LNG,
        timezone_name=DEV_REPORT_TZ,
    )
    geo = bundle["geo"]
    natal = dict(bundle["natal"])
    location = dict(natal.get("location") or {})
    location["place"] = DEV_REPORT_PLACE
    natal["location"] = location
    chart, _ = NatalChart.objects.update_or_create(
        session=session,
        defaults={
            "user": user,
            "birth_date": DEV_REPORT_BIRTH_DATE,
            "birth_time": DEV_REPORT_BIRTH_TIME,
            "birth_place": DEV_REPORT_PLACE,
            "birth_lat": geo["latitude"],
            "birth_lng": geo["longitude"],
            "timezone": geo["timezone"] or DEV_REPORT_TZ,
            "status": NatalChart.Status.READY,
            "error_message": "",
            "chart_data": {
                **natal,
                "insight": bundle["insight"],
            },
            "calculated_at": timezone.now(),
        },
    )
    return chart


def _create_paid_order(user, session: OnboardingSession, lead: WaitlistLead) -> Order:
    sku, name, amount = _product()
    now = timezone.now()
    return Order.objects.create(
        idempotency_key=f"dev-report-{user.pk}",
        idempotency_request_hash=_request_hash(str(session.token), sku, ""),
        session=session,
        waitlist_lead=lead,
        user=user,
        customer_email=DEV_REPORT_EMAIL,
        customer_telegram=DEV_REPORT_TELEGRAM,
        product_sku=sku,
        product_name=name,
        amount=amount,
        status=Order.Status.PAID,
        paid_at=now,
    )
