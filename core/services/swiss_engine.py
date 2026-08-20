"""
Натальный расчёт на Swiss Ephemeris (pyswisseph).

Классическая карта в логике GeoCult: тропический зодиак, дома Плацидуса.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional

import swisseph as swe

from core.services.natal_common import (
    SIGNS,
    SIGNS_RU,
    NatalCalcError,
    house_of_longitude,
    houses_from_cusps,
    local_to_utc,
    sign_of,
)

ENGINE_ID = "swiss_ephemeris"

_EPHE_DIR = Path(__file__).resolve().parent / "ephemeris" / "swiss"
_EPHE_DIR.mkdir(parents=True, exist_ok=True)

# API-ключ → id тела Swiss Ephemeris
BODIES: dict[str, int] = {
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
}

_READY = False


def _ensure_ephemeris() -> None:
    global _READY
    if _READY:
        return
    swe.set_ephe_path(str(_EPHE_DIR))
    # Проверка, что файлы на месте (иначе FLG_SWIEPH упадёт / уйдёт в Moshier)
    needed = ("sepl_18.se1", "semo_18.se1", "seas_18.se1")
    missing = [name for name in needed if not (_EPHE_DIR / name).exists()]
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
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def _calc_body(jd_ut: float, body_id: int) -> dict[str, Any]:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    xx, retflag = swe.calc_ut(jd_ut, body_id, flags)
    if retflag < 0:
        raise NatalCalcError(f"Swiss Ephemeris calc failed for body {body_id}: {retflag}")
    lon = float(xx[0]) % 360.0
    speed = float(xx[3])
    block = sign_of(lon)
    block["speed"] = round(speed, 6)
    block["retrograde"] = speed < 0
    return block


def planet_longitudes(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    _ensure_ephemeris()
    jd = _jd_ut(dt_utc)
    return {key: _calc_body(jd, body_id) for key, body_id in BODIES.items()}


def _placidus_houses(jd_ut: float, lat: float, lng: float) -> tuple[float, float, list[float]]:
    """Asc, MC и 12 куспидов Плацидуса — как в классическом расчёте GeoCult."""
    cusps, ascmc = swe.houses(jd_ut, float(lat), float(lng), b"P")
    # pyswisseph отдаёт 12 куспидов (дом 1 = индекс 0); C API — 13 с пустым [0].
    start = 1 if len(cusps) >= 13 else 0
    house_cusps = [float(cusps[i]) % 360.0 for i in range(start, start + 12)]
    return float(ascmc[0]) % 360.0, float(ascmc[1]) % 360.0, house_cusps


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
    dt_utc, has_time = local_to_utc(birth_date, birth_time, timezone_name)
    planets = planet_longitudes(dt_utc)

    result: dict[str, Any] = {
        "engine": ENGINE_ID,
        "system": "tropical",
        "datetime_utc": dt_utc.isoformat().replace("+00:00", "Z"),
        "timezone": timezone_name,
        "has_birth_time": has_time,
        "location": {
            "place": place,
            "lat": round(float(latitude), 6),
            "lng": round(float(longitude), 6),
        },
        "planets": planets,
    }

    if not has_time:
        result["ascendant"] = None
        result["midheaven"] = None
        result["houses"] = None
        result["house_system"] = None
        result["notes"] = [
            "Время рождения не указано: Асцендент и дома не считаем.",
            "Солнце и планеты в знаках посчитаны на полдень местного времени.",
            "Луна без точного времени менее надёжна (за сутки проходит ~13°).",
        ]
        return result

    jd = _jd_ut(dt_utc)
    asc_deg, mc_deg, cusps = _placidus_houses(jd, float(latitude), float(longitude))
    asc = sign_of(asc_deg)
    mc = sign_of(mc_deg)
    result["ascendant"] = asc
    result["midheaven"] = mc
    result["houses"] = houses_from_cusps(cusps)
    result["house_system"] = "placidus"
    result["house_system_label"] = "Плацидус"
    for data in planets.values():
        data["house"] = house_of_longitude(float(data["longitude"]), cusps)
    result["notes"] = []
    return result


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


# re-export for callers that import signs from engine
__all__ = [
    "ENGINE_ID",
    "BODIES",
    "SIGNS",
    "SIGNS_RU",
    "calculate_natal",
    "calculate_sky_now",
    "calculate_positions",
    "planet_longitudes",
]
