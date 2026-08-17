"""Персональный отчёт: натал Swiss Ephemeris + каркас длинного разбора."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.models import NatalChart, Order
from core.services.frontend import public_frontend_base
from core.services.natal import calculate_sky_now
from core.services.personalize import quiz_from_session
from core.services.report_blueprint import build_report_document, flatten_document_sections


def report_page_url(order: Order) -> str:
    """Ссылка из письма: на localhost остаётся http://localhost, иначе прод."""
    return f"{public_frontend_base()}/report/{order.public_id}/"


def build_paid_report(order: Order) -> dict[str, Any]:
    natal = _natal_for(order)
    sky: dict[str, Any] = {}
    if natal.get("planets"):
        try:
            sky = calculate_sky_now()
        except Exception:
            sky = {}

    person = _person_block(order, natal)
    quiz: dict[str, Any] = {}
    if order.session:
        try:
            quiz = quiz_from_session(order.session)
        except Exception:
            quiz = {}

    document = build_report_document(
        natal=natal,
        sky_now=sky,
        quiz=quiz,
        person=person,
    )
    sections = [
        {"id": "person", "title": "О тебе", "blocks": _person_story(person, natal)},
        *flatten_document_sections(document),
    ]

    return {
        "title": "Персональный астрологический отчёт",
        "subtitle": _subtitle(document),
        "schema_version": document.get("schema_version"),
        "person": person,
        "document": document,
        "sections": sections,
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Расчёт карты — Swiss Ephemeris. Интерпретация — гипотеза, которую стоит проверить на своём опыте."
        ),
    }


def _subtitle(document: dict[str, Any]) -> str:
    profile = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    focus = profile.get("focus_labels") or []
    if focus:
        return f"Разбор по Swiss Ephemeris · в фокусе: {', '.join(focus)}"
    return "Разбор по Swiss Ephemeris: карта, текущие периоды и твой запрос."


def _natal_for(order: Order) -> dict[str, Any]:
    chart = NatalChart.objects.filter(session=order.session).first()
    if chart and isinstance(chart.chart_data, dict) and chart.chart_data.get("planets"):
        data = dict(chart.chart_data)
        data.setdefault("location", {})
        if chart.birth_place and not data["location"].get("place"):
            data["location"]["place"] = chart.birth_place
        return data
    session = order.session
    if session and session.birth_date:
        from core.services.onboarding_astro import build_chart_and_insight

        try:
            bundle = build_chart_and_insight(
                birth_date=session.birth_date,
                birth_time=session.birth_time,
                birth_place=session.birth_place,
                birth_lat=session.birth_lat,
                birth_lng=session.birth_lng,
                timezone_name=session.timezone or "",
            )
            return {**bundle["natal"], "insight": bundle["insight"]}
        except Exception:
            return {}
    return {}


def _person_block(order: Order, natal: dict[str, Any]) -> dict[str, Any]:
    name = ""
    lead = order.waitlist_lead or (order.session.waitlist_lead if order.session else None)
    if lead and (lead.name or "").strip():
        name = lead.name.strip()
    location = natal.get("location") if isinstance(natal.get("location"), dict) else {}
    session = order.session
    birth_date = ""
    birth_time = ""
    if session and session.birth_date:
        birth_date = session.birth_date.isoformat()
        if session.birth_time:
            birth_time = session.birth_time.strftime("%H:%M")
    chart = NatalChart.objects.filter(session=order.session).first()
    if chart:
        birth_date = chart.birth_date.isoformat()
        if chart.birth_time:
            birth_time = chart.birth_time.strftime("%H:%M")
    return {
        "name": name,
        "birth_date": birth_date,
        "birth_time": birth_time,
        "birth_place": (location.get("place") or (session.birth_place if session else "") or "").strip(),
        "timezone": natal.get("timezone") or (session.timezone if session else "") or "",
        "has_birth_time": bool(natal.get("has_birth_time")),
        "engine": natal.get("engine") or "",
    }


def _fmt_date(raw: str) -> str:
    if not raw:
        return "не указана"
    try:
        return date.fromisoformat(raw[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return raw


def _person_story(person: dict[str, Any], natal: dict[str, Any]) -> list[dict[str, str]]:
    time_bit = person.get("birth_time") or "время не указано"
    place = person.get("birth_place") or "место не указано"
    name = person.get("name") or "ты"
    engine = "Swiss Ephemeris" if "swiss" in str(person.get("engine") or "") else "натальный расчёт Cosmirror"
    notes = natal.get("notes") or []
    text = (
        f"{name.capitalize() if name != 'ты' else 'Ты'}: дата рождения {_fmt_date(person.get('birth_date') or '')}, "
        f"{time_bit}, {place}."
    )
    if person.get("timezone"):
        text += f" Часовой пояс {person['timezone']}."
    text += f" Карта посчитана через {engine}."
    if notes:
        text += " " + " ".join(str(n) for n in notes if n)
    return [{"title": "Исходные данные", "text": text}]
