"""
Детерминированный fallback вкладки «Твоя карта».

Lookup готовых semantic units из YAML. Без runtime LLM и без склейки
фраз из «планета + знак + дом».
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from core.services.report_lexicon import PLANET_THEME, SIGN_IN, SIGN_THEME
from core.services.report_types import PLANET_RU

LIBRARY_PATH = (
    Path(__file__).resolve().parent.parent / "content" / "natal_fallback_library.yaml"
)

PLACEMENT_ORDER = (
    "sun",
    "moon",
    "ascendant",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
)
PERSONAL_POINTS = frozenset(
    {"sun", "moon", "ascendant", "mercury", "venus", "mars"}
)
HIGH_PRIORITY = frozenset({"sun", "moon", "ascendant"})
MAX_SYNTHESIS = 4
CORE_THEME_COUNT = 2
MAX_QUESTIONS = 5

SECTION_FOR = {
    "mercury": ("mind", "Как работает твой ум"),
    "venus": ("relationships", "Близость и отношения"),
    "mars": ("action", "Воля, энергия и действие"),
    "jupiter": ("expansion", "Смысл и расширение"),
    "saturn": ("work", "Работа, реализация и вклад"),
}

NO_TIME_ASC = {
    "headline": "Асцендент без надёжного времени не читаем",
    "body": (
        "Без времени рождения Асцендент и дома не используем как факт карты. "
        "Солнце и Луна читаются по дате. Если появится надёжное время — "
        "можно будет отдельно посмотреть, как ты входишь в контакт."
    ),
    "why": "",
    "question": (
        "Если появится время рождения — что в том, как тебя встречают, "
        "хотелось бы проверить первым?"
    ),
}

PORTRAIT_WITHOUT_SYNTHESIS = {
    "headline": "Карта как набор рабочих гипотез",
    "summary": (
        "Ниже — готовые смысловые единицы по уже посчитанным положениям. "
        "Это гипотезы символической системы для проверки на опыте, "
        "а не описание характера и не прогноз."
    ),
}


@lru_cache(maxsize=1)
def load_natal_fallback_library() -> dict[str, Any]:
    with LIBRARY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Natal fallback library must be a mapping")
    return data


def fallback_natal_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    factual = (document.get("factual") or {}).get("natal") or {}
    by_key = {
        str(row.get("key")): row
        for row in (factual.get("points") or [])
        if isinstance(row, dict) and row.get("key")
    }
    houses_valid = bool(factual.get("has_birth_time"))
    library = load_natal_fallback_library()

    placements: list[dict[str, Any]] = []
    for point_key in PLACEMENT_ORDER:
        row = by_key.get(point_key)
        if point_key == "ascendant" and not houses_valid:
            continue
        if not row:
            continue
        card = _placement_card(
            library,
            point_key=point_key,
            row=row,
            houses_valid=houses_valid,
        )
        if card:
            placements.append(card)

    themes = _select_themes(library, placements)
    core_themes = themes[:CORE_THEME_COUNT]
    repeating_themes = themes[CORE_THEME_COUNT:]
    questions = _select_questions(placements, themes)
    limitations: list[str] = []
    if not houses_valid:
        limitations.append(
            "Время рождения не надёжно: Асцендент и дома не интерпретируем. "
            "Солнце и Луна читаются по дате."
        )

    if core_themes:
        portrait = {
            "headline": str(core_themes[0].get("headline") or "")[:90],
            "summary": " ".join(
                str(theme.get("narrative") or "").strip()
                for theme in core_themes
                if str(theme.get("narrative") or "").strip()
            ),
            "themes": core_themes,
        }
    else:
        portrait = {
            **PORTRAIT_WITHOUT_SYNTHESIS,
            "themes": [],
        }

    return {
        "report_type": "natal",
        "source": "fallback",
        "core_portrait": portrait,
        "repeating_themes": repeating_themes,
        "placements": placements,
        "big_three": _big_three_from_placements(placements, by_key, houses_valid),
        "sections": _sections_from_placements(placements),
        "reflection_questions": questions,
        "limitations": limitations,
    }


def _placement_card(
    library: dict[str, Any],
    *,
    point_key: str,
    row: dict[str, Any],
    houses_valid: bool,
) -> Optional[dict[str, Any]]:
    sign = _sign_key(row)
    lookup_key = _lookup_key(point_key, sign)
    unit = _lookup_unit(library, point_key, lookup_key)
    house_modifier = _house_modifier(library, row, houses_valid)
    if unit:
        return _card_from_unit(
            unit,
            lookup_key=lookup_key,
            point_key=point_key,
            row=row,
            house_modifier=house_modifier,
        )
    return _factual_card(
        point_key=point_key,
        lookup_key=lookup_key or f"{point_key}_{sign or 'unknown'}",
        row=row,
        house_modifier=house_modifier,
    )


def _lookup_key(point_key: str, sign: str) -> str:
    if not sign:
        return ""
    if point_key == "ascendant":
        return f"asc_{sign}"
    return f"{point_key}_{sign}"


def _lookup_unit(
    library: dict[str, Any],
    point_key: str,
    lookup_key: str,
) -> Optional[dict[str, Any]]:
    if not lookup_key:
        return None
    if point_key == "ascendant":
        block = library.get("ascendants") or {}
    else:
        block = library.get("placements") or {}
    unit = block.get(lookup_key)
    return unit if isinstance(unit, dict) else None


def _card_from_unit(
    unit: dict[str, Any],
    *,
    lookup_key: str,
    point_key: str,
    row: dict[str, Any],
    house_modifier: Optional[str],
) -> dict[str, Any]:
    deep = [
        str(item).strip()
        for item in (unit.get("deep_read") or [])
        if str(item).strip()
    ]
    tags = [
        str(tag).strip()
        for tag in (unit.get("theme_tags") or [])
        if str(tag).strip()
    ]
    return {
        "key": lookup_key,
        "point_key": point_key,
        "body": str(unit.get("body") or PLANET_RU.get(point_key) or row.get("name") or ""),
        "sign": str(unit.get("sign") or row.get("sign_ru") or ""),
        "headline": str(unit.get("headline") or "").strip(),
        "summary": str(unit.get("summary") or "").strip(),
        "deep_read": deep,
        "protective_hypothesis": str(unit.get("protective_hypothesis") or "").strip(),
        "resource": str(unit.get("resource") or "").strip(),
        "blind_spot": str(unit.get("blind_spot") or "").strip(),
        "flexibility": str(unit.get("flexibility") or "").strip(),
        "reflection_question": str(unit.get("reflection_question") or "").strip(),
        "astro_explanation": str(unit.get("astro_explanation") or "").strip(),
        "house_modifier": house_modifier,
        "theme_tags": tags,
        "paragraphs": _readable_paragraphs(unit),
    }


def _readable_paragraphs(unit: dict[str, Any]) -> list[str]:
    summary = str(unit.get("summary") or "").strip()
    seen: set[str] = set()
    paragraphs: list[str] = []
    for item in [summary, *(unit.get("deep_read") or [])]:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)
    blob = " ".join(paragraphs)
    extras: list[str] = []
    resource = str(unit.get("resource") or "").strip()
    blind = str(unit.get("blind_spot") or "").strip()
    flexibility = str(unit.get("flexibility") or "").strip()
    protective = str(unit.get("protective_hypothesis") or "").strip()
    if protective and protective not in blob:
        extras.append(protective)
    if resource and resource not in blob:
        extras.append(resource)
    if blind and blind not in blob:
        extras.append(blind)
    if flexibility and flexibility not in blob:
        extras.append(flexibility)
    paragraphs.extend(extras)
    return paragraphs


def _factual_card(
    *,
    point_key: str,
    lookup_key: str,
    row: dict[str, Any],
    house_modifier: Optional[str],
) -> dict[str, Any]:
    name = str(row.get("name") or PLANET_RU.get(point_key) or point_key)
    sign = _sign_key(row)
    sign_ru = str(row.get("sign_ru") or "")
    in_sign = SIGN_IN.get(sign, f"в {sign_ru}" if sign_ru else "")
    planet_theme = PLANET_THEME.get(point_key, "")
    sign_theme = SIGN_THEME.get(sign, "")
    summary = f"{name} {in_sign}.".strip()
    explanation_bits = [
        f"{name} {in_sign}".strip(),
    ]
    if planet_theme:
        explanation_bits.append(f"В этой системе {name.lower()} связано с {planet_theme}.")
    if sign_theme:
        explanation_bits.append(f"{sign_ru or sign} добавляет тему {sign_theme}.")
    explanation_bits.append(
        "Это техническое положение карты, а не готовая персональная интерпретация."
    )
    explanation = " ".join(part for part in explanation_bits if part)
    paragraphs = [summary, explanation]
    return {
        "key": lookup_key,
        "point_key": point_key,
        "body": name,
        "sign": sign_ru,
        "headline": summary,
        "summary": summary,
        "deep_read": [explanation],
        "protective_hypothesis": "",
        "resource": "",
        "blind_spot": "",
        "flexibility": "",
        "reflection_question": (
            f"Узнаёшь ли ты в опыте что-то связанное с тем, как у тебя проявляется {name.lower()}?"
        ),
        "astro_explanation": explanation,
        "house_modifier": house_modifier,
        "theme_tags": [],
        "paragraphs": paragraphs,
        "factual": True,
    }


def _house_modifier(
    library: dict[str, Any],
    row: dict[str, Any],
    houses_valid: bool,
) -> Optional[str]:
    if not houses_valid:
        return None
    house = row.get("house")
    try:
        number = int(house)
    except (TypeError, ValueError):
        return None
    if number < 1 or number > 12:
        return None
    block = library.get("house_modifiers") or {}
    entry = block.get(number) or block.get(str(number))
    if not isinstance(entry, dict):
        return None
    text = str(entry.get("modifier") or "").strip()
    return text or None


def _select_themes(
    library: dict[str, Any],
    placements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    syntheses = library.get("theme_synthesis") or {}
    if not isinstance(syntheses, dict) or not placements:
        return []
    support: dict[str, list[dict[str, Any]]] = {}
    for card in placements:
        for tag in card.get("theme_tags") or []:
            support.setdefault(str(tag), []).append(card)

    ranked: list[tuple[tuple[int, int, int, int], str, list[dict[str, Any]]]] = []
    for tag, units in support.items():
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for unit in units:
            key = str(unit.get("key") or "")
            if key in seen:
                continue
            seen.add(key)
            unique.append(unit)
        if len(unique) < 2:
            continue
        has_high = any(unit.get("point_key") in HIGH_PRIORITY for unit in unique)
        has_personal = any(unit.get("point_key") in PERSONAL_POINTS for unit in unique)
        score = (
            len(unique),
            1 if has_high else 0,
            1 if has_personal else 0,
            -len(ranked),
        )
        ranked.append((score, tag, unique))
    ranked.sort(key=lambda item: item[0], reverse=True)

    chosen: list[dict[str, Any]] = []
    used_basis: set[str] = set()
    for _score, tag, units in ranked:
        entry = syntheses.get(tag)
        if not isinstance(entry, dict):
            continue
        basis = [str(unit.get("key") or "") for unit in units if unit.get("key")]
        if not basis:
            continue
        overlap = sum(1 for key in basis if key in used_basis)
        if overlap == len(basis):
            continue
        chosen.append(
            {
                "theme_id": tag,
                "headline": str(entry.get("headline") or "").strip(),
                "narrative": str(entry.get("narrative") or "").strip(),
                "reflection_question": str(entry.get("reflection_question") or "").strip(),
                "basis": basis,
            }
        )
        used_basis.update(basis)
        if len(chosen) >= MAX_SYNTHESIS:
            break
    return chosen


def _select_questions(
    placements: list[dict[str, Any]],
    themes: list[dict[str, Any]],
) -> list[str]:
    by_point = {str(card.get("point_key")): card for card in placements}
    picks: list[str] = []

    def add(question: str) -> None:
        text = str(question or "").strip()
        if text and text not in picks and len(picks) < MAX_QUESTIONS:
            picks.append(text)

    add(str((by_point.get("moon") or {}).get("reflection_question") or ""))
    add(str((by_point.get("sun") or {}).get("reflection_question") or ""))
    add(str((by_point.get("venus") or {}).get("reflection_question") or ""))
    add(str((by_point.get("mars") or {}).get("reflection_question") or ""))
    if themes:
        add(str(themes[0].get("reflection_question") or ""))
    add(str((by_point.get("saturn") or {}).get("reflection_question") or ""))
    add(str((by_point.get("mercury") or {}).get("reflection_question") or ""))
    add(str((by_point.get("ascendant") or {}).get("reflection_question") or ""))
    add(str((by_point.get("jupiter") or {}).get("reflection_question") or ""))
    return picks


def _big_three_from_placements(
    placements: list[dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    houses_valid: bool,
) -> dict[str, dict[str, str]]:
    by_point = {str(card.get("point_key")): card for card in placements}
    out: dict[str, dict[str, str]] = {}
    for key in ("sun", "moon"):
        card = by_point.get(key)
        out[key] = _ui_card(card) if card else {
            "headline": PLANET_RU.get(key, key),
            "body": str((by_key.get(key) or {}).get("fact") or ""),
            "why": "",
            "question": "",
        }
    if by_point.get("ascendant"):
        out["ascendant"] = _ui_card(by_point["ascendant"])
    elif not houses_valid:
        out["ascendant"] = dict(NO_TIME_ASC)
    else:
        row = by_key.get("ascendant") or {}
        out["ascendant"] = {
            "headline": "Асцендент",
            "body": str(row.get("fact") or ""),
            "why": "",
            "question": "",
        }
    return out


def _ui_card(card: dict[str, Any]) -> dict[str, str]:
    paragraphs = [str(item).strip() for item in (card.get("paragraphs") or []) if str(item).strip()]
    if not paragraphs:
        paragraphs = [
            str(card.get("summary") or "").strip(),
            *[str(item).strip() for item in (card.get("deep_read") or [])],
        ]
    body = " ".join(part for part in paragraphs if part)
    return {
        "headline": str(card.get("headline") or ""),
        "body": body,
        "why": str(card.get("astro_explanation") or ""),
        "question": str(card.get("reflection_question") or ""),
    }


def _sections_from_placements(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_point = {str(card.get("point_key")): card for card in placements}
    sections: list[dict[str, Any]] = []
    for point_key, (section_id, title) in SECTION_FOR.items():
        card = by_point.get(point_key)
        if not card:
            continue
        sections.append(
            {
                "id": section_id,
                "title": title,
                "headline": str(card.get("headline") or title),
                "summary": str(card.get("summary") or ""),
                "deep_read": list(card.get("deep_read") or []),
                "why": str(card.get("astro_explanation") or ""),
                "question": str(card.get("reflection_question") or ""),
            }
        )
    return sections


def _sign_key(row: dict[str, Any]) -> str:
    return str(row.get("sign") or "").strip().lower()
