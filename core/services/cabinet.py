"""Free cabinet: natal wheel + signs. Interpretive tabs stay locked."""

from __future__ import annotations

from typing import Any

from core.models import OnboardingSession, OnboardingStep, OnboardingStepAnswer
from core.services.natal import calculate_sky_now
from core.services.personalize import quiz_from_session
from core.services.report import natal_from_session, natal_from_user
from core.services.report_blueprint import build_report_document
from core.services.report_types import (
    SECTION_ASPECTS,
    SECTION_CYCLES,
    SECTION_NATAL,
    SECTION_PRACTICE,
    SECTION_REQUEST,
)

LOCKED_SECTIONS = (
    SECTION_NATAL,
    SECTION_ASPECTS,
    SECTION_CYCLES,
    SECTION_REQUEST,
    SECTION_PRACTICE,
)


def session_for_user(user) -> OnboardingSession | None:
    session = (
        OnboardingSession.objects.filter(user=user, birth_date__isnull=False)
        .order_by("-updated_at")
        .first()
    )
    if session:
        return session
    from core.models import NatalChart

    chart = (
        NatalChart.objects.filter(user=user)
        .select_related("session")
        .order_by("-id")
        .first()
    )
    if chart and chart.session_id:
        return chart.session
    return (
        OnboardingSession.objects.filter(user=user)
        .order_by("-updated_at")
        .first()
    )


def build_free_cabinet(user) -> dict[str, Any] | None:
    session = session_for_user(user)
    natal = natal_from_session(session) if session else natal_from_user(user)
    if not natal.get("planets"):
        return None

    sky: dict[str, Any] = {}
    try:
        sky = calculate_sky_now()
    except Exception:
        sky = {}

    quiz: dict[str, Any] = {}
    if session:
        try:
            quiz = quiz_from_session(session)
        except Exception:
            quiz = {}

    document = build_report_document(
        natal=natal,
        sky_now=sky,
        quiz=quiz,
        person={},
    )
    document = _strip_paid_layers(document)
    owner = _person_from_session(user, session, natal)
    sections: list[dict[str, Any]] = []

    report = {
        "title": "Персональный астрологический отчёт",
        "subtitle": "Тропическая карта · Плацидус: положения и расшифровка.",
        "schema_version": document.get("schema_version"),
        "person": {
            "birth_date": owner.get("birth_date") or "",
            "birth_time": owner.get("birth_time") or "",
            "birth_place": owner.get("birth_place") or "",
            "has_birth_time": bool(owner.get("has_birth_time")),
        },
        "document": document,
        "sections": sections,
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Расчёт — Swiss Ephemeris, тропический зодиак, дома Плацидуса. "
            "Интерпретация — гипотеза, которую стоит проверить на своём опыте."
        ),
    }
    return {
        "access": "free",
        "locked_sections": list(LOCKED_SECTIONS),
        "report": report,
        "quiz": _public_quiz(quiz),
        "contacts": _contacts_from_session(session, user),
    }


def _strip_paid_layers(document: dict[str, Any]) -> dict[str, Any]:
    interpretive = document.get("interpretive")
    if isinstance(interpretive, dict):
        for key in LOCKED_SECTIONS:
            interpretive.pop(key, None)
        interpretive.pop("generation", None)
        interpretive["sections"] = {}
    sections = document.get("sections")
    if isinstance(sections, dict):
        document["sections"] = {}
    factual = document.get("factual")
    if isinstance(factual, dict):
        factual.pop("transits", None)
        natal_facts = factual.get("natal")
        if isinstance(natal_facts, dict):
            natal_facts.pop("aspects", None)
    quiz = document.get("quiz")
    if isinstance(quiz, dict):
        quiz.pop("name", None)
    document.pop("generation", None)
    accents = document.get("accents")
    if isinstance(accents, dict):
        accents.pop("upcoming", None)
        accents.pop("pressure", None)
        accents.pop("resource", None)
    return document


def _person_from_session(user, session, natal: dict[str, Any]) -> dict[str, Any]:
    location = natal.get("location") if isinstance(natal.get("location"), dict) else {}
    birth_date = ""
    birth_time = ""
    place = ""
    if session and session.birth_date:
        birth_date = session.birth_date.isoformat()
        if session.birth_time:
            birth_time = session.birth_time.strftime("%H:%M")
        place = (session.birth_place or "").strip()
    profile = getattr(user, "profile", None)
    if profile is not None:
        if profile.birth_date:
            birth_date = profile.birth_date.isoformat()
        if profile.birth_time:
            birth_time = profile.birth_time.strftime("%H:%M")
        place = place or (profile.birth_place or "").strip()
    return {
        "birth_date": birth_date,
        "birth_time": birth_time,
        "birth_place": place or (location.get("place") or ""),
        "has_birth_time": bool(natal.get("has_birth_time")),
    }


def _public_quiz(quiz: dict[str, Any]) -> dict[str, Any]:
    focus = quiz.get("focus")
    if not isinstance(focus, list):
        focus = []
    return {
        "focus": [str(item) for item in focus if str(item).strip()],
        "intent": str(quiz.get("intent") or ""),
        "life_stage": str(quiz.get("life_stage") or ""),
    }


def _contacts_from_session(session, user) -> dict[str, str]:
    email = (getattr(user, "email", "") or "").strip()
    telegram = ""
    if session is None:
        return {"email": email, "telegram": telegram}
    step = OnboardingStep.objects.filter(
        is_active=True,
        step_type=OnboardingStep.StepType.WAITLIST,
    ).first()
    if step:
        answer = OnboardingStepAnswer.objects.filter(session=session, step=step).first()
        payload = answer.payload if answer and isinstance(answer.payload, dict) else {}
        email = str(payload.get("email") or email).strip()
        telegram = str(payload.get("telegram") or "").strip()
    lead = session.waitlist_lead
    if lead:
        email = email or (lead.email or "").strip()
        telegram = telegram or (lead.telegram or "").strip()
    profile = getattr(user, "profile", None)
    if profile is not None:
        telegram = telegram or (profile.telegram or "").strip()
    return {"email": email, "telegram": telegram}
