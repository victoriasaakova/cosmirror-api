"""
Фактический слой отчёта.

Не считает эфемериды заново: берёт долготы из уже готового natal / sky_now
(Swiss Ephemeris или Skyfield — как посчитала карта).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import copysign
from typing import Any, Optional

from core.services.natal_common import SIGNS, SIGNS_RU
from core.services.report_lexicon import (
    ASPECT_THEME,
    HOUSE_THEME,
    PLANET_THEME,
    SIGN_THEME,
    aspect_sentence,
    cycle_copy,
    natal_aspect_sentence,
    placement_sentence,
)
from core.services.report_types import (
    ANGLE_ORDER,
    ASPECTS,
    ENGINE_ANGLE_IDS,
    NATAL_ORB,
    PLANET_GLYPH,
    PLANET_ORDER,
    PLANET_RU,
    POLARITY_MIXED,
    POLARITY_PRESSURE,
    POLARITY_RESOURCE,
    POLARITY_RU,
    TRANSIT_ORB,
    TRANSIT_PLANET_WEIGHT,
    WHEEL_ASPECT_BODIES,
    WHEEL_ASPECT_KINDS,
    WHEEL_ASPECT_MAX_ORB,
    WHEEL_ASPECT_OUTER,
    WHEEL_BODY_ORDER,
)


def longitude_of(block: Any) -> Optional[float]:
    if not isinstance(block, dict):
        return None
    if block.get("longitude") is not None:
        return float(block["longitude"]) % 360.0
    sign_index = block.get("sign_index")
    degree = block.get("degree")
    if sign_index is None or degree is None:
        return None
    return (int(sign_index) * 30 + float(degree)) % 360.0


def angle_sep(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _best_aspect(sep: float, max_orb: float) -> Optional[dict[str, Any]]:
    best: Optional[dict[str, Any]] = None
    best_orb = 999.0
    for aspect in ASPECTS:
        orb = abs(sep - float(aspect["angle"]))
        if orb <= max_orb and orb < best_orb:
            best_orb = orb
            best = {**aspect, "orb": round(orb, 2)}
    return best


def _polarity(transit: str, aspect_kind: str) -> str:
    if transit == "jupiter" and aspect_kind == "hard":
        return POLARITY_MIXED
    if transit == "saturn" and aspect_kind == "soft":
        return POLARITY_MIXED
    if aspect_kind == "soft":
        return POLARITY_RESOURCE
    return POLARITY_PRESSURE


def _motion(transit_lon: float, speed: float, natal_lon: float, aspect_angle: float) -> str:
    if abs(speed) < 0.008:
        return "stationary"
    current = abs(angle_sep(transit_lon, natal_lon) - aspect_angle)
    future_lon = (transit_lon + copysign(0.02, speed)) % 360.0
    future = abs(angle_sep(future_lon, natal_lon) - aspect_angle)
    return "applying" if future < current else "separating"


def _days_to_exact(orb: float, speed: float, motion: str) -> Optional[int]:
    if motion != "applying" or abs(speed) < 0.004:
        return None
    return max(0, int(round(orb / abs(speed))))


def natal_points(natal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Планеты + углы как единый набор точек для аспектов."""
    points: dict[str, dict[str, Any]] = {}
    planets = natal.get("planets") if isinstance(natal.get("planets"), dict) else {}
    for key in PLANET_ORDER:
        block = planets.get(key)
        lon = longitude_of(block)
        if not isinstance(block, dict) or lon is None:
            continue
        points[key] = {**block, "key": key, "longitude": lon, "kind": "planet"}
    for key in ANGLE_ORDER:
        block = natal.get(key)
        lon = longitude_of(block)
        if not isinstance(block, dict) or lon is None:
            continue
        points[key] = {**block, "key": key, "longitude": lon, "kind": "angle", "speed": 0.0}
    return points


def natal_table(natal: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, block in natal_points(natal).items():
        house = block.get("house")
        sign = str(block.get("sign") or "")
        sign_ru = str(block.get("sign_ru") or SIGNS_RU.get(sign, ""))
        rows.append(
            {
                "key": key,
                "name": PLANET_RU.get(key, key),
                "sign": sign,
                "sign_ru": sign_ru,
                "degree": block.get("degree"),
                "minute": block.get("minute"),
                "longitude": block.get("longitude"),
                "house": house,
                "house_theme": HOUSE_THEME.get(int(house), "") if house else "",
                "retrograde": bool(block.get("retrograde")),
                "theme": PLANET_THEME.get(key, ""),
                "sign_theme": SIGN_THEME.get(sign, ""),
                "fact": placement_sentence(
                    key, sign_ru, int(house) if house else None, sign=sign
                ),
                "glyph": PLANET_GLYPH.get(key, ""),
            }
        )
    return rows


def _report_point_id(raw: str) -> str:
    return ENGINE_ANGLE_IDS.get(raw, raw)


def _is_pattern_wheel_aspect(a: str, b: str, aspect: str, orb: float) -> bool:
    """Какие линии рисуем на колесе — как в The Pattern, не все рассчитанные аспекты."""
    if a not in WHEEL_ASPECT_BODIES or b not in WHEEL_ASPECT_BODIES:
        return False
    if aspect not in WHEEL_ASPECT_KINDS:
        return False
    if a in WHEEL_ASPECT_OUTER and b in WHEEL_ASPECT_OUTER:
        return False
    return float(orb) <= float(WHEEL_ASPECT_MAX_ORB.get(aspect, 0.0))


def natal_aspects(natal: dict[str, Any]) -> list[dict[str, Any]]:
    engine_rows = natal.get("aspects") if isinstance(natal.get("aspects"), list) else []
    if engine_rows and isinstance(engine_rows[0], dict) and engine_rows[0].get("body_a"):
        found: list[dict[str, Any]] = []
        for row in engine_rows:
            a = _report_point_id(str(row.get("body_a") or ""))
            b = _report_point_id(str(row.get("body_b") or ""))
            aspect = str(row.get("aspect") or "")
            meta = next((item for item in ASPECTS if item["key"] == aspect), None)
            if not a or not b or not meta:
                continue
            if a not in PLANET_ORDER and a not in ANGLE_ORDER:
                continue
            if b not in PLANET_ORDER and b not in ANGLE_ORDER:
                continue
            found.append(
                {
                    "id": f"natal_{a}_{aspect}_{b}",
                    "a": a,
                    "b": b,
                    "a_name": PLANET_RU.get(a, a),
                    "b_name": PLANET_RU.get(b, b),
                    "aspect": aspect,
                    "aspect_ru": meta["ru"],
                    "kind": meta["kind"],
                    "orb": round(float(row.get("orb") or 0), 2),
                    "applying": bool(row.get("applying")),
                    "theme": ASPECT_THEME[aspect],
                    "fact": natal_aspect_sentence(a, aspect, meta["ru"], b),
                    "scope": "natal",
                }
            )
        found.sort(key=lambda row: (float(row["orb"]), str(row["id"])))
        return found

    points = natal_points(natal)
    keys = list(points.keys())
    found = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            lon_a = float(points[a]["longitude"])
            lon_b = float(points[b]["longitude"])
            max_orb = max(NATAL_ORB.get(a, 6.0), NATAL_ORB.get(b, 6.0))
            hit = _best_aspect(angle_sep(lon_a, lon_b), max_orb)
            if not hit:
                continue
            found.append(
                {
                    "id": f"natal_{a}_{hit['key']}_{b}",
                    "a": a,
                    "b": b,
                    "a_name": PLANET_RU.get(a, a),
                    "b_name": PLANET_RU.get(b, b),
                    "aspect": hit["key"],
                    "aspect_ru": hit["ru"],
                    "kind": hit["kind"],
                    "orb": hit["orb"],
                    "theme": ASPECT_THEME[hit["key"]],
                    "fact": natal_aspect_sentence(a, hit["key"], hit["ru"], b),
                    "scope": "natal",
                }
            )
    found.sort(key=lambda row: (float(row["orb"]), str(row["id"])))
    return found


def _sky_points(sky: dict[str, Any]) -> dict[str, dict[str, Any]]:
    planets = sky.get("planets") if isinstance(sky.get("planets"), dict) else {}
    points: dict[str, dict[str, Any]] = {}
    for key in PLANET_ORDER:
        block = planets.get(key)
        lon = longitude_of(block)
        if not isinstance(block, dict) or lon is None:
            continue
        points[key] = {**block, "key": key, "longitude": lon}
    return points


def transits_now(natal: dict[str, Any], sky: dict[str, Any]) -> list[dict[str, Any]]:
    natal_pts = natal_points(natal)
    sky_pts = _sky_points(sky)
    hits: list[dict[str, Any]] = []
    for t_key, t_block in sky_pts.items():
        max_orb = TRANSIT_ORB.get(t_key, 4.0)
        t_lon = float(t_block["longitude"])
        speed = float(t_block.get("speed") or 0.0)
        for n_key, n_block in natal_pts.items():
            n_lon = float(n_block["longitude"])
            hit = _best_aspect(angle_sep(t_lon, n_lon), max_orb)
            if not hit:
                continue
            polarity = _polarity(t_key, str(hit["kind"]))
            motion = _motion(t_lon, speed, n_lon, float(hit["angle"]))
            days = _days_to_exact(float(hit["orb"]), speed, motion)
            natal_house = n_block.get("house")
            hits.append(
                {
                    "id": f"t_{t_key}_{hit['key']}_{n_key}",
                    "transit": t_key,
                    "transit_name": PLANET_RU.get(t_key, t_key),
                    "natal": n_key,
                    "natal_name": PLANET_RU.get(n_key, n_key),
                    "aspect": hit["key"],
                    "aspect_ru": hit["ru"],
                    "kind": hit["kind"],
                    "polarity": polarity,
                    "polarity_ru": POLARITY_RU[polarity],
                    "orb": hit["orb"],
                    "motion": motion,
                    "speed": round(speed, 6),
                    "days_to_exact": days,
                    "natal_sign": n_block.get("sign"),
                    "natal_sign_ru": n_block.get("sign_ru"),
                    "natal_house": natal_house,
                    "transit_sign": t_block.get("sign"),
                    "transit_sign_ru": t_block.get("sign_ru"),
                    "transit_degree": t_block.get("degree"),
                    "scope": "personal",
                    "weight_hint": TRANSIT_PLANET_WEIGHT.get(t_key, 0.3),
                    "fact": aspect_sentence(t_key, str(hit["ru"]), n_key, str(hit["key"])),
                    **cycle_copy(t_key, polarity),
                }
            )
    hits.sort(key=lambda row: (row["orb"], -float(row["weight_hint"])))
    return hits


def collective_sky(sky: dict[str, Any]) -> list[dict[str, Any]]:
    """Общий фон: где стоят внешние планеты сейчас. Не персональный транзит."""
    points = _sky_points(sky)
    rows: list[dict[str, Any]] = []
    for key in ("saturn", "uranus", "neptune", "pluto"):
        block = points.get(key)
        if not block:
            continue
        sign = str(block.get("sign") or "")
        rows.append(
            {
                "id": f"sky_{key}",
                "planet": key,
                "name": PLANET_RU.get(key, key),
                "sign": sign,
                "sign_ru": block.get("sign_ru") or SIGNS_RU.get(sign, ""),
                "degree": block.get("degree"),
                "retrograde": bool(block.get("retrograde")),
                "scope": "collective",
                "theme": PLANET_THEME.get(key, ""),
                "sign_theme": SIGN_THEME.get(sign, ""),
            }
        )
    return rows


def houses_table(natal: dict[str, Any]) -> list[dict[str, Any]]:
    houses = natal.get("houses")
    if not isinstance(houses, list):
        return []
    occupants: dict[int, list[str]] = {}
    for row in natal_table(natal):
        house = row.get("house")
        if house:
            occupants.setdefault(int(house), []).append(str(row["name"]))
    out: list[dict[str, Any]] = []
    for row in houses:
        if not isinstance(row, dict):
            continue
        number = int(row.get("house") or 0)
        if number < 1:
            continue
        sign = str(row.get("sign") or "")
        out.append(
            {
                "house": number,
                "sign": sign,
                "sign_ru": row.get("sign_ru") or SIGNS_RU.get(sign, ""),
                "theme": HOUSE_THEME.get(number, ""),
                "occupants": occupants.get(number) or [],
                "cusp_longitude": row.get("cusp_longitude"),
            }
        )
    return out


def chart_wheel(natal: dict[str, Any], aspects: list[dict[str, Any]]) -> dict[str, Any]:
    """Данные для SVG-колеса: ASC слева, долготы из Swiss Ephemeris без интерпретации."""
    stored = natal.get("planets") if isinstance(natal.get("planets"), dict) else {}
    points = natal_points(natal)
    asc = natal.get("ascendant") or (natal.get("angles") or {}).get("asc") or points.get("ascendant")
    mc = natal.get("midheaven") or (natal.get("angles") or {}).get("mc") or points.get("midheaven")
    dsc = natal.get("descendant") or (natal.get("angles") or {}).get("dsc")
    ic = natal.get("ic") or (natal.get("angles") or {}).get("ic")
    asc_lon = float(longitude_of(asc) or 0.0)

    planets = []
    for key in WHEEL_BODY_ORDER:
        block = stored.get(key) or points.get(key)
        lon = longitude_of(block) if isinstance(block, dict) else None
        if lon is None:
            continue
        planets.append(
            {
                "key": key,
                "name": PLANET_RU.get(key, key),
                "glyph": PLANET_GLYPH.get(key, ""),
                "longitude": lon,
                "sign": block.get("sign"),
                "sign_ru": block.get("sign_ru"),
                "degree": block.get("degree"),
                "minute": block.get("minute"),
                "house": block.get("house"),
                "retrograde": bool(block.get("retrograde")),
            }
        )
    houses = []
    for row in natal.get("houses") or []:
        if not isinstance(row, dict):
            continue
        houses.append(
            {
                "house": int(row.get("house") or 0),
                "cusp": float(row.get("cusp_longitude") or 0),
                "sign_ru": row.get("sign_ru") or "",
            }
        )
    engine_aspects = natal.get("aspects") if isinstance(natal.get("aspects"), list) else []
    if engine_aspects and isinstance(engine_aspects[0], dict) and engine_aspects[0].get("body_a"):
        raw_lines = []
        for row in engine_aspects:
            a = _report_point_id(str(row.get("body_a") or ""))
            b = _report_point_id(str(row.get("body_b") or ""))
            aspect = str(row.get("aspect") or "")
            orb = float(row.get("orb") or 0)
            meta = next((item for item in ASPECTS if item["key"] == aspect), None)
            if not meta or not _is_pattern_wheel_aspect(a, b, aspect, orb):
                continue
            raw_lines.append({"a": a, "b": b, "kind": meta["kind"], "aspect": aspect, "orb": round(orb, 2)})
        lines = raw_lines
    else:
        lines = [
            {
                "a": row["a"],
                "b": row["b"],
                "kind": row["kind"],
                "aspect": row["aspect"],
                "orb": row.get("orb"),
            }
            for row in aspects
            if _is_pattern_wheel_aspect(
                str(row.get("a") or ""),
                str(row.get("b") or ""),
                str(row.get("aspect") or ""),
                float(row.get("orb") or 0),
            )
        ]
    return {
        "ascendant_longitude": asc_lon,
        "mc_longitude": float(longitude_of(mc)) if isinstance(mc, dict) and longitude_of(mc) is not None else None,
        "dsc_longitude": float(longitude_of(dsc)) if isinstance(dsc, dict) and longitude_of(dsc) is not None else None,
        "ic_longitude": float(longitude_of(ic)) if isinstance(ic, dict) and longitude_of(ic) is not None else None,
        "has_birth_time": bool(natal.get("has_birth_time")),
        "house_system": natal.get("house_system") or "placidus",
        "planets": planets,
        "houses": houses,
        "aspects": lines,
        "signs": [
            {"sign": SIGNS[i], "sign_ru": SIGNS_RU[SIGNS[i]], "start": i * 30}
            for i in range(12)
        ],
    }


def method_block(natal: dict[str, Any], sky: dict[str, Any]) -> dict[str, Any]:
    engine = str(natal.get("engine") or "")
    engine_label = "Swiss Ephemeris · Плацидус"
    when = str(sky.get("datetime_utc") or "")
    has_time = bool(natal.get("has_birth_time"))
    notes = [str(n) for n in (natal.get("notes") or []) if n]
    if not has_time:
        notes.append("Без точного времени Асцендент, дома и транзиты к углам не считаем.")
    return {
        "engine": engine,
        "engine_label": engine_label,
        "system": natal.get("system") or "tropical",
        "house_system": natal.get("house_system") or ("placidus" if has_time else None),
        "has_birth_time": has_time,
        "sky_datetime_utc": when,
        "what_calculated": [
            "тропическая натальная карта, система домов Плацидус — как в классическом расчёте GeoCult",
            "положения планет в знаках и домах",
            "натальные аспекты и текущие транзиты к натальным точкам",
        ],
        "what_it_means": (
            "Карта показывает темы и склонности, циклы — какой фон сейчас громче. "
            "Это не список будущих событий."
        ),
        "notes": notes,
    }


def estimate_window(hit: dict[str, Any], sky_iso: str) -> dict[str, Any]:
    """Грубая оценка окна по орбу и скорости. Не сканирует эфемериды вперёд."""
    days = hit.get("days_to_exact")
    peak = None
    if days is not None and sky_iso:
        try:
            base = datetime.fromisoformat(sky_iso.replace("Z", "+00:00"))
            peak = (base + timedelta(days=int(days))).date().isoformat()
        except ValueError:
            peak = None
    span = {
        "uranus": "обычно волнами 12–18 месяцев на точный контакт",
        "neptune": "длинный, размытый фон: месяцы и годы",
        "pluto": "глубокий и медленный: месяцы и годы",
        "saturn": "примерно 8–12 месяцев вокруг точного аспекта",
        "jupiter": "короче: недели или 2–3 месяца",
        "mars": "дни или несколько недель",
    }.get(str(hit.get("transit") or ""), "зависит от скорости планеты")
    return {
        "span_note": span,
        "peak_estimate": peak,
        "motion": hit.get("motion"),
        "confidence": "low" if days is None else "medium",
        "source": "orb_and_speed",
    }
