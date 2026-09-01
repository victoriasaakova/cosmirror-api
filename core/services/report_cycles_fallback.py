"""
Детерминированный fallback вкладки «Циклы».

Lookup готовых transit × natal × aspect semantic units. Без runtime LLM
и без склейки TRANSIT_FN + NATAL_FN + ASPECT_FN.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from core.services.report_lexicon import (
    ASPECT_THEME,
    HOUSE_ARENA,
    PLANET_THEME,
    as_sentence,
    duration_span_sentence,
)
from core.services.report_types import (
    ASPECTS,
    PLANET_RU,
    POLARITY_PRESSURE,
    POLARITY_RESOURCE,
)

LIBRARY_PATH = (
    Path(__file__).resolve().parent.parent / "content" / "cycles_fallback_library.yaml"
)

SUPPORTED_TRANSITS = frozenset({"jupiter", "saturn", "uranus", "neptune", "pluto"})
ANGLE_TARGETS = frozenset({"ascendant", "midheaven", "asc", "mc"})
TARGET_ALIAS = {
    "ascendant": "asc",
    "midheaven": "mc",
}
MAX_CYCLES = 8
PRIMARY_COUNT = 4
MAX_SYNTHESIS = 2
ASPECT_RU = {row["key"]: row["ru"] for row in ASPECTS}
PHASE_RU = {
    "applying": "сходится",
    "exact": "точный контакт",
    "separating": "расходится",
}
# Library theme_tags ≠ theme_synthesis keys; map known tags onto authored blocks.
TAG_TO_SYNTHESIS = {
    "control_vs_uncertainty": "control_and_uncertainty",
    "control_and_uncertainty": "control_and_uncertainty",
    "safety_vs_change": "security_and_change",
    "security_and_change": "security_and_change",
    "change": "security_and_change",
    "emotional_safety": "security_and_change",
    "home_and_support": "security_and_change",
    "autonomy_vs_closeness": "relationships_and_boundaries",
    "relationships_and_boundaries": "relationships_and_boundaries",
    "relationships": "relationships_and_boundaries",
    "boundaries": "relationships_and_boundaries",
    "freedom_vs_commitment": "relationships_and_boundaries",
    "identity": "identity_and_autonomy",
    "identity_and_autonomy": "identity_and_autonomy",
    "self_expression": "identity_and_autonomy",
    "self_presentation": "identity_and_autonomy",
    "autonomy": "identity_and_autonomy",
    "expansion_and_limits": "growth_and_structure",
    "growth_and_structure": "growth_and_structure",
    "growth": "growth_and_structure",
    "structure_and_freedom": "growth_and_structure",
    "structure": "growth_and_structure",
    "meaning_and_direction": "growth_and_structure",
    "meaning": "growth_and_structure",
    "idealism_vs_realism": "clarity_and_ideal",
    "clarity_and_ideal": "clarity_and_ideal",
    "imagination": "clarity_and_ideal",
    "sensitivity_vs_boundaries": "clarity_and_ideal",
    "quality_and_action": "action_and_pressure",
    "action_and_pressure": "action_and_pressure",
    "action": "action_and_pressure",
    "intensity_vs_stability": "action_and_pressure",
    "power": "action_and_pressure",
    "deep_change": "action_and_pressure",
    "work": "work_and_role",
    "work_and_role": "work_and_role",
    "public_role": "work_and_role",
    "responsibility": "work_and_role",
}


@lru_cache(maxsize=1)
def load_cycles_fallback_library() -> dict[str, Any]:
    with LIBRARY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Cycles fallback library must be a mapping")
    units = data.get("units")
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(units, list):
        for row in units:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row
    indexed = dict(data)
    indexed["units_by_id"] = by_id
    return indexed


def category_for_polarity(polarity: str) -> str:
    if polarity == POLARITY_PRESSURE:
        return "tension"
    if polarity == POLARITY_RESOURCE:
        return "support"
    return "mixed"


def canonical_unit_key(transit: str, aspect: str, natal: str) -> str:
    return f"{_norm(transit)}_{_norm(aspect)}_{_alias_target(natal)}"


def fallback_cycles_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    library = load_cycles_fallback_library()
    ranked = ranked_hits(document)
    cards = [build_cycle_card(library, row, document) for row in ranked]
    cards = [card for card in cards if card]
    primary = cards[:PRIMARY_COUNT]
    secondary = cards[PRIMARY_COUNT:]
    themes = _select_themes(library, cards)
    overview = _period_overview_from_themes(themes) or _period_overview_from_cards(cards)
    synthesis = _cross_cycle_synthesis(library, cards, themes)
    return {
        "report_type": "current_cycles",
        "source": "fallback",
        "period_overview": overview,
        "themes": themes,
        "primary_cycles": primary,
        "secondary_cycles": secondary,
        "cross_cycle_synthesis": synthesis,
    }


def ranked_hits(document: dict[str, Any]) -> list[dict[str, Any]]:
    accents = document.get("accents") if isinstance(document.get("accents"), dict) else {}
    houses_valid = bool(((document.get("factual") or {}).get("natal") or {}).get("has_birth_time"))
    seen: list[dict[str, Any]] = []
    ids: set[str] = set()
    for bucket in ("primary", "pressure", "resource", "supporting", "upcoming"):
        for row in accents.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or "")
            if not cid or cid in ids:
                continue
            if not row.get("transit") or not row.get("natal"):
                continue
            if not houses_valid and str(row.get("natal") or "") in ANGLE_TARGETS:
                continue
            ids.add(cid)
            seen.append(row)
    if not seen:
        for row in (document.get("factual") or {}).get("transits") or []:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or "")
            if not cid or cid in ids:
                continue
            if not row.get("transit") or not row.get("natal"):
                continue
            if not houses_valid and str(row.get("natal") or "") in ANGLE_TARGETS:
                continue
            ids.add(cid)
            seen.append(row)
    seen.sort(
        key=lambda row: (
            float(row.get("orb") or 99),
            -float(row.get("weight_hint") or 0),
        )
    )
    return seen[:MAX_CYCLES]


def build_cycle_card(
    library: dict[str, Any],
    hit: dict[str, Any],
    document: dict[str, Any],
) -> Optional[dict[str, Any]]:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    if not transit or not natal or not aspect:
        return None
    houses_valid = bool(((document.get("factual") or {}).get("natal") or {}).get("has_birth_time"))
    if not houses_valid and natal in ANGLE_TARGETS:
        return None
    lookup = canonical_unit_key(transit, aspect, natal)
    units = library.get("units_by_id") if isinstance(library.get("units_by_id"), dict) else {}
    unit = units.get(lookup) if isinstance(units, dict) else None
    if isinstance(unit, dict) and transit in SUPPORTED_TRANSITS:
        return _card_from_unit(library, unit, hit, lookup)
    return _factual_card(library, hit, lookup)


def _card_from_unit(
    library: dict[str, Any],
    unit: dict[str, Any],
    hit: dict[str, Any],
    lookup: str,
) -> dict[str, Any]:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    t_name = str(hit.get("transit_name") or PLANET_RU.get(transit, transit))
    n_name = str(hit.get("natal_name") or PLANET_RU.get(natal, natal))
    aspect_ru = str(hit.get("aspect_ru") or ASPECT_RU.get(aspect) or aspect)
    deep = [str(item).strip() for item in (unit.get("deep_read") or []) if str(item).strip()]
    questions = [
        str(item).strip()
        for item in (unit.get("reflection_questions") or [])
        if str(item).strip()
    ]
    manifestations = [
        str(item).strip()
        for item in (unit.get("possible_manifestations") or [])
        if str(item).strip()
    ]
    tags = [str(tag).strip() for tag in (unit.get("theme_tags") or []) if str(tag).strip()]
    protective = str(unit.get("protective_hypothesis") or "").strip()
    flexibility = str(unit.get("flexibility") or "").strip()
    explanation = str(unit.get("astro_explanation") or "").strip()
    summary = str(unit.get("summary") or "").strip()
    headline = str(unit.get("headline") or "").strip()
    library_category = str(unit.get("category") or "").strip()
    polarity_category = category_for_polarity(str(hit.get("polarity") or "mixed"))
    category = (
        library_category
        if library_category in {"tension", "support", "mixed"}
        else polarity_category
    )
    timing = _timing(library, hit)
    return {
        "source": "semantic_fallback",
        "unit_key": lookup,
        "cycle_id": str(hit.get("id") or ""),
        "category": category,
        "technical_title": str(
            unit.get("technical_title_ru") or f"{t_name} {aspect_ru} {n_name}"
        ).strip(),
        "headline": headline,
        "human_theme": headline,
        "short_explanation": summary,
        "timing": timing,
        "astrology_explanation": explanation,
        "astro_explanation": explanation,
        "summary": summary,
        "deep_read": deep,
        "personalization": "",
        "possible_manifestations": manifestations,
        "protective_hypothesis": protective,
        "protective_function": protective,
        "tension_or_blind_spot": str(unit.get("tension_or_blind_spot") or "").strip(),
        "resource": str(unit.get("resource") or "").strip(),
        "flexibility": flexibility,
        "how_to_work": flexibility,
        "reflection_question": questions[0] if questions else "",
        "reflection_questions": questions,
        "theme_tags": tags,
        "confidence": str(unit.get("confidence") or ""),
        "transit": transit,
        "natal": natal,
        "aspect": aspect,
        "aspect_ru": aspect_ru,
        "transit_name": t_name,
        "natal_name": n_name,
        "priority_score": float(hit.get("weight_hint") or 0),
    }


def _factual_card(
    library: dict[str, Any],
    hit: dict[str, Any],
    lookup: str,
) -> dict[str, Any]:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    polarity = str(hit.get("polarity") or "mixed")
    category = category_for_polarity(polarity)
    t_name = str(hit.get("transit_name") or PLANET_RU.get(transit, transit))
    n_name = str(hit.get("natal_name") or PLANET_RU.get(natal, natal))
    aspect_ru = str(hit.get("aspect_ru") or ASPECT_RU.get(aspect) or aspect)
    aspect_clause = ASPECT_THEME.get(aspect, "две темы вступают в контакт")
    t_theme = PLANET_THEME.get(transit, "")
    n_theme = PLANET_THEME.get(natal, "")
    bits = [
        f"{t_name} {aspect_ru} {n_name} — текущий транзит к уже посчитанной карте, "
        "не черта характера и не натальный аспект."
    ]
    bits.append(f"В астрологической рамке {aspect_clause}.")
    if t_theme and n_theme:
        bits.append(
            f"Транзитный {t_name.lower()} связан с {t_theme}; "
            f"натальный {n_name.lower()} — с {n_theme}."
        )
    house = hit.get("natal_house")
    if isinstance(house, int) and house in HOUSE_ARENA:
        bits.append(f"Тема может быть заметнее {HOUSE_ARENA[house]}.")
    timing = _timing(library, hit)
    bits.append(
        "Без готовой смысловой единицы для этой пары оставляем техническое объяснение, "
        "а не собранный из словаря психологический текст."
    )
    summary = bits[0]
    explanation = " ".join(bits)
    question = (
        f"Где сейчас особенно заметно взаимодействие {t_name.lower()} "
        f"и {n_name.lower()} — в действии, отношениях, работе или ощущении себя?"
    )
    headline = f"{t_name} {aspect_ru} {n_name}"
    return {
        "source": "factual_fallback",
        "unit_key": lookup,
        "cycle_id": str(hit.get("id") or ""),
        "category": category,
        "technical_title": headline,
        "headline": headline,
        "human_theme": headline,
        "short_explanation": explanation,
        "timing": timing,
        "astrology_explanation": explanation,
        "astro_explanation": explanation,
        "summary": summary,
        "deep_read": bits[1:],
        "personalization": "",
        "possible_manifestations": [],
        "protective_hypothesis": "",
        "protective_function": "",
        "tension_or_blind_spot": "",
        "resource": "",
        "flexibility": "",
        "how_to_work": "",
        "reflection_question": question,
        "reflection_questions": [question],
        "theme_tags": [],
        "confidence": "low",
        "factual": True,
        "transit": transit,
        "natal": natal,
        "aspect": aspect,
        "aspect_ru": aspect_ru,
        "transit_name": t_name,
        "natal_name": n_name,
        "priority_score": float(hit.get("weight_hint") or 0),
    }


def _timing(library: dict[str, Any], hit: dict[str, Any]) -> dict[str, Any]:
    window = hit.get("window") if isinstance(hit.get("window"), dict) else {}
    parts: list[str] = []
    span = duration_span_sentence(str(window.get("span_note") or ""))
    if span:
        parts.append(span)
    peak = window.get("peak_estimate")
    if peak:
        parts.append(f"Оценка пика по орбу: {peak}.")
    phase = str(hit.get("motion") or "").strip()
    phase_copy = library.get("phase_copy") if isinstance(library.get("phase_copy"), dict) else {}
    phase_text = as_sentence(str(phase_copy.get(phase) or ""))
    if phase_text:
        parts.append(phase_text)
    elif phase in PHASE_RU:
        parts.append(f"Фаза: {PHASE_RU[phase]}.")
    return {
        "orb_deg": hit.get("orb"),
        "phase": phase,
        "active_window_text": " ".join(parts).strip(),
        "exact_passes_text": "",
    }


def _select_themes(library: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    syntheses = library.get("theme_synthesis") or {}
    if not isinstance(syntheses, dict) or not cards:
        return []
    support: dict[str, list[str]] = {}
    for card in cards:
        if card.get("factual"):
            continue
        unit_key = str(card.get("unit_key") or card.get("cycle_id") or "")
        mapped: set[str] = set()
        for tag in card.get("theme_tags") or []:
            theme_id = TAG_TO_SYNTHESIS.get(str(tag).strip())
            if theme_id:
                mapped.add(theme_id)
        for theme_id in mapped:
            support.setdefault(theme_id, []).append(unit_key)
    ranked: list[tuple[int, str, list[str]]] = []
    for theme_id, keys in support.items():
        unique = []
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        if len(unique) < 2:
            continue
        ranked.append((len(unique), theme_id, unique))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for _count, theme_id, keys in ranked:
        entry = syntheses.get(theme_id)
        if not isinstance(entry, dict):
            continue
        if all(key in used for key in keys):
            continue
        questions = [
            str(item).strip()
            for item in (entry.get("questions") or [])
            if str(item).strip()
        ]
        chosen.append(
            {
                "theme_id": theme_id,
                "headline": str(entry.get("headline") or "").strip(),
                "narrative": str(entry.get("narrative") or "").strip(),
                "reflection_question": questions[0] if questions else "",
                "reflection_questions": questions,
                "basis": keys,
            }
        )
        used.update(keys)
        if len(chosen) >= MAX_SYNTHESIS:
            break
    return chosen


def _period_overview_from_themes(themes: list[dict[str, Any]]) -> Optional[dict[str, str]]:
    if not themes:
        return None
    lead = themes[0]
    return {
        "headline": str(lead.get("headline") or ""),
        "summary": str(lead.get("narrative") or ""),
        "main_tension": "",
        "main_support": "",
    }


def _period_overview_from_cards(cards: list[dict[str, Any]]) -> dict[str, str]:
    if not cards:
        return {
            "headline": "Значимых персональных транзитов в текущем орбе нет",
            "summary": (
                "Это расчётный слой внешнего неба к уже посчитанной карте. "
                "Сейчас нет тесных персональных попаданий в орбе."
            ),
            "main_tension": "",
            "main_support": "",
        }
    tension = sum(1 for row in cards if row.get("category") == "tension")
    support = sum(1 for row in cards if row.get("category") == "support")
    if tension and support:
        headline = "Трение и опора звучат в одном периоде"
        summary = (
            "Это внешнее небо к уже посчитанной карте, не натальные аспекты. "
            "Ниже — текущие активации: где тема требует выбора, где есть более "
            "доступный канал. Узнаёшь в опыте — бери. Не узнаёшь — это тоже ответ."
        )
    elif tension:
        headline = "Период, где привычные способы чаще встречают сопротивление"
        summary = (
            "Сейчас заметнее внешние активации с трением. Это не прогноз события: "
            "скорее окно, где полезно отличать защитную реакцию от выбора, "
            "который лучше соответствует ситуации."
        )
    elif support:
        headline = "Период, где есть более доступные каналы"
        summary = (
            "Сейчас заметнее активации поддержки. Ресурс полезен естественностью, "
            "но его граница — не перестать проверять, зачем идёшь по привычному руслу."
        )
    else:
        headline = "Что сейчас звучит во внешнем небе"
        summary = (
            "Ниже — текущие транзиты к твоей карте. Это гипотезы периода для "
            "наблюдения, не описание судьбы и не внутренние аспекты карты."
        )
    return {
        "headline": headline,
        "summary": summary,
        "main_tension": "",
        "main_support": "",
    }


def _cross_cycle_synthesis(
    library: dict[str, Any],
    cards: list[dict[str, Any]],
    themes: list[dict[str, Any]],
) -> dict[str, Any]:
    if themes:
        lead = themes[0]
        questions = list(lead.get("reflection_questions") or [])
        if lead.get("reflection_question") and lead["reflection_question"] not in questions:
            questions = [lead["reflection_question"], *questions]
        return {
            "headline": str(lead.get("headline") or ""),
            "narrative": str(lead.get("narrative") or ""),
            "what_to_watch": [],
            "available_support": [],
            "reflection_questions": questions,
            "basis": list(lead.get("basis") or []),
        }
    counts: dict[str, list[str]] = {}
    for card in cards:
        key = str(card.get("natal") or "")
        if not key:
            continue
        counts.setdefault(key, []).append(str(card.get("unit_key") or card.get("cycle_id") or ""))
    repeated = [(natal, keys) for natal, keys in counts.items() if len(keys) >= 2]
    if not repeated:
        return {}
    natal, keys = max(repeated, key=lambda item: len(item[1]))
    natal_name = PLANET_RU.get(natal, natal)
    relations = library.get("relations") if isinstance(library.get("relations"), dict) else {}
    relation = str(relations.get("ACTIVATES_SAME_NATAL_THEME") or "").strip()
    narrative = (
        f"Несколько активных циклов затрагивают {natal_name}. "
        + (relation + " " if relation else "")
        + "Это группировка по расчёту и готовым смысловым единицам, "
        "не вывод о главном конфликте периода."
    )
    return {
        "headline": f"Несколько циклов активируют тему {natal_name}",
        "narrative": narrative.strip(),
        "what_to_watch": [],
        "available_support": [],
        "reflection_questions": [],
        "basis": keys,
    }


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _alias_target(value: str) -> str:
    key = _norm(value)
    return TARGET_ALIAS.get(key, key)
