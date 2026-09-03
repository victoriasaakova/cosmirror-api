"""Персональный отчёт: натал Swiss Ephemeris + каркас длинного разбора."""

from __future__ import annotations

from datetime import date
from typing import Any

from core.models import NatalChart, Order
from core.services.frontend import public_frontend_base
from core.services.natal import calculate_natal, calculate_sky_now
from core.services.personalize import quiz_from_session
from core.services import llm_client
from core.services.report_blueprint import build_report_document, flatten_document_sections
from core.services.report_aspects import (
    apply_aspects_to_document,
    cached_aspects_layer,
    generate_aspects_interpretation,
    save_aspects_layer,
)
from core.services.report_cycles import (
    apply_cycles_to_document,
    cached_cycles_layer,
    generate_cycles_interpretation,
    save_cycles_layer,
)
from core.services.report_natal import (
    apply_natal_to_document,
    cached_natal_layer,
    generate_natal_interpretation,
    save_natal_layer,
)
from core.services.report_request import (
    apply_request_to_document,
    cached_request_layer,
    generate_request_interpretation,
    save_request_layer,
)
from core.services.report_practice import (
    apply_practice_to_document,
    cached_practice_layer,
    generate_practice_interpretation,
    save_practice_layer,
)


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
    # LLM-first: valid persisted source=llm always overlays fallback shell.
    # LLM_PROVIDER / is_configured only gates NEW LLM calls (kickoff/generate),
    # not read of already sealed layers.
    cached = cached_natal_layer(order, document)
    if cached:
        apply_natal_to_document(
            document,
            cached["payload"],
            source=str(cached.get("source") or "llm"),
            model=str(cached.get("model") or ""),
            sealed=True,
        )
    cached_aspects = cached_aspects_layer(order, document)
    if cached_aspects:
        apply_aspects_to_document(
            document,
            cached_aspects["payload"],
            source=str(cached_aspects.get("source") or "llm"),
            model=str(cached_aspects.get("model") or ""),
            sealed=True,
        )
    cached_cycles = cached_cycles_layer(order, document)
    if cached_cycles:
        apply_cycles_to_document(
            document,
            cached_cycles["payload"],
            source=str(cached_cycles.get("source") or "llm"),
            model=str(cached_cycles.get("model") or ""),
            error=str(cached_cycles.get("error") or ""),
            generation_status=str(cached_cycles.get("generation_status") or ""),
            sealed=True,
        )
    cached_request = cached_request_layer(order, document)
    if cached_request:
        apply_request_to_document(
            document,
            cached_request["payload"],
            source=str(cached_request.get("source") or "llm"),
            model=str(cached_request.get("model") or ""),
            error=str(cached_request.get("error") or ""),
            sealed=True,
        )
    cached_practice = cached_practice_layer(order, document)
    if cached_practice:
        apply_practice_to_document(
            document,
            cached_practice["payload"],
            source=str(cached_practice.get("source") or "llm"),
            model=str(cached_practice.get("model") or ""),
            error=str(cached_practice.get("error") or ""),
            sealed=True,
        )
    job = (order.interpretive or {}).get("generation") if isinstance(order.interpretive, dict) else None
    if isinstance(job, dict):
        interpretive = document.setdefault("interpretive", {})
        generation_meta: dict[str, Any] = {"status": str(job.get("status") or "idle")}
        current_section = str(job.get("current_section") or "").strip()
        if current_section:
            generation_meta["current_section"] = current_section
        interpretive["generation"] = generation_meta
    sections = flatten_document_sections(document)
    owner = _person_block(order, natal)

    return {
        "title": "Персональный астрологический отчёт",
        "subtitle": _subtitle(document, natal),
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


def customer_name_for_order(order: Order) -> str:
    """Имя с квиза онбординга, иначе с лида. Только для письма и PDF, не для GET кабинета."""
    session = order.session
    if session is not None:
        from core.services.personalize import quiz_from_session

        quiz_name = str(quiz_from_session(session).get("name") or "").strip()
        if quiz_name:
            return quiz_name
    lead = order.waitlist_lead
    if lead and (lead.name or "").strip():
        return lead.name.strip()
    if session and session.waitlist_lead and (session.waitlist_lead.name or "").strip():
        return session.waitlist_lead.name.strip()
    return ""


def paid_report_for_pdf(order: Order) -> dict[str, Any]:
    """Полный отчёт для PDF: имя на обложке, без публичного стрипа кабинета."""
    report = build_paid_report(order)
    person = report.get("person")
    if isinstance(person, dict):
        person["name"] = customer_name_for_order(order)
    return report


def public_paid_report(order: Order) -> dict[str, Any]:
    """Отчёт для кабинета: без ФИО, почты и внутренних payload. Дата рождения нужна шапке карты."""
    report = build_paid_report(order)
    live = natal_from_user(order.user) if order.user_id else {}
    if not live.get("planets"):
        live = natal_from_session(order.session)
    if live.get("planets"):
        from core.services.report_facts import chart_wheel, natal_aspects, natal_table

        hits = natal_aspects(live)
        report["home_natal"] = {
            "points": natal_table(live),
            "wheel": chart_wheel(live, hits),
            "has_birth_time": bool(live.get("has_birth_time")),
        }
        report["person"] = _person_block(order, live)
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
    person = report.get("person")
    if isinstance(person, dict):
        person.pop("name", None)
    return report


def generate_natal_section(order: Order, *, force: bool = False) -> dict[str, Any]:
    """Собрать слой «Твоя карта» через скилл. Повтор без force отдаёт кэш LLM."""
    from core.services.report_jobs import acquire_section, release_section

    if not llm_client.is_configured():
        return public_paid_report(order)
    report = build_paid_report(order)
    document = report.get("document")
    if not isinstance(document, dict):
        return public_paid_report(order)
    cached = cached_natal_layer(order, document)
    if cached and cached.get("source") == "llm" and not force:
        return public_paid_report(order)
    if not acquire_section(order.pk, "natal"):
        return public_paid_report(order)
    try:
        result = generate_natal_interpretation(document)
        save_natal_layer(order, document, result)
    finally:
        release_section(order.pk, "natal")
    return public_paid_report(order)


def generate_aspects_section(order: Order, *, force: bool = False) -> dict[str, Any]:
    """Собрать слой «Аспекты» через скилл. Повтор без force отдаёт кэш LLM."""
    from core.services.report_jobs import acquire_section, release_section

    if not llm_client.is_configured():
        return public_paid_report(order)
    report = build_paid_report(order)
    document = report.get("document")
    if not isinstance(document, dict):
        return public_paid_report(order)
    cached = cached_aspects_layer(order, document)
    if cached and cached.get("source") == "llm" and not force:
        return public_paid_report(order)
    if not acquire_section(order.pk, "aspects"):
        return public_paid_report(order)
    try:
        result = generate_aspects_interpretation(document)
        save_aspects_layer(order, document, result)
    finally:
        release_section(order.pk, "aspects")
    return public_paid_report(order)


def generate_cycles_section(order: Order, *, force: bool = False) -> dict[str, Any]:
    """Собрать слой «Циклы» через скилл. Повтор без force отдаёт кэш LLM."""
    from core.services.report_jobs import acquire_section, release_section

    if not llm_client.is_configured():
        return public_paid_report(order)
    report = build_paid_report(order)
    document = report.get("document")
    if not isinstance(document, dict):
        return public_paid_report(order)
    cached = cached_cycles_layer(order, document)
    if cached and cached.get("source") == "llm" and not force:
        return public_paid_report(order)
    if not acquire_section(order.pk, "cycles"):
        return public_paid_report(order)
    try:
        result = generate_cycles_interpretation(document)
        save_cycles_layer(order, document, result)
    finally:
        release_section(order.pk, "cycles")
    return public_paid_report(order)


def generate_request_section(order: Order, *, force: bool = False) -> dict[str, Any]:
    """Собрать вкладку «Запрос» через скилл paid_report_request."""
    from core.services.report_jobs import acquire_section, release_section

    if not llm_client.is_configured():
        return public_paid_report(order)
    report = build_paid_report(order)
    document = report.get("document")
    if not isinstance(document, dict):
        return public_paid_report(order)
    cached = cached_request_layer(order, document)
    if cached and cached.get("source") == "llm" and not force:
        return public_paid_report(order)
    if not acquire_section(order.pk, "request"):
        return public_paid_report(order)
    try:
        result = generate_request_interpretation(document)
        save_request_layer(order, document, result)
    finally:
        release_section(order.pk, "request")
    return public_paid_report(order)


def generate_practice_section(order: Order, *, force: bool = False) -> dict[str, Any]:
    """Собрать вкладку «Практика» через скилл paid_report_practice."""
    from core.services.report_jobs import acquire_section, release_section

    if not llm_client.is_configured():
        return public_paid_report(order)
    report = build_paid_report(order)
    document = report.get("document")
    if not isinstance(document, dict):
        return public_paid_report(order)
    cached = cached_practice_layer(order, document)
    if cached and cached.get("source") == "llm" and not force:
        return public_paid_report(order)
    if not acquire_section(order.pk, "practice"):
        return public_paid_report(order)
    try:
        result = generate_practice_interpretation(document)
        save_practice_layer(order, document, result)
    finally:
        release_section(order.pk, "practice")
    return public_paid_report(order)


def _subtitle(document: dict[str, Any], natal: dict[str, Any]) -> str:
    profile = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    house = natal.get("house_system_label") or "Плацидус"
    focus = profile.get("focus_labels") or []
    if focus:
        return f"Тропическая карта · {house} · в фокусе: {', '.join(focus)}"
    return f"Тропическая карта · {house}: положения, циклы и твой запрос."


def natal_from_session(session) -> dict[str, Any]:
    """Натал по сессии онбординга — с заказом или без."""
    if session is None:
        return {}
    chart = NatalChart.objects.filter(session=session).first()
    stored: dict[str, Any] = {}
    if chart and isinstance(chart.chart_data, dict) and chart.chart_data.get("planets"):
        stored = dict(chart.chart_data)
        stored.setdefault("location", {})
        if chart.birth_place and not stored["location"].get("place"):
            stored["location"]["place"] = chart.birth_place
    loc = stored.get("location") if isinstance(stored.get("location"), dict) else {}

    birth_date = session.birth_date
    birth_time = session.birth_time
    place = session.birth_place or loc.get("place") or ""
    tz_name = session.timezone or stored.get("timezone") or ""
    lat = session.birth_lat if session.birth_lat is not None else loc.get("lat")
    lng = session.birth_lng if session.birth_lng is not None else loc.get("lng")
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
    if session.birth_date:
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


def natal_from_user(user) -> dict[str, Any]:
    from core.models import OnboardingSession

    session = (
        OnboardingSession.objects.filter(user=user, birth_date__isnull=False)
        .order_by("-updated_at")
        .first()
    )
    if session:
        natal = natal_from_session(session)
        if natal.get("planets"):
            return natal
    chart = NatalChart.objects.filter(user=user).order_by("-id").first()
    if chart and chart.session_id:
        natal = natal_from_session(chart.session)
        if natal.get("planets"):
            return natal
    if chart and isinstance(chart.chart_data, dict) and chart.chart_data.get("planets"):
        return dict(chart.chart_data)
    return {}


def _stored_natal(order: Order) -> dict[str, Any]:
    return natal_from_session(order.session) if order.session else {}


def _natal_for(order: Order) -> dict[str, Any]:
    """Натал разбора: после правки данных в кабинете — снимок покупки, не живая карта."""
    store = order.interpretive if isinstance(order.interpretive, dict) else {}
    sealed = store.get("sealed_natal")
    if isinstance(sealed, dict) and sealed.get("planets"):
        return sealed
    return natal_from_session(order.session)


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
