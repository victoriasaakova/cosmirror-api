"""
Детерминированный fallback вкладки «Аспекты».

Lookup готовых pair-level semantic units. Без runtime LLM и без склейки
PLANET_FN + шаблон аспекта.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from core.services.report_lexicon import PLANET_THEME
from core.services.report_types import ASPECTS, NATAL_POINT_WEIGHT, PLANET_RU

LIBRARY_PATH = (
    Path(__file__).resolve().parent.parent / "content" / "aspects_fallback_library.yaml"
)

POINT_RANK = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "ascendant",
    "midheaven",
)
KEY_ALIAS = {
    "ascendant": "asc",
    "midheaven": "mc",
}
ANGLE_POINTS = frozenset({"ascendant", "midheaven", "asc", "mc"})
PERSONAL = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "ascendant",
    "midheaven",
}
OUTER = frozenset({"uranus", "neptune", "pluto"})
MAX_ASPECTS = 10
MAX_SYNTHESIS = 3
ASPECT_RU = {row["key"]: row["ru"] for row in ASPECTS}


@lru_cache(maxsize=1)
def load_aspects_fallback_library() -> dict[str, Any]:
    with LIBRARY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Aspects fallback library must be a mapping")
    return data


def category_for(aspect: str) -> str:
    if aspect in {"square", "opposition"}:
        return "tension"
    if aspect in {"trine", "sextile"}:
        return "resource"
    return "mixed"


def canonical_unit_key(a: str, b: str, aspect: str) -> str:
    left, right = _canonical_pair(a, b)
    return f"{_alias(left)}_{aspect}_{_alias(right)}"


def fallback_aspects_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    library = load_aspects_fallback_library()
    cards = []
    for row in ranked_aspects(document):
        card = build_aspect_card(library, row, document)
        if card:
            cards.append(card)
    themes = _select_themes(library, cards)
    intro = _intro_from_themes(themes) or _intro_from_cards(cards)
    return {
        "report_type": "natal_aspects",
        "source": "fallback",
        "intro": intro,
        "themes": themes,
        "aspects": cards,
    }


def build_aspect_card(
    library: dict[str, Any],
    row: dict[str, Any],
    document: dict[str, Any],
) -> Optional[dict[str, Any]]:
    a = str(row.get("a") or "")
    b = str(row.get("b") or "")
    aspect = str(row.get("aspect") or "")
    if not a or not b or not aspect:
        return None
    houses_valid = bool(((document.get("factual") or {}).get("natal") or {}).get("has_birth_time"))
    if not houses_valid and ({a, b} & ANGLE_POINTS):
        return None
    lookup = canonical_unit_key(a, b, aspect)
    units = library.get("aspects") if isinstance(library.get("aspects"), dict) else {}
    unit = units.get(lookup) if isinstance(units, dict) else None
    points = _points_by_key(document)
    pa = points.get(a) or {}
    pb = points.get(b) or {}
    a_name = str(row.get("a_name") or pa.get("name") or PLANET_RU.get(a) or a)
    b_name = str(row.get("b_name") or pb.get("name") or PLANET_RU.get(b) or b)
    aspect_ru = str(row.get("aspect_ru") or ASPECT_RU.get(aspect) or aspect)
    orb = _orb(row)
    if isinstance(unit, dict):
        return _card_from_unit(
            unit,
            lookup_key=lookup,
            row=row,
            a=a,
            b=b,
            a_name=a_name,
            b_name=b_name,
            aspect=aspect,
            aspect_ru=aspect_ru,
            orb=orb,
            sign_a=str(pa.get("sign") or ""),
            sign_b=str(pb.get("sign") or ""),
            house_a=pa.get("house") if houses_valid else None,
            house_b=pb.get("house") if houses_valid else None,
        )
    return _factual_card(
        lookup_key=lookup,
        row=row,
        a=a,
        b=b,
        a_name=a_name,
        b_name=b_name,
        aspect=aspect,
        aspect_ru=aspect_ru,
        orb=orb,
        sign_a=str(pa.get("sign") or ""),
        sign_b=str(pb.get("sign") or ""),
        house_a=pa.get("house") if houses_valid else None,
        house_b=pb.get("house") if houses_valid else None,
    )


def _card_from_unit(
    unit: dict[str, Any],
    *,
    lookup_key: str,
    row: dict[str, Any],
    a: str,
    b: str,
    a_name: str,
    b_name: str,
    aspect: str,
    aspect_ru: str,
    orb: float,
    sign_a: str,
    sign_b: str,
    house_a: Any,
    house_b: Any,
) -> dict[str, Any]:
    deep = [
        str(item).strip()
        for item in (unit.get("deep_read") or [])
        if str(item).strip()
    ]
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
    blind = str(unit.get("blind_spot") or "").strip()
    flexibility = str(unit.get("flexibility") or "").strip()
    library_category = str(unit.get("category") or category_for(aspect))
    runtime_category = str(row.get("category") or "").strip()
    category = runtime_category if runtime_category in {"tension", "resource", "mixed"} else library_category
    return {
        "aspect_id": _aspect_id(row),
        "unit_key": lookup_key,
        "source": "semantic_fallback",
        "category": category,
        "aspect_label_ru": str(unit.get("aspect_label_ru") or f"{a_name} {aspect_ru} {b_name}"),
        "orb_deg": orb,
        "headline": str(unit.get("headline") or "").strip(),
        "summary": str(unit.get("summary") or "").strip(),
        "deep_read": deep,
        "possible_manifestations": manifestations,
        "protective_hypothesis": str(unit.get("protective_hypothesis") or "").strip(),
        "resource": str(unit.get("resource") or "").strip(),
        "blind_spot": blind,
        "tension_or_blind_spot": blind,
        "flexibility": flexibility,
        "how_to_work": flexibility,
        "reflection_questions": questions,
        "astro_explanation": str(unit.get("astro_explanation") or "").strip(),
        "theme_tags": tags,
        "confidence": str(unit.get("confidence") or ""),
        "a": a,
        "b": b,
        "aspect": aspect,
        "aspect_ru": aspect_ru,
        "a_name": a_name,
        "b_name": b_name,
        "priority_score": _priority(row),
        "astrological_basis": {
            "planet_a": a,
            "planet_b": b,
            "aspect_type": aspect,
            "orb_deg": orb,
            "sign_a": sign_a or None,
            "sign_b": sign_b or None,
            "house_a": house_a,
            "house_b": house_b,
        },
    }


def _factual_card(
    *,
    lookup_key: str,
    row: dict[str, Any],
    a: str,
    b: str,
    a_name: str,
    b_name: str,
    aspect: str,
    aspect_ru: str,
    orb: float,
    sign_a: str,
    sign_b: str,
    house_a: Any,
    house_b: Any,
) -> dict[str, Any]:
    category = category_for(aspect)
    summary = (
        f"В натальной карте {a_name} и {b_name} образуют {aspect_ru}. "
        "Это отношение двух функций внутри карты, не текущее небо и не прогноз."
    )
    bits = [summary]
    theme_a = PLANET_THEME.get(a, "")
    theme_b = PLANET_THEME.get(b, "")
    if theme_a and theme_b:
        bits.append(
            f"В этой системе {a_name.lower()} связано с {theme_a}, "
            f"{b_name.lower()} — с {theme_b}. Аспект показывает, как эти темы уже сцеплены."
        )
    bits.append(
        "Без готовой смысловой единицы для этой пары оставляем техническое объяснение, "
        "а не собранный из словаря психологический текст."
    )
    explanation = " ".join(bits)
    question = (
        f"Где в опыте ты замечаешь взаимодействие {a_name.lower()} и {b_name.lower()} "
        "— как спор, как опору или как сцепку, которую трудно разделить?"
    )
    return {
        "aspect_id": _aspect_id(row),
        "unit_key": lookup_key,
        "source": "factual_fallback",
        "category": category,
        "aspect_label_ru": f"{a_name} {aspect_ru} {b_name}",
        "orb_deg": orb,
        "headline": f"{a_name} {aspect_ru} {b_name}",
        "summary": summary,
        "deep_read": bits[1:],
        "possible_manifestations": [],
        "protective_hypothesis": "",
        "resource": "",
        "blind_spot": "",
        "tension_or_blind_spot": "",
        "flexibility": "",
        "how_to_work": "",
        "reflection_questions": [question],
        "astro_explanation": explanation,
        "theme_tags": [],
        "confidence": "low",
        "factual": True,
        "a": a,
        "b": b,
        "aspect": aspect,
        "aspect_ru": aspect_ru,
        "a_name": a_name,
        "b_name": b_name,
        "priority_score": _priority(row),
        "astrological_basis": {
            "planet_a": a,
            "planet_b": b,
            "aspect_type": aspect,
            "orb_deg": orb,
            "sign_a": sign_a or None,
            "sign_b": sign_b or None,
            "house_a": house_a,
            "house_b": house_b,
        },
    }


def _select_themes(library: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    syntheses = library.get("theme_syntheses") or {}
    if not isinstance(syntheses, dict) or not cards:
        return []
    support: dict[str, list[str]] = {}
    for card in cards:
        if card.get("factual"):
            continue
        unit_key = str(card.get("unit_key") or "")
        for tag in card.get("theme_tags") or []:
            support.setdefault(str(tag), []).append(unit_key)
    ranked: list[tuple[int, str, list[str]]] = []
    for tag, keys in support.items():
        unique = []
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        if len(unique) < 2:
            continue
        ranked.append((len(unique), tag, unique))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for _count, tag, keys in ranked:
        entry = syntheses.get(tag)
        if not isinstance(entry, dict):
            continue
        if all(key in used for key in keys):
            continue
        chosen.append(
            {
                "theme_id": tag,
                "headline": str(entry.get("headline") or "").strip(),
                "narrative": str(entry.get("narrative") or "").strip(),
                "reflection_question": str(entry.get("question") or "").strip(),
                "basis": keys,
            }
        )
        used.update(keys)
        if len(chosen) >= MAX_SYNTHESIS:
            break
    return chosen


def _intro_from_themes(themes: list[dict[str, Any]]) -> Optional[dict[str, str]]:
    if not themes:
        return None
    lead = themes[0]
    return {
        "headline": str(lead.get("headline") or ""),
        "summary": str(lead.get("narrative") or ""),
    }


def _intro_from_cards(cards: list[dict[str, Any]]) -> dict[str, str]:
    tension = sum(1 for row in cards if row.get("category") == "tension")
    resource = sum(1 for row in cards if row.get("category") == "resource")
    if tension and resource:
        return {
            "headline": "Трение и опора уже связаны внутри",
            "summary": (
                "Это не текущее небо. Ниже — устойчивые связки двух функций: "
                "где они спорят, где поддерживают друг друга, где сливаются."
            ),
        }
    if tension:
        return {
            "headline": "Где две важные нужды редко идут одним шагом",
            "summary": (
                "Здесь больше внутренних споров, чем автоматического согласия. "
                "Напряжение не приговор: это место, где чаще приходится выбирать, "
                "какую сторону сейчас не предавать. Ресурс внутри этих связок тоже есть."
            ),
        }
    if resource:
        return {
            "headline": "Где две функции уже умеют договариваться",
            "summary": (
                "Здесь есть рабочие каналы: темы поддерживают друг друга без долгого торга. "
                "Ресурс полезен своей естественностью. Его граница — не перестать проверять, "
                "зачем ты идёшь по привычному руслу."
            ),
        }
    return {
        "headline": "Как темы внутри уже сцеплены",
        "summary": (
            "Аспект показывает отношение двух функций, не сумму двух гороскопов. "
            "Это гипотеза для проверки на опыте, не диагноз и не прогноз."
        ),
    }


def ranked_aspects(document: dict[str, Any]) -> list[dict[str, Any]]:
    natal = (document.get("factual") or {}).get("natal") or {}
    houses_valid = bool(natal.get("has_birth_time"))
    rows = [
        row
        for row in (natal.get("aspects") or [])
        if isinstance(row, dict) and row.get("a") and row.get("b")
    ]
    if not houses_valid:
        rows = [
            row
            for row in rows
            if str(row.get("a") or "") not in ANGLE_POINTS
            and str(row.get("b") or "") not in ANGLE_POINTS
        ]
    rows.sort(key=lambda row: (-_priority(row), float(row.get("orb") or 99)))
    return rows[:MAX_ASPECTS]


def _priority(row: dict[str, Any]) -> float:
    a = str(row.get("a") or "")
    b = str(row.get("b") or "")
    orb = float(row.get("orb") or 8)
    score = 0.15
    score += NATAL_POINT_WEIGHT.get(a, 0.3) * 0.35
    score += NATAL_POINT_WEIGHT.get(b, 0.3) * 0.35
    if a in PERSONAL or b in PERSONAL:
        score += 0.2
    if {a, b} <= (OUTER | {"jupiter", "saturn"}):
        score -= 0.18
    if {a, b} <= OUTER:
        score -= 0.12
    score += max(0.0, 1.0 - orb / 8.0) * 0.25
    return round(score, 4)


def _points_by_key(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    natal = (document.get("factual") or {}).get("natal") or {}
    return {
        str(row.get("key")): row
        for row in (natal.get("points") or [])
        if isinstance(row, dict) and row.get("key")
    }


def _aspect_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or f"natal_{row.get('a')}_{row.get('aspect')}_{row.get('b')}")


def _orb(row: dict[str, Any]) -> float:
    try:
        return round(float(row.get("orb") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    ia = _rank(a)
    ib = _rank(b)
    if ia <= ib:
        return a, b
    return b, a


def _rank(point: str) -> int:
    key = str(point or "").strip().lower()
    if key in {"asc", "ascendant"}:
        key = "ascendant"
    if key in {"mc", "midheaven"}:
        key = "midheaven"
    try:
        return POINT_RANK.index(key)
    except ValueError:
        return len(POINT_RANK) + 1


def _alias(point: str) -> str:
    key = str(point or "").strip().lower()
    if key in {"asc", "ascendant"}:
        return "asc"
    if key in {"mc", "midheaven"}:
        return "mc"
    return KEY_ALIAS.get(key, key)
