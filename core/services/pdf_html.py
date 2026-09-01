"""View-model и HTML для WeasyPrint PDF — те же карточки, что в кабинете, все раскрыты."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.services.natal_wheel_svg import render_natal_wheel_svg
from core.services.report_types import PLANET_GLYPH, PLANET_RU

VS15 = "\uFE0E"
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "pdf"

ZODIAC_GLYPH = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"]
SIGN_KEYS = [
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
]
MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
ASPECT_GLYPH = {
    "conjunction": "☌",
    "opposition": "☍",
    "square": "□",
    "trine": "△",
    "sextile": "⚹",
    "quincunx": "⚻",
}
ASPECT_RU = {
    "conjunction": "соединение",
    "opposition": "оппозиция",
    "square": "квадрат",
    "trine": "тригон",
    "sextile": "секстиль",
    "quincunx": "квинконс",
}
BODY_KEYS = [
    "north_node",
    "south_node",
    "midheaven",
    "ascendant",
    "descendant",
    "mercury",
    "jupiter",
    "neptune",
    "saturn",
    "uranus",
    "chiron",
    "vesta",
    "pluto",
    "venus",
    "mars",
    "moon",
    "sun",
    "ic",
]
ASPECT_KEYS = ["conjunction", "opposition", "quincunx", "sextile", "square", "trine"]
NATAL_GROUPS = [
    {"title": "Солнце, Луна, Асцендент", "keys": ["sun", "moon", "ascendant"]},
    {"title": "Как работает твой ум", "keys": ["mercury"]},
    {"title": "Близость и отношения", "keys": ["venus"]},
    {"title": "Воля, энергия и действие", "keys": ["mars"]},
    {"title": "Работа, реализация и вклад", "keys": ["jupiter", "saturn", "midheaven"]},
    {"title": "Где ещё звучит напряжение и глубина", "keys": ["uranus", "neptune", "pluto"]},
]
CORE = ("sun", "moon", "ascendant")
SECTION_BY_POINT = {
    "mercury": "mind",
    "venus": "relationships",
    "mars": "action",
    "jupiter": "work",
    "saturn": "work",
    "midheaven": "work",
}
TEXT_LABELS = {"Asc", "MC", "Ds", "IC"}
CHAPTERS = (
    ("natal", "Твоя карта"),
    ("aspects", "Аспекты"),
    ("cycles", "Циклы"),
    ("request", "Запрос"),
    ("practice", "Практика"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_glyph(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if value in TEXT_LABELS or value.endswith(VS15):
        return value
    return f"{value}{VS15}"


def sign_glyph(sign: str | None = None, sign_index: int | None = None) -> str:
    index = sign_index if isinstance(sign_index, int) else -1
    if index < 0 or index > 11:
        key = (sign or "").lower()
        index = SIGN_KEYS.index(key) if key in SIGN_KEYS else -1
    if index < 0 or index > 11:
        return ""
    return _text_glyph(ZODIAC_GLYPH[index])


def planet_glyph(key: str | None = None, fallback: str = "") -> str:
    raw = PLANET_GLYPH.get(key or "", "") or fallback or ""
    return _text_glyph(raw)


def aspect_glyph(aspect: str | None = None) -> str:
    if not aspect:
        return ""
    return _text_glyph(ASPECT_GLYPH.get(aspect, ""))


def format_dms(degree: Any = None, minute: Any = None) -> str:
    try:
        deg = int(degree)
    except (TypeError, ValueError):
        return ""
    try:
        mins = int(minute or 0)
    except (TypeError, ValueError):
        mins = 0
    return f"{deg}°{mins:02d}′"


def format_orb(orb: Any) -> str:
    try:
        value = float(orb)
    except (TypeError, ValueError):
        return ""
    if value == int(value):
        return f"орб {int(value)}°"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"орб {text}°"


def natal_meaning(fact: str) -> str:
    if not fact:
        return ""
    return fact.split(" Это может проявляться")[0].strip()


def format_birth_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return raw
    return f"{parsed.day} {MONTHS_RU[parsed.month - 1]} {parsed.year}"


def format_birth_time(raw: str) -> str:
    return (raw or "")[:5]


def _same_copy(left: str, right: str) -> bool:
    return " ".join(left.split()).lower() == " ".join(right.split()).lower()


def _deep_read_paragraphs(deep: Any) -> list[str]:
    if isinstance(deep, list):
        return [_text(item) for item in deep if _text(item)]
    text = _text(deep)
    return [text] if text else []


def _without_contained(body: str, fragment: str) -> str:
    fragment_text = fragment.strip()
    if not fragment_text or not body or fragment_text not in body:
        return body
    return " ".join(body.replace(fragment_text, "").split())


def _visible_manifestations(items: Any, deep_read: Any) -> list[str]:
    deep_text = "\n".join(_deep_read_paragraphs(deep_read))
    seen: set[str] = set()
    visible: list[str] = []
    for raw in items or []:
        item = _text(raw)
        if not item or item in seen or item in deep_text:
            continue
        seen.add(item)
        visible.append(item)
        if len(visible) >= 3:
            break
    return visible


def _is_takeaway(block: dict[str, Any]) -> bool:
    return block.get("kind") == "user_takeaway" or _text(block.get("title")) == "Твой вывод"


def _section_blocks(section: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(section, dict):
        return []
    out = []
    for block in section.get("blocks") or []:
        if not isinstance(block, dict) or _is_takeaway(block):
            continue
        title = _text(block.get("title"))
        text = _text(block.get("text"))
        if title or text:
            out.append({"title": title, "text": text})
    return out


def _alias_body(token: str) -> str:
    if token == "asc":
        return "ascendant"
    if token == "mc":
        return "midheaven"
    if token == "ds":
        return "descendant"
    return token


def _take_keyed(parts: list[str], keys: list[str], alias=None) -> tuple[str, list[str]]:
    if not parts:
        return "", parts
    first = alias(parts[0]) if alias else parts[0]
    shifted = [first, *parts[1:]] if first != parts[0] else parts
    for key in keys:
        tokens = key.split("_")
        if shifted[: len(tokens)] == tokens:
            return key, shifted[len(tokens) :]
    return "", parts


def parse_astro_pair_id(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    parts = [part for part in raw.lower().replace("-", "_").split("_") if part]
    if parts and parts[0] in {"t", "natal"}:
        parts = parts[1:]
    left, rest = _take_keyed(parts, BODY_KEYS, _alias_body)
    if not left:
        return None
    aspect, tail = _take_keyed(rest, ASPECT_KEYS)
    if not aspect:
        return None
    right, _ = _take_keyed(tail, BODY_KEYS, _alias_body)
    if not right:
        return None
    return {"left": left, "aspect": aspect, "right": right}


def astro_pair_label(pair: dict[str, str]) -> str:
    return " ".join(
        part
        for part in (
            PLANET_RU.get(pair.get("left") or "", ""),
            ASPECT_RU.get(pair.get("aspect") or "", ""),
            PLANET_RU.get(pair.get("right") or "", ""),
        )
        if part
    )


def _gpair_class(kind: str | None, aspect: str | None) -> str:
    if kind == "soft" or aspect in {"trine", "sextile"}:
        return "soft"
    if kind == "hard" or aspect in {"square", "opposition", "conjunction"}:
        return "hard"
    return ""


def _tag_class(category: str | None) -> str:
    if category in {"tension", "pressure"}:
        return "hard"
    if category in {"resource", "support"}:
        return "soft"
    if category == "mixed":
        return "mixed"
    return "hard"


def _category_label(category: str | None, *, cycles: bool = False) -> str:
    if category in {"tension", "pressure"}:
        return "напряжение"
    if category == "resource" or (cycles and category == "support"):
        return "ресурс"
    if category == "mixed":
        return "смешанное"
    return ""


def _placement_copy(point: dict[str, Any], natal: dict[str, Any] | None) -> dict[str, Any]:
    natal = natal if isinstance(natal, dict) else {}
    key = _text(point.get("key"))
    for row in natal.get("placements") or []:
        if isinstance(row, dict) and _text(row.get("point_key")) == key:
            paragraphs = row.get("paragraphs") or []
            if not paragraphs:
                paragraphs = [row.get("summary"), *(row.get("deep_read") or [])]
            return {
                "headline": _text(row.get("headline")),
                "paragraphs": [_text(item) for item in paragraphs if _text(item)],
                "question": "",
                "house_modifier": _text(row.get("house_modifier")),
                "why": _text(row.get("astro_explanation")),
            }
    if key in CORE:
        card = ((natal.get("big_three") or {}).get(key) or {})
        if isinstance(card, dict) and _text(card.get("body")):
            return {
                "headline": "",
                "paragraphs": [_text(card.get("body"))],
                "question": _text(card.get("question")),
                "house_modifier": "",
                "why": "",
            }
    section_id = SECTION_BY_POINT.get(key)
    if section_id and section_id != "work":
        copied = _section_copy(next((row for row in natal.get("sections") or [] if row.get("id") == section_id), None))
        if copied["paragraphs"]:
            return copied
    if key == "saturn":
        copied = _section_copy(next((row for row in natal.get("sections") or [] if row.get("id") == "work"), None))
        if copied["paragraphs"]:
            return copied
    fact = _text(point.get("fact"))
    return {
        "headline": "",
        "paragraphs": [fact] if fact else [],
        "question": "",
        "house_modifier": "",
        "why": "",
    }


def _section_copy(section: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {"headline": "", "paragraphs": [], "question": "", "house_modifier": "", "why": ""}
    paragraphs = [_text(section.get("summary")), *(_text(item) for item in section.get("deep_read") or [])]
    return {
        "headline": "",
        "paragraphs": [item for item in paragraphs if item],
        "question": _text(section.get("question")),
        "house_modifier": "",
        "why": "",
    }


def _marks_for_point(key: str, aspects: list[dict[str, Any]], glyphs: dict[str, str]) -> list[dict[str, Any]]:
    rows = [row for row in aspects if row.get("a") == key or row.get("b") == key]
    rows.sort(key=lambda row: float(row.get("orb") or 99))
    marks = []
    for row in rows[:6]:
        other_key = _text(row.get("b") if row.get("a") == key else row.get("a"))
        other_name = _text(row.get("b_name") if row.get("a") == key else row.get("a_name"))
        aspect = _text(row.get("aspect"))
        orb = format_orb(row.get("orb"))
        label = " ".join(part for part in (_text(row.get("aspect_ru")), other_name) if part)
        if orb:
            label = f"{label} · {orb}" if label else orb
        marks.append(
            {
                "class": _gpair_class(_text(row.get("kind")), aspect),
                "glyphs": " ".join(part for part in (aspect_glyph(aspect), planet_glyph(other_key, glyphs.get(other_key, ""))) if part),
                "label": label,
            }
        )
    return marks


def _marks_for_section(section_id: str, aspects: list[dict[str, Any]], glyphs: dict[str, str]) -> list[dict[str, Any]]:
    rows = list(aspects)
    if section_id == "resource":
        rows = [row for row in aspects if row.get("kind") == "soft"]
    elif section_id == "flexibility":
        rows = [row for row in aspects if row.get("kind") == "hard"]
    elif section_id == "inner_conflict":
        sun_moon = [
            row
            for row in aspects
            if (row.get("a") == "sun" and row.get("b") == "moon") or (row.get("a") == "moon" and row.get("b") == "sun")
        ]
        rows = sun_moon or [
            row
            for row in aspects
            if row.get("kind") == "hard" and (row.get("a") in CORE[:2] or row.get("b") in CORE[:2])
        ]
    marks = []
    for row in rows[:6]:
        a_key = _text(row.get("a"))
        b_key = _text(row.get("b"))
        aspect = _text(row.get("aspect"))
        label = " ".join(part for part in (_text(row.get("a_name")), _text(row.get("aspect_ru")), _text(row.get("b_name"))) if part)
        marks.append(
            {
                "class": _gpair_class(_text(row.get("kind")), aspect),
                "glyphs": " ".join(
                    part
                    for part in (
                        planet_glyph(a_key, glyphs.get(a_key, "")),
                        aspect_glyph(aspect),
                        planet_glyph(b_key, glyphs.get(b_key, "")),
                    )
                    if part
                ),
                "label": label,
            }
        )
    return marks


def _planet_card(point: dict[str, Any], natal: dict[str, Any] | None, aspects: list, glyphs: dict[str, str]) -> dict[str, Any]:
    copy = _placement_copy(point, natal)
    house = point.get("house")
    house_bits = []
    if house:
        house_bits.append(f"дом {house}")
    if point.get("retrograde"):
        house_bits.append("ретроградный")
    sign = _text(point.get("sign_ru"))
    name = _text(point.get("name"))
    title = f"{name} в {sign}" if sign else name
    return {
        "glyphs": " ".join(part for part in (planet_glyph(point.get("key"), _text(point.get("glyph"))), sign_glyph(point.get("sign"))) if part),
        "title": title,
        "house": " · ".join(house_bits),
        "headline": copy["headline"],
        "paragraphs": copy["paragraphs"],
        "house_modifier": copy["house_modifier"],
        "why": copy["why"],
        "question": copy["question"],
        "marks": _marks_for_point(_text(point.get("key")), aspects, glyphs),
    }


def _theme_blocks(themes: Any) -> list[dict[str, str]]:
    out = []
    for theme in themes or []:
        if not isinstance(theme, dict):
            continue
        item = {
            "headline": _text(theme.get("headline")),
            "narrative": _text(theme.get("narrative")),
            "question": _text(theme.get("reflection_question")),
        }
        if any(item.values()):
            out.append(item)
    return out


def _resolve_pair(document: dict[str, Any], source_id: str | None = None, source_type: str | None = None) -> dict[str, str] | None:
    identity = _text(source_id)
    if not identity:
        return None
    kind = _text(source_type)
    interpretive = document.get("interpretive") if isinstance(document.get("interpretive"), dict) else {}
    if kind in {"", "cycle"}:
        payload = ((interpretive.get("cycles") or {}).get("payload") or {})
        cards = [*(payload.get("primary_cycles") or []), *(payload.get("secondary_cycles") or [])]
        for card in cards:
            if not isinstance(card, dict):
                continue
            if _text(card.get("cycle_id")) == identity or _text(card.get("unit_key")) == identity:
                if card.get("transit") and card.get("natal"):
                    pair = {"left": _text(card.get("transit")), "aspect": _text(card.get("aspect")), "right": _text(card.get("natal"))}
                    label = _text(card.get("technical_title")) or " ".join(
                        part for part in (_text(card.get("transit_name")), _text(card.get("aspect_ru")), _text(card.get("natal_name"))) if part
                    )
                    return {**pair, "label": label or astro_pair_label(pair)}
    if kind in {"", "aspect"}:
        cards = (((interpretive.get("aspects") or {}).get("payload") or {}).get("aspects") or [])
        for card in cards:
            if not isinstance(card, dict):
                continue
            if _text(card.get("aspect_id")) == identity or _text(card.get("unit_key")) == identity:
                if card.get("a") and card.get("b"):
                    pair = {"left": _text(card.get("a")), "aspect": _text(card.get("aspect")), "right": _text(card.get("b"))}
                    label = " ".join(part for part in (_text(card.get("a_name")), _text(card.get("aspect_ru")), _text(card.get("b_name"))) if part)
                    return {**pair, "label": label or astro_pair_label(pair)}
    parsed = parse_astro_pair_id(identity)
    if not parsed:
        return None
    return {**parsed, "label": astro_pair_label(parsed)}


def _pair_caption(pair: dict[str, str] | None, glyphs: dict[str, str]) -> dict[str, str] | None:
    if not pair:
        return None
    left = planet_glyph(pair.get("left"), glyphs.get(pair.get("left") or "", ""))
    right = planet_glyph(pair.get("right"), glyphs.get(pair.get("right") or "", ""))
    aspect = aspect_glyph(pair.get("aspect"))
    glyphs_text = " ".join(part for part in (left, aspect, right) if part)
    label = _text(pair.get("label"))
    if not glyphs_text and not label:
        return None
    return {"glyphs": glyphs_text, "label": label, "class": _gpair_class(None, pair.get("aspect"))}


def _source_captions(document: dict[str, Any], ids: Any, glyphs: dict[str, str]) -> list[dict[str, str]]:
    out = []
    for identity in ids or []:
        caption = _pair_caption(_resolve_pair(document, _text(identity)), glyphs)
        if caption:
            out.append(caption)
    return out


def _natal_view(document: dict[str, Any]) -> dict[str, Any]:
    natal_layer = ((document.get("interpretive") or {}).get("natal") or {})
    natal = natal_layer.get("payload") if isinstance(natal_layer, dict) else {}
    natal = natal if isinstance(natal, dict) else {}
    factual = ((document.get("factual") or {}).get("natal") or {})
    points = [row for row in (factual.get("points") or []) if isinstance(row, dict)]
    houses = [row for row in (factual.get("houses") or []) if isinstance(row, dict)]
    aspects = [row for row in (factual.get("aspects") or []) if isinstance(row, dict)]
    by_key = {_text(row.get("key")): row for row in points}
    glyphs = {_text(row.get("key")): _text(row.get("glyph")) for row in points}
    using_library = bool(natal.get("placements"))
    portrait = natal.get("core_portrait") if isinstance(natal.get("core_portrait"), dict) else {}
    grouped_keys = {key for group in NATAL_GROUPS for key in group["keys"]}
    groups = []
    for group in NATAL_GROUPS:
        items = [by_key[key] for key in group["keys"] if key in by_key]
        if not items:
            continue
        groups.append(
            {
                "title": group["title"],
                "cards": [_planet_card(point, natal, aspects, glyphs) for point in items],
            }
        )
    leftover = [
        point
        for point in points
        if _text(point.get("key")) not in CORE and _text(point.get("key")) not in grouped_keys
    ]
    if leftover:
        groups.append(
            {
                "title": "Что ещё звучит в карте",
                "cards": [_planet_card(point, natal, aspects, glyphs) for point in leftover],
            }
        )
    extra_groups = []
    if not using_library:
        for section in natal.get("sections") or []:
            if not isinstance(section, dict) or section.get("id") not in {"inner_conflict", "resource", "flexibility"}:
                continue
            copy = _section_copy(section)
            extra_groups.append(
                {
                    "title": _text(section.get("title")),
                    "cards": [
                        {
                            "glyphs": "",
                            "title": _text(section.get("headline") or section.get("title")),
                            "house": "",
                            "headline": "",
                            "paragraphs": copy["paragraphs"],
                            "house_modifier": "",
                            "why": "",
                            "question": copy["question"],
                            "marks": _marks_for_section(_text(section.get("id")), aspects, glyphs),
                        }
                    ],
                }
            )
    house_cells = []
    for house in houses:
        occupants = [planet_glyph(key, glyphs.get(key, "")) for key, point in by_key.items() if point.get("house") == house.get("house")]
        house_cells.append(
            {
                "number": house.get("house"),
                "glyph": sign_glyph(house.get("sign")),
                "sign": _text(house.get("sign_ru")),
                "theme": _text(house.get("theme")),
                "in": " ".join(part for part in occupants if part) or ", ".join(house.get("occupants") or []),
            }
        )
    return {
        "portrait_themes": _theme_blocks(portrait.get("themes")) if using_library else [],
        "portrait_headline": "" if using_library else _text(portrait.get("headline")),
        "portrait_summary": "" if using_library else _text(portrait.get("summary")),
        "groups": groups,
        "extra_groups": extra_groups,
        "repeating_themes": _theme_blocks(natal.get("repeating_themes")),
        "questions": [_text(item) for item in (natal.get("reflection_questions") or []) if _text(item)] if using_library else [],
        "limitations": " ".join(_text(item) for item in (natal.get("limitations") or []) if _text(item)),
        "houses": house_cells,
    }


def _aspect_card(card: dict[str, Any], glyphs: dict[str, str]) -> dict[str, Any]:
    a_key = _text(card.get("a"))
    b_key = _text(card.get("b"))
    aspect = _text(card.get("aspect"))
    pair_label = " ".join(part for part in (_text(card.get("a_name")), _text(card.get("aspect_ru")), _text(card.get("b_name"))) if part)
    headline = _text(card.get("headline"))
    return {
        "tag_class": _tag_class(_text(card.get("category"))),
        "tag": _category_label(card.get("category")),
        "orb": format_orb(card.get("orb_deg") if card.get("orb_deg") is not None else card.get("orb")),
        "pair": " ".join(part for part in (planet_glyph(a_key, glyphs.get(a_key, "")), aspect_glyph(aspect), planet_glyph(b_key, glyphs.get(b_key, ""))) if part),
        "name": pair_label,
        "headline": headline if headline and not _same_copy(headline, pair_label) else "",
        "lead": [_text(card.get("summary")), *_deep_read_paragraphs(card.get("deep_read"))],
        "manifestations": _visible_manifestations(card.get("possible_manifestations"), card.get("deep_read")),
        "resource": _text(card.get("resource")),
        "tension": _text(card.get("tension_or_blind_spot") or card.get("blind_spot")),
        "work": _text(card.get("how_to_work") or card.get("flexibility")),
        "questions": [_text(item) for item in (card.get("reflection_questions") or []) if _text(item)],
        "astro": _text(card.get("astro_explanation")),
        "why_label": pair_label,
    }


def _aspects_view(document: dict[str, Any]) -> dict[str, Any]:
    payload = (((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {})
    payload = payload if isinstance(payload, dict) else {}
    intro = payload.get("intro") if isinstance(payload.get("intro"), dict) else {}
    themes = payload.get("themes") or []
    extra = themes[1:] if intro.get("headline") and themes and (themes[0] or {}).get("headline") == intro.get("headline") else themes
    points = ((document.get("factual") or {}).get("natal") or {}).get("points") or []
    glyphs = {_text(row.get("key")): _text(row.get("glyph")) for row in points if isinstance(row, dict)}
    cards = [_aspect_card(card, glyphs) for card in payload.get("aspects") or [] if isinstance(card, dict)]
    return {
        "headline": _text(intro.get("headline")),
        "summary": _text(intro.get("summary"))
        or "Это связи внутри карты, не текущее небо. Аспект показывает, как две темы уже сцеплены: трение, поддержка, растяжка или слияние.",
        "themes": _theme_blocks(extra),
        "cards": cards,
        "empty": not cards and not (((document.get("factual") or {}).get("natal") or {}).get("aspects") or []),
    }


def _is_compact_cycle(card: dict[str, Any]) -> bool:
    source = _text(card.get("source"))
    if source in {"llm", "semantic_fallback"}:
        return False
    if source in {"factual_fallback", "fallback"}:
        return True
    deep = _deep_read_paragraphs(card.get("deep_read"))
    return not (card.get("resource") or card.get("protective_function") or card.get("protective_hypothesis") or len(deep) > 1)


def _cycle_card(card: dict[str, Any], glyphs: dict[str, str]) -> dict[str, Any]:
    timing = card.get("timing") if isinstance(card.get("timing"), dict) else {}
    pair_label = _text(card.get("technical_title")) or " ".join(
        part for part in (_text(card.get("transit_name")), _text(card.get("aspect_ru")), _text(card.get("natal_name"))) if part
    )
    theme = _text(card.get("human_theme") or card.get("headline"))
    window = _text(timing.get("active_window_text"))
    compact = _is_compact_cycle(card)
    lead = [_without_contained(_text(item), window) for item in [_text(card.get("summary")), *_deep_read_paragraphs(card.get("deep_read"))]]
    rest = [
        _text(card.get("personalization")),
        _text(card.get("protective_function") or card.get("protective_hypothesis")),
        _text(card.get("resource")),
        _text(card.get("tension_or_blind_spot")),
        _text(card.get("how_to_work") or card.get("flexibility")),
    ]
    t_key = _text(card.get("transit"))
    n_key = _text(card.get("natal"))
    return {
        "compact": compact,
        "tag_class": _tag_class(_text(card.get("category"))),
        "tag": _category_label(card.get("category"), cycles=True),
        "orb": format_orb(timing.get("orb_deg")),
        "phase": _text(timing.get("phase")),
        "pair": " ".join(
            part
            for part in (planet_glyph(t_key), aspect_glyph(card.get("aspect")), planet_glyph(n_key, glyphs.get(n_key, "")))
            if part
        ),
        "name": pair_label,
        "headline": theme if theme and not _same_copy(theme, pair_label) else "",
        "window": window,
        "explanation": _without_contained(_text(card.get("short_explanation") or card.get("summary")), window) if compact else "",
        "lead": [item for item in lead if item],
        "rest": [item for item in rest if item],
        "manifestations": _visible_manifestations(card.get("possible_manifestations"), card.get("deep_read")),
        "questions": [_text(item) for item in (card.get("reflection_questions") or []) if _text(item)],
        "fallback_question": _text(card.get("reflection_question") or (card.get("reflection_questions") or [None])[0]),
        "astro": _text(card.get("astro_explanation") or card.get("astrology_explanation")),
        "why_label": pair_label,
    }


def _cycles_view(document: dict[str, Any]) -> dict[str, Any]:
    layer = (document.get("interpretive") or {}).get("cycles") or {}
    payload = layer.get("payload") if isinstance(layer, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    overview = payload.get("period_overview") if isinstance(payload.get("period_overview"), dict) else {}
    cards_raw = [*(payload.get("primary_cycles") or []), *(payload.get("secondary_cycles") or [])]
    points = ((document.get("factual") or {}).get("natal") or {}).get("points") or []
    glyphs = {_text(row.get("key")): _text(row.get("glyph")) for row in points if isinstance(row, dict)}
    cards = [_cycle_card(card, glyphs) for card in cards_raw if isinstance(card, dict)]
    rich = any(not card["compact"] for card in cards)
    degraded = _text(layer.get("source") if isinstance(layer, dict) else "") != "llm" and not rich
    synthesis = payload.get("cross_cycle_synthesis") if isinstance(payload.get("cross_cycle_synthesis"), dict) else {}
    return {
        "headline": _text(overview.get("headline")),
        "summary": _text(overview.get("summary"))
        or "Это внешнее небо к уже посчитанной карте. Не путать с натальными аспектами: те во вкладке «Аспекты».",
        "degraded": degraded,
        "cards": cards,
        "empty": not cards,
        "synthesis_headline": _text(synthesis.get("headline"))
        or ("Какие точки карты затронуты" if degraded else "Как эти периоды встречаются"),
        "synthesis": _text(synthesis.get("narrative")),
        "synthesis_questions": [_text(item) for item in (synthesis.get("reflection_questions") or []) if _text(item)],
    }


def _request_view(document: dict[str, Any]) -> dict[str, Any]:
    payload = (((document.get("interpretive") or {}).get("request") or {}).get("payload") or {})
    payload = payload if isinstance(payload, dict) else {}
    section = (document.get("sections") or {}).get("request") if isinstance(document.get("sections"), dict) else {}
    points = ((document.get("factual") or {}).get("natal") or {}).get("points") or []
    glyphs = {_text(row.get("key")): _text(row.get("glyph")) for row in points if isinstance(row, dict)}
    if not payload:
        return {"fallback_blocks": _section_blocks(section), "empty": not _section_blocks(section)}
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    distinction = payload.get("core_distinction") or payload.get("core_pattern")
    distinction = distinction if isinstance(distinction, dict) else {}
    resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
    connections = []
    for row in payload.get("connections") or []:
        if not isinstance(row, dict):
            continue
        connections.append(
            {
                "title": _text(row.get("title")),
                "text": _text(row.get("text")),
                "pair": _pair_caption(_resolve_pair(document, row.get("source_id") or row.get("source"), row.get("source_type")), glyphs),
            }
        )
    return {
        "fallback_blocks": [],
        "request_title": _text(request.get("title")),
        "request_text": _text(request.get("text")),
        "connections": connections,
        "distinction_title": _text(distinction.get("title")) or "Главное различение",
        "distinction_text": _text(distinction.get("text")),
        "distinction_pairs": _source_captions(document, (payload.get("core_distinction") or {}).get("provenance") if isinstance(payload.get("core_distinction"), dict) else None, glyphs),
        "resource_title": _text(resource.get("title")) or "На что можно опереться",
        "resource_text": _text(resource.get("text")),
        "resource_pair": _pair_caption(_resolve_pair(document, resource.get("source_id") or resource.get("source"), resource.get("source_type")), glyphs),
        "takeaway": _text(payload.get("takeaway")),
        "empty": False,
    }


def _practice_view(document: dict[str, Any]) -> dict[str, Any]:
    payload = (((document.get("interpretive") or {}).get("practice") or {}).get("payload") or {})
    payload = payload if isinstance(payload, dict) else {}
    section = (document.get("sections") or {}).get("practice") if isinstance(document.get("sections"), dict) else {}
    questions = payload.get("reflection_questions") if payload else None
    if questions is None:
        questions = section.get("questions") if isinstance(section, dict) else []
    points = ((document.get("factual") or {}).get("natal") or {}).get("points") or []
    glyphs = {_text(row.get("key")): _text(row.get("glyph")) for row in points if isinstance(row, dict)}
    if not payload:
        return {
            "fallback_blocks": _section_blocks(section),
            "questions": [_text(item) for item in (questions or []) if _text(item)],
            "empty": not _section_blocks(section) and not questions,
        }
    start = payload.get("start_here") if isinstance(payload.get("start_here"), dict) else {}
    pattern = payload.get("pattern") if isinstance(payload.get("pattern"), dict) else {}
    experiment = payload.get("experiment") if isinstance(payload.get("experiment"), dict) else {}
    extras = []
    for row in (payload.get("protective_function"), payload.get("cost"), payload.get("values")):
        if isinstance(row, dict) and (_text(row.get("title")) or _text(row.get("text"))):
            extras.append({"title": _text(row.get("title")), "text": _text(row.get("text"))})
    distinctions = []
    for row in payload.get("key_distinctions") or []:
        if not isinstance(row, dict):
            continue
        left, right = _text(row.get("left")), _text(row.get("right"))
        if left or right:
            distinctions.append({"pair": f"{left} ≠ {right}", "note": _text(row.get("note"))})
    return {
        "fallback_blocks": [],
        "start_headline": _text(start.get("headline")),
        "start_text": _text(start.get("text")),
        "start_pairs": _source_captions(document, start.get("provenance") or payload.get("provenance"), glyphs),
        "pattern_title": _text(pattern.get("title")),
        "pattern_text": _text(pattern.get("text")),
        "pattern_pairs": _source_captions(document, pattern.get("source_ids"), glyphs),
        "extras": extras,
        "distinctions": distinctions,
        "questions": [_text(item) for item in (questions or []) if _text(item)],
        "experiment_title": _text(experiment.get("title")) or "Попробуй проверить",
        "experiment_text": _text(experiment.get("text")),
        "experiment_duration": _text(experiment.get("duration")),
        "observe": [_text(item) for item in (payload.get("observe_over_time") or []) if _text(item)],
        "empty": False,
    }


def _trio(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {_text(row.get("key")): row for row in points}
    labels = {"sun": "Солнце", "moon": "Луна", "ascendant": "Асцендент"}
    items = []
    for key in CORE:
        point = by_key.get(key) or {}
        dms = format_dms(point.get("degree"), point.get("minute"))
        house = f"дом {point['house']}" if point.get("house") else ""
        items.append(
            {
                "glyphs": " ".join(part for part in (planet_glyph(key, _text(point.get("glyph"))), sign_glyph(point.get("sign"))) if part),
                "name": labels[key],
                "sign": _text(point.get("sign_ru")) or "не считаем",
                "dms": " · ".join(part for part in (dms, house) if part),
                "fact": natal_meaning(_text(point.get("fact"))),
            }
        )
    return items


def _positions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for point in points:
        rows.append(
            {
                "glyph": planet_glyph(point.get("key"), _text(point.get("glyph"))),
                "name": _text(point.get("name")),
                "retro": bool(point.get("retrograde")),
                "sign": _text(point.get("sign_ru")),
                "dms": format_dms(point.get("degree"), point.get("minute")),
                "house": str(point["house"]) if point.get("house") else "",
            }
        )
    return rows


def build_pdf_context(report: dict[str, Any]) -> dict[str, Any]:
    document = report.get("document") if isinstance(report.get("document"), dict) else {}
    person = report.get("person") if isinstance(report.get("person"), dict) else {}
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    natal = ((document.get("factual") or {}).get("natal") or {})
    natal = natal if isinstance(natal, dict) else {}
    points = [row for row in (natal.get("points") or []) if isinstance(row, dict)]
    wheel = natal.get("wheel") if isinstance(natal.get("wheel"), dict) else {}
    name = _text(person.get("name") or quiz.get("name"))
    disclaimer = _text(report.get("disclaimer")) or (
        "Это не прогноз будущего и не замена терапии. "
        "Расчёт — Swiss Ephemeris, тропический зодиак, дома Плацидуса. "
        "Интерпретация — гипотеза, которую стоит проверить на своём опыте."
    )
    return {
        "title": _text(report.get("title")) or "Персональный астрологический отчёт",
        "name": name,
        "birth_date": format_birth_date(_text(person.get("birth_date"))),
        "birth_time": format_birth_time(_text(person.get("birth_time"))),
        "birth_place": _text(person.get("birth_place")),
        "generated": datetime.now().strftime("%d.%m.%Y"),
        "trio": _trio(points),
        "wheel_svg": render_natal_wheel_svg(wheel) if wheel.get("planets") else "",
        "positions": _positions(points),
        "natal": _natal_view(document),
        "aspects": _aspects_view(document),
        "cycles": _cycles_view(document),
        "request": _request_view(document),
        "practice": _practice_view(document),
        "chapters": [{"id": key, "title": title} for key, title in CHAPTERS],
        "disclaimer": disclaimer,
    }


def render_report_html(report: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("report.html").render(**build_pdf_context(report))
