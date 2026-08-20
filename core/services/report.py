"""Персональный отчёт: натал Swiss Ephemeris + каркас длинного разбора."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.models import NatalChart, Order
from core.services.frontend import public_frontend_base
from core.services.natal import calculate_natal, calculate_sky_now
from core.services.personalize import quiz_from_session
from core.services.report_blueprint import build_report_document, flatten_document_sections


def report_page_url(order: Order | None = None) -> str:
    """Ссылка из письма: кабинет, без публичного UUID заказа."""
    return f"{public_frontend_base()}/account/"


def build_paid_report(order: Order) -> dict[str, Any]:
    natal = _natal_for(order)
    sky: dict[str, Any] = {}
    if natal.get("planets"):
        try:
            sky = calculate_sky_now()
        except Exception:
            sky = {}

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
        person={},
    )
    sections = flatten_document_sections(document)

    return {
        "title": "Персональный астрологический отчёт",
        "subtitle": _subtitle(document, natal),
        "schema_version": document.get("schema_version"),
        "document": document,
        "sections": sections,
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Расчёт — Swiss Ephemeris, тропический зодиак, дома Плацидуса. "
            "Интерпретация — гипотеза, которую стоит проверить на своём опыте."
        ),
    }


def public_paid_report(order: Order) -> dict[str, Any]:
    """Отчёт для кабинета: без ФИО, даты рождения, почты и внутренних payload."""
    report = build_paid_report(order)
    report.pop("person", None)
    document = report.get("document")
    if isinstance(document, dict):
        quiz = document.get("quiz")
        if isinstance(quiz, dict):
            quiz.pop("name", None)
        generation = document.get("generation")
        if isinstance(generation, dict):
            generation.pop("payload", None)
        natal = ((document.get("factual") or {}).get("natal") or {})
        if isinstance(natal, dict):
            natal.pop("location", None)
    return report


def _subtitle(document: dict[str, Any], natal: dict[str, Any]) -> str:
    profile = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    house = natal.get("house_system_label") or "Плацидус"
    focus = profile.get("focus_labels") or []
    if focus:
        return f"Тропическая карта · {house} · в фокусе: {', '.join(focus)}"
    return f"Тропическая карта · {house}: положения, циклы и твой запрос."


def _stored_natal(order: Order) -> dict[str, Any]:
    chart = NatalChart.objects.filter(session=order.session).first()
    if chart and isinstance(chart.chart_data, dict) and chart.chart_data.get("planets"):
        data = dict(chart.chart_data)
        data.setdefault("location", {})
        if chart.birth_place and not data["location"].get("place"):
            data["location"]["place"] = chart.birth_place
        return data
    return {}


def _natal_for(order: Order) -> dict[str, Any]:
    """Пересчитываем Плацидус из данных рождения, чтобы старые whole-sign карты не залипали."""
    stored = _stored_natal(order)
    session = order.session
    loc = stored.get("location") if isinstance(stored.get("location"), dict) else {}
    chart = NatalChart.objects.filter(session=order.session).first() if session else None

    birth_date = session.birth_date if session else None
    birth_time = session.birth_time if session else None
    place = (session.birth_place if session else "") or loc.get("place") or ""
    tz_name = (session.timezone if session else "") or stored.get("timezone") or ""
    lat = (session.birth_lat if session else None) or loc.get("lat")
    lng = (session.birth_lng if session else None) or loc.get("lng")
    if chart:
        birth_date = birth_date or chart.birth_date
        birth_time = birth_time or chart.birth_time
        place = place or chart.birth_place

    if birth_date and lat not in (None, "") and lng not in (None, "") and tz_name:
        try:
            natal = calculate_natal(
                birth_date=birth_date,
                birth_time=birth_time,
                latitude=float(lat),
                longitude=float(lng),
                timezone_name=str(tz_name),
                place=str(place or ""),
            )
            if natal.get("planets"):
                return natal
        except Exception:
            pass
    if stored:
        return stored
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
    house = natal.get("house_system_label") or "Плацидус"
    notes = natal.get("notes") or []
    who = name.capitalize() if name != "ты" else "Ты"
    text = (
        f"{who}: дата рождения {_fmt_date(person.get('birth_date') or '')}, "
        f"{time_bit}, {place}."
    )
    if person.get("timezone"):
        text += f" Часовой пояс {person['timezone']}."
    text += f" Карта: Swiss Ephemeris, тропический зодиак, дома {house}."
    if notes:
        text += " " + " ".join(str(n) for n in notes if n)
    return [{"title": "Исходные данные", "text": text}]
