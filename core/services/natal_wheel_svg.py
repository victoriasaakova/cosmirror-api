"""SVG натального колеса из wheel JSON — та же геометрия, что NatalWheel.tsx."""

from __future__ import annotations

import math
from typing import Any
from xml.sax.saxutils import escape

VS15 = "\uFE0E"
ACCENT = "#F6E7A1"
ASTRO_FONT = "Noto Sans Symbols 2, Apple Symbols, Segoe UI Symbol, sans-serif"
TEXT_FONT = "Onest, ui-sans-serif, system-ui, sans-serif"

CX = 250.0
CY = 250.0
R_OUT = 200.0
R_ZODIAC_IN = 176.0
R_TICK_INNER = 160.0
R_PLANET = 138.0
R_DEGREE = 114.0
R_HOUSE_OUTER = 84.0
R_HOUSE_INNER = 72.0
R_HOUSE_NUM = (R_HOUSE_INNER + R_HOUSE_OUTER) / 2
R_ASPECT = 66.0
R_ANGLE_MARK_IN = R_TICK_INNER
R_ANGLE_MARK_OUT = R_ZODIAC_IN
R_ANGLE_LABEL = R_TICK_INNER - 8
MIN_LABEL_PX = 22.0

ZODIAC_GLYPH = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"]

PLANET_GLYPH = {
    "sun": "☉",
    "moon": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "uranus": "♅",
    "neptune": "♆",
    "pluto": "♇",
    "north_node": "☊",
    "south_node": "☋",
    "chiron": "⚷",
    "vesta": "⚶",
}

CLASSICAL = {
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
}
OUTER = {"uranus", "neptune", "pluto"}
WHEEL_ASPECTS = {"square", "opposition", "trine", "sextile"}


def _normalize(value: float) -> float:
    return ((value % 360) + 360) % 360


def _angular_gap(a: float, b: float) -> float:
    diff = abs(_normalize(a) - _normalize(b))
    return min(diff, 360 - diff)


def _xy(asc: float, lon: float, r: float) -> tuple[float, float]:
    theta = math.radians(asc - lon)
    return CX - r * math.cos(theta), CY - r * math.sin(theta)


def _round(value: float) -> float:
    return round(value, 2)


def _house_mid(start: float, end: float) -> float:
    span = _normalize(end - start)
    return _normalize(start + span / 2)


def _dms(planet: dict[str, Any]) -> str:
    lon = float(planet.get("longitude") or 0)
    degree = planet.get("degree")
    if not isinstance(degree, (int, float)):
        degree = math.floor(_normalize(lon) % 30)
    minute = planet.get("minute")
    if not isinstance(minute, (int, float)):
        minute = 0
    rx = "R" if planet.get("retrograde") else ""
    return f"{int(degree)}°{int(minute):02d}′{rx}"


def _glyph_of(planet: dict[str, Any]) -> str:
    key = str(planet.get("key") or "")
    raw = PLANET_GLYPH.get(key) or str(planet.get("glyph") or "")
    if not raw and planet.get("name"):
        raw = str(planet.get("name"))[:1]
    return f"{raw}{VS15}" if raw else ""


def _sign_glyph(index: int) -> str:
    return f"{ZODIAC_GLYPH[index % 12]}{VS15}"


def _min_sep_deg() -> float:
    return (MIN_LABEL_PX / R_DEGREE) * (180 / math.pi)


def _place_bodies(planets: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    sorted_planets = sorted(planets, key=lambda row: _normalize(float(row.get("longitude") or 0)))
    display = [_normalize(float(row.get("longitude") or 0)) for row in sorted_planets]
    min_deg = _min_sep_deg()
    n = len(display)
    if n > 1:
        for _ in range(40):
            moved = False
            for i in range(n):
                j = (i + 1) % n
                gap = _angular_gap(display[i], display[j])
                if gap >= min_deg:
                    continue
                extra = (min_deg - gap) / 2
                display[i] = _normalize(display[i] - extra)
                display[j] = _normalize(display[j] + extra)
                moved = True
            if not moved:
                break
    return list(zip(sorted_planets, display))


def _visible_aspects(aspects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in aspects:
        a = str(row.get("a") or "")
        b = str(row.get("b") or "")
        if a not in CLASSICAL or b not in CLASSICAL:
            continue
        if a in OUTER and b in OUTER:
            continue
        kind = str(row.get("aspect") or "")
        if kind not in WHEEL_ASPECTS:
            continue
        orb = row.get("orb")
        if kind == "sextile" and isinstance(orb, (int, float)) and float(orb) > 3.5:
            continue
        out.append(row)
    return out


def _tick_inner_r(lon: int) -> float:
    if lon % 10 == 0:
        return R_ZODIAC_IN - 11
    if lon % 5 == 0:
        return R_ZODIAC_IN - 7
    return R_ZODIAC_IN - 4


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str,
    opacity: float,
    width: float,
    dash: str | None = None,
) -> str:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{_round(x1)}" y1="{_round(y1)}" x2="{_round(x2)}" y2="{_round(y2)}" '
        f'stroke="{stroke}" stroke-opacity="{opacity}" stroke-width="{width}"{extra}/>'
    )


def _circle(cx: float, cy: float, r: float, *, stroke: str, opacity: float, width: float = 1) -> str:
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{stroke}" stroke-opacity="{opacity}" stroke-width="{width}"/>'
    )


def _text(
    x: float,
    y: float,
    content: str,
    *,
    fill: str,
    size: float,
    family: str,
    opacity: float = 1,
    weight: int = 400,
    baseline: str = "middle",
) -> str:
    return (
        f'<text x="{_round(x)}" y="{_round(y)}" fill="{fill}" fill-opacity="{opacity}" '
        f'font-size="{size}" font-family="{escape(family)}" font-weight="{weight}" '
        f'text-anchor="middle" dominant-baseline="{baseline}" '
        f'style="font-variant-emoji:text">{escape(content)}</text>'
    )


def render_natal_wheel_svg(wheel: dict[str, Any] | None) -> str:
    """SVG-строка, прозрачный фон. Пустой wheel → пустой холст 500×500."""
    data = wheel if isinstance(wheel, dict) else {}
    asc = float(data.get("ascendant_longitude") or 0)
    dsc = data.get("dsc_longitude")
    dsc_lon = float(dsc) if isinstance(dsc, (int, float)) else _normalize(asc + 180)
    mc = data.get("mc_longitude")
    mc_lon = float(mc) if isinstance(mc, (int, float)) else None
    ic = data.get("ic_longitude")
    ic_lon = float(ic) if isinstance(ic, (int, float)) else (_normalize(mc_lon + 180) if mc_lon is not None else None)
    planets = [row for row in (data.get("planets") or []) if isinstance(row, dict) and row.get("key")]
    houses = sorted(
        [row for row in (data.get("houses") or []) if isinstance(row, dict)],
        key=lambda row: int(row.get("house") or 0),
    )
    placed = _place_bodies(planets)
    by_key = {str(row.get("key")): row for row in planets}

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500" '
        'preserveAspectRatio="xMidYMid meet" role="img" aria-label="Натальная карта" '
        'style="background:transparent">',
        _circle(CX, CY, R_OUT, stroke=ACCENT, opacity=0.55, width=0.9),
        _circle(CX, CY, R_ZODIAC_IN, stroke=ACCENT, opacity=0.3, width=0.7),
        _circle(CX, CY, R_TICK_INNER, stroke="#ffffff", opacity=0.28, width=0.7),
        _circle(CX, CY, R_HOUSE_OUTER, stroke=ACCENT, opacity=0.26, width=1),
        _circle(CX, CY, R_HOUSE_INNER, stroke=ACCENT, opacity=0.2, width=1),
    ]

    for i in range(360):
        if i % 30 == 0:
            continue
        ten = i % 10 == 0
        five = i % 5 == 0
        inner = _xy(asc, i, _tick_inner_r(i))
        outer = _xy(asc, i, R_ZODIAC_IN)
        parts.append(
            _line(
                *inner,
                *outer,
                stroke="#ffffff",
                opacity=0.42 if ten else 0.28 if five else 0.14,
                width=0.55 if ten else 0.4 if five else 0.28,
            )
        )

    for i in range(12):
        lon = i * 30
        inner = _xy(asc, lon, R_ZODIAC_IN)
        outer = _xy(asc, lon, R_OUT)
        parts.append(_line(*inner, *outer, stroke=ACCENT, opacity=0.58, width=1.05))

    signs = data.get("signs")
    if not isinstance(signs, list) or len(signs) < 12:
        signs = [{"start": i * 30} for i in range(12)]
    for index, sign in enumerate(signs[:12]):
        start = float(sign.get("start") or index * 30)
        icon = _xy(asc, start + 15, (R_OUT + R_ZODIAC_IN) / 2)
        parts.append(
            _text(
                icon[0],
                icon[1],
                _sign_glyph(index),
                fill=ACCENT,
                size=14,
                family=ASTRO_FONT,
                opacity=0.88,
                baseline="central",
            )
        )

    for index, house in enumerate(houses):
        cusp = house.get("cusp")
        if cusp is None:
            continue
        next_house = houses[(index + 1) % len(houses)] if houses else None
        inner = _xy(asc, float(cusp), R_HOUSE_INNER)
        outer = _xy(asc, float(cusp), R_ZODIAC_IN)
        parts.append(_line(*inner, *outer, stroke="#ffffff", opacity=0.28, width=0.7))
        if next_house and next_house.get("cusp") is not None:
            number = _xy(asc, _house_mid(float(cusp), float(next_house["cusp"])), R_HOUSE_NUM)
            parts.append(
                _text(
                    number[0],
                    number[1],
                    str(house.get("house") or ""),
                    fill=ACCENT,
                    size=8,
                    family=TEXT_FONT,
                    opacity=0.62,
                )
            )

    for aspect in _visible_aspects(list(data.get("aspects") or [])):
        a = by_key.get(str(aspect.get("a") or ""))
        b = by_key.get(str(aspect.get("b") or ""))
        if not a or not b:
            continue
        start = _xy(asc, float(a["longitude"]), R_ASPECT)
        end = _xy(asc, float(b["longitude"]), R_ASPECT)
        hard = str(aspect.get("kind") or "") == "hard" or str(aspect.get("aspect") or "") in {
            "square",
            "opposition",
        }
        parts.append(
            _line(
                *start,
                *end,
                stroke="#c45c5c" if hard else "#7eafd6",
                opacity=0.78 if hard else 0.55,
                width=1.05 if hard else 0.8,
                dash=None if hard else "3.5 3",
            )
        )

    for planet, display_lon in placed:
        glyph = _xy(asc, display_lon, R_PLANET)
        label = _xy(asc, display_lon, R_DEGREE)
        parts.append(
            _text(
                glyph[0],
                glyph[1],
                _glyph_of(planet),
                fill="#ffffff",
                size=18,
                family=ASTRO_FONT,
                baseline="central",
            )
        )
        parts.append(
            _text(
                label[0],
                label[1],
                _dms(planet),
                fill=ACCENT,
                size=8,
                family=TEXT_FONT,
                opacity=0.88,
            )
        )

    for planet in planets:
        anchor = _xy(asc, float(planet.get("longitude") or 0), R_ZODIAC_IN)
        parts.append(
            f'<circle cx="{_round(anchor[0])}" cy="{_round(anchor[1])}" r="1.15" '
            f'fill="#ffffff" fill-opacity="0.72"/>'
        )

    angle_labels = [("ASC", asc), ("DSC", dsc_lon)]
    if mc_lon is not None:
        angle_labels.append(("MC", mc_lon))
    if ic_lon is not None:
        angle_labels.append(("IC", ic_lon))
    for key, lon in angle_labels:
        mark_inner = _xy(asc, lon, R_ANGLE_MARK_IN)
        mark_outer = _xy(asc, lon, R_ANGLE_MARK_OUT)
        label = _xy(asc, lon, R_ANGLE_LABEL)
        parts.append(_line(*mark_inner, *mark_outer, stroke=ACCENT, opacity=0.95, width=1.2))
        parts.append(
            _text(label[0], label[1], key, fill=ACCENT, size=8, family=TEXT_FONT)
        )

    parts.append("</svg>")
    return "".join(parts)
