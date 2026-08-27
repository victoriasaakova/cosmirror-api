"""
Натальный расчёт на Swiss Ephemeris (pyswisseph).

Skill 01: тропический зодиак, Плацидус, True Node.
Единственный source of truth для натальной карты Cosmirror.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional

import swisseph as swe

from core.services.natal_common import (
    SIGNS,
    SIGNS_RU,
    NatalCalcError,
    angular_distance,
    house_of_longitude,
    houses_from_cusps,
    nearest_cusp_distance,
    normalize_longitude,
    resolve_birth_moment,
    sign_of,
)
from core.services.natal_orbs import (
    APPLYING_STEP_DAYS,
    ASPECT_ANGLES,
    HARD_ASPECTS,
    NEAR_CUSP_DEG,
    ORB_POLICY_VERSION,
    SKIP_ASPECT_PAIRS,
    allowed_orb,
)

ENGINE_ID = "swiss_ephemeris"
SCHEMA_VERSION = "natal-chart-v1"

_EPHE_DIR = Path(__file__).resolve().parent / "ephemeris" / "swiss"
_EPHE_DIR.mkdir(parents=True, exist_ok=True)
_NEEDED_FILES = ("sepl_18.se1", "semo_18.se1", "seas_18.se1")

PLANETS: dict[str, int] = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,
    "north_node": swe.TRUE_NODE,
    "chiron": swe.CHIRON,
    "vesta": swe.VESTA,
}

# Legacy public mapping: classical planets only.
BODIES: dict[str, int] = {key: PLANETS[key] for key in (
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
)}

CLASSICAL_IDS = tuple(BODIES.keys())
EXTRA_BODY_IDS = ("north_node", "south_node", "chiron", "vesta")
ASPECT_BODY_IDS = CLASSICAL_IDS + ("north_node", "chiron", "vesta", "asc", "mc")

_READY = False


def _ensure_ephemeris() -> None:
    global _READY
    if _READY:
        return
    swe.set_ephe_path(str(_EPHE_DIR))
    missing = [name for name in _NEEDED_FILES if not (_EPHE_DIR / name).exists()]
    if missing:
        raise NatalCalcError(
            "Swiss Ephemeris files missing in "
            f"{_EPHE_DIR}: {', '.join(missing)}. "
            "Download from https://www.astro.com/ftp/swisseph/ephe/"
        )
    _READY = True


def _jd_ut(dt_utc: datetime) -> float:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_utc = dt_utc.astimezone(timezone.utc)
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, swe.GREG_CAL)


def _check_finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise NatalCalcError(f"Swiss Ephemeris returned non-finite {name}")
    return value


def _calc_raw(jd_ut: float, body_id: int) -> dict[str, float]:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    xx, retflag = swe.calc_ut(jd_ut, body_id, flags)
    if retflag < 0:
        raise NatalCalcError(f"Swiss Ephemeris calc failed for body {body_id}: {retflag}")
    if not (retflag & swe.FLG_SWIEPH):
        raise NatalCalcError(f"Unexpected Swiss Ephemeris mode retflag={retflag}")
    lon = normalize_longitude(_check_finite("longitude", float(xx[0])))
    return {
        "longitude": lon,
        "latitude": _check_finite("latitude", float(xx[1])),
        "distance": _check_finite("distance", float(xx[2])),
        "speed_longitude": _check_finite("speed", float(xx[3])),
    }


def _placidus(jd_ut: float, lat: float, lng: float) -> dict[str, Any]:
    try:
        cusps, ascmc = swe.houses(jd_ut, float(lat), float(lng), b"P")
    except Exception as exc:
        raise NatalCalcError(f"Placidus houses failed: {exc}") from exc
    if len(cusps) < 12 or len(ascmc) < 4:
        raise NatalCalcError("Swiss Ephemeris returned unexpected house arrays")
    start = 1 if len(cusps) >= 13 else 0
    house_cusps = [normalize_longitude(float(cusps[i])) for i in range(start, start + 12)]
    if any(not math.isfinite(value) for value in house_cusps):
        raise NatalCalcError("Non-finite Placidus cusps")
    asc = normalize_longitude(_check_finite("asc", float(ascmc[0])))
    mc = normalize_longitude(_check_finite("mc", float(ascmc[1])))
    vertex = normalize_longitude(_check_finite("vertex", float(ascmc[3])))
    return {
        "cusps": house_cusps,
        "asc": asc,
        "mc": mc,
        "dsc": normalize_longitude(asc + 180.0),
        "ic": normalize_longitude(mc + 180.0),
        "vertex": vertex,
        "antivertex": normalize_longitude(vertex + 180.0),
    }


def _snapshot(jd_ut: float, lat: float, lng: float, has_time: bool) -> dict[str, dict[str, float]]:
    points: dict[str, dict[str, float]] = {}
    for key, body_id in PLANETS.items():
        points[key] = _calc_raw(jd_ut, body_id)
    north = points["north_node"]
    points["south_node"] = {
        "longitude": normalize_longitude(north["longitude"] + 180.0),
        "latitude": -north["latitude"],
        "distance": north["distance"],
        "speed_longitude": north["speed_longitude"],
    }
    if has_time:
        houses = _placidus(jd_ut, lat, lng)
        for key in ("asc", "dsc", "mc", "ic", "vertex", "antivertex"):
            points[key] = {
                "longitude": houses[key],
                "latitude": 0.0,
                "distance": 0.0,
                "speed_longitude": 0.0,
            }
        points["_cusps"] = {"values": houses["cusps"]}  # type: ignore[assignment]
    return points


def _decorate_point(
    key: str,
    raw: dict[str, float],
    cusps: Optional[list[float]],
) -> dict[str, Any]:
    block = sign_of(raw["longitude"])
    speed = float(raw["speed_longitude"])
    block.update(
        {
            "id": key,
            "latitude": round(float(raw["latitude"]), 6),
            "distance": round(float(raw["distance"]), 8),
            "speed_longitude": round(speed, 6),
            "speed": round(speed, 6),
            "retrograde": speed < 0,
        }
    )
    if cusps:
        house = house_of_longitude(raw["longitude"], cusps)
        distance = nearest_cusp_distance(raw["longitude"], cusps)
        block["house"] = house
        block["distance_to_nearest_cusp"] = round(distance, 4)
        block["near_cusp"] = distance <= NEAR_CUSP_DEG
    else:
        block["house"] = None
        block["distance_to_nearest_cusp"] = None
        block["near_cusp"] = False
    return block


def _aspect_error(lon_a: float, lon_b: float, exact: float) -> float:
    return abs(angular_distance(lon_a, lon_b) - exact)


def _compute_aspects(
    now: dict[str, dict[str, float]],
    later: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    ids = [key for key in ASPECT_BODY_IDS if key in now]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if frozenset({a, b}) in SKIP_ASPECT_PAIRS:
                continue
            lon_a = now[a]["longitude"]
            lon_b = now[b]["longitude"]
            separation = angular_distance(lon_a, lon_b)
            best_name = None
            best_orb = 999.0
            best_exact = 0.0
            for name, exact in ASPECT_ANGLES.items():
                orb = abs(separation - exact)
                if orb <= allowed_orb(name, a, b) and orb < best_orb:
                    best_name = name
                    best_orb = orb
                    best_exact = exact
            if not best_name:
                continue
            error_now = _aspect_error(lon_a, lon_b, best_exact)
            error_later = _aspect_error(later[a]["longitude"], later[b]["longitude"], best_exact)
            found.append(
                {
                    "body_a": a,
                    "body_b": b,
                    "aspect": best_name,
                    "exact_angle": int(best_exact) if best_exact in (0, 60, 90, 120, 180) else best_exact,
                    "separation": round(separation, 4),
                    "orb": round(best_orb, 4),
                    "applying": bool(error_later < error_now - 1e-9),
                    "kind": "hard" if best_name in HARD_ASPECTS else "soft",
                }
            )
    found.sort(key=lambda row: (float(row["orb"]), str(row["body_a"]), str(row["body_b"])))
    return found


def planet_longitudes(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    _ensure_ephemeris()
    jd = _jd_ut(dt_utc)
    snap = _snapshot(jd, 0.0, 0.0, has_time=False)
    return {key: _decorate_point(key, snap[key], None) for key in CLASSICAL_IDS}


def calculate_positions(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return planet_longitudes(dt_utc.astimezone(timezone.utc))


def calculate_natal(
    *,
    birth_date: date,
    birth_time: Optional[time],
    latitude: float,
    longitude: float,
    timezone_name: str,
    place: str = "",
) -> dict[str, Any]:
    _ensure_ephemeris()
    if not math.isfinite(float(latitude)) or not math.isfinite(float(longitude)):
        raise NatalCalcError("Invalid birth coordinates")

    moment = resolve_birth_moment(birth_date, birth_time, timezone_name)
    jd = _jd_ut(moment.utc_dt)
    has_time = moment.has_time

    now = _snapshot(jd, float(latitude), float(longitude), has_time)
    later = _snapshot(jd + APPLYING_STEP_DAYS, float(latitude), float(longitude), has_time)
    cusps: Optional[list[float]] = now.get("_cusps", {}).get("values") if has_time else None

    body_ids = list(CLASSICAL_IDS) + list(EXTRA_BODY_IDS)
    bodies = [_decorate_point(key, now[key], cusps) for key in body_ids]
    by_id = {row["id"]: row for row in bodies}

    if has_time:
        angles = {
            key: _decorate_point(key, now[key], cusps)
            for key in ("asc", "dsc", "mc", "ic", "vertex", "antivertex")
        }
    else:
        angles = {
            "asc": None,
            "dsc": None,
            "mc": None,
            "ic": None,
            "vertex": None,
            "antivertex": None,
        }

    aspects = _compute_aspects(now, later)

    warnings: list[str] = []
    if not has_time:
        warnings.extend(
            [
                "Время рождения не указано: Асцендент и дома не считаем.",
                "Солнце и планеты в знаках посчитаны на полдень местного времени.",
                "Луна без точного времени менее надёжна (за сутки проходит ~13°).",
            ]
        )

    engine_version = str(getattr(swe, "version", "") or "")
    houses_rows = houses_from_cusps(cusps) if cusps else None

    canonical: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "calculation": {
            "engine": "Swiss Ephemeris",
            "engine_version": engine_version,
            "ephemeris_mode": "SWIEPH",
            "zodiac": "tropical",
            "house_system": "Placidus" if has_time else None,
            "node_type": "true",
            "orb_policy_version": ORB_POLICY_VERSION,
        },
        "birth": {
            "local_datetime": moment.local_dt.replace(tzinfo=None).isoformat(timespec="seconds"),
            "timezone_id": moment.timezone_id,
            "utc_offset": moment.utc_offset,
            "utc_datetime": moment.utc_dt.isoformat().replace("+00:00", "Z"),
            "latitude": round(float(latitude), 6),
            "longitude": round(float(longitude), 6),
            "julian_day_ut": jd,
            "place": place,
            "birth_time_known": has_time,
        },
        "angles": angles,
        "houses": [
            {"house": row["house"], "cusp_longitude": row["cusp_longitude"]}
            for row in (houses_rows or [])
        ] if has_time else [],
        "bodies": bodies,
        "aspects": aspects,
        "validation": {
            "valid": True,
            "warnings": warnings,
        },
    }

    # Legacy aliases: онбординг, отчёт и старые тесты читают этот контур.
    planets = {key: dict(by_id[key]) for key in list(CLASSICAL_IDS) + list(EXTRA_BODY_IDS)}

    canonical.update(
        {
            "engine": ENGINE_ID,
            "system": "tropical",
            "datetime_utc": canonical["birth"]["utc_datetime"],
            "timezone": moment.timezone_id,
            "has_birth_time": has_time,
            "location": {
                "place": place,
                "lat": round(float(latitude), 6),
                "lng": round(float(longitude), 6),
            },
            "planets": planets,
            "ascendant": angles["asc"] if has_time else None,
            "descendant": angles["dsc"] if has_time else None,
            "midheaven": angles["mc"] if has_time else None,
            "ic": angles["ic"] if has_time else None,
            "vertex": angles["vertex"] if has_time else None,
            "antivertex": angles["antivertex"] if has_time else None,
            "houses": houses_rows,
            "house_system": "placidus" if has_time else None,
            "house_system_label": "Плацидус" if has_time else None,
            "notes": warnings,
        }
    )
    return canonical


def calculate_sky_now(when: Optional[datetime] = None) -> dict[str, Any]:
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    planets = planet_longitudes(moment.astimezone(timezone.utc))
    return {
        "engine": ENGINE_ID,
        "datetime_utc": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "planets": planets,
    }


__all__ = [
    "ENGINE_ID",
    "BODIES",
    "PLANETS",
    "SIGNS",
    "SIGNS_RU",
    "calculate_natal",
    "calculate_sky_now",
    "calculate_positions",
    "planet_longitudes",
]
