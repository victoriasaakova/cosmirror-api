"""
Натальный расчёт — фасад.

Натальная карта и текущее небо для отчёта считаются только через Swiss Ephemeris.
Skyfield остаётся в этом модуле для демо-сравнения, не для прод-карты.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional

from skyfield.api import load
from skyfield.framelib import ecliptic_frame

from core.services.natal_common import (
    SIGNS,
    SIGNS_RU,
    NatalCalcError,
    local_to_utc,
    sign_of,
    whole_sign_houses,
)

# --- Skyfield / NASA JPL -------------------------------------------------

_EPHE_DIR = Path(__file__).resolve().parent / "ephemeris"
_EPHE_DIR.mkdir(parents=True, exist_ok=True)
_LOADER = load
_LOADER.directory = str(_EPHE_DIR)

_TS = None
_EPH = None
_EARTH = None

# Ключ API → имя тела в de421
BODIES = {
    "sun": "sun",
    "moon": "moon",
    "mercury": "mercury",
    "venus": "venus",
    "mars": "mars",
    "jupiter": "jupiter barycenter",
    "saturn": "saturn barycenter",
    "uranus": "uranus barycenter",
    "neptune": "neptune barycenter",
    "pluto": "pluto barycenter",
}

SKYFIELD_ENGINE_ID = "skyfield_de421"


def _ensure_skyfield():
    global _TS, _EPH, _EARTH
    if _EPH is not None:
        return
    _TS = _LOADER.timescale()
    _EPH = _LOADER("de421.bsp")
    _EARTH = _EPH["earth"]


@dataclass
class BirthMoment:
    dt_utc: datetime
    timezone: str
    has_birth_time: bool
    latitude: float
    longitude: float
    place: str


def _obliquity_deg(t) -> float:
    T = (t.tt - 2451545.0) / 36525.0
    return 23.439291111 - 0.0130042 * T - 1.64e-7 * T**2 + 5.04e-7 * T**3


def _ascendant_and_mc(t, lat: float, lon: float) -> tuple[float, float]:
    eps = math.radians(_obliquity_deg(t))
    phi = math.radians(lat)
    lst_hours = (t.gast + lon / 15.0) % 24.0
    ramc = math.radians(lst_hours * 15.0)

    mc = math.degrees(math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps))) % 360
    y = math.cos(ramc)
    x = -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps))
    asc = math.degrees(math.atan2(y, x)) % 360
    return asc, mc


def _planet_longitudes_skyfield(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    _ensure_skyfield()
    assert _TS is not None and _EPH is not None and _EARTH is not None

    t = _TS.from_datetime(dt_utc)
    planets: dict[str, dict[str, Any]] = {}
    for key, body_name in BODIES.items():
        astrometric = _EARTH.at(t).observe(_EPH[body_name]).apparent()
        _lat, lon_ecl, _ = astrometric.frame_latlon(ecliptic_frame)
        planets[key] = sign_of(lon_ecl.degrees)
    return planets


def _calculate_natal_skyfield(
    *,
    birth_date: date,
    birth_time: Optional[time],
    latitude: float,
    longitude: float,
    timezone_name: str,
    place: str = "",
) -> dict[str, Any]:
    dt_utc, has_time = local_to_utc(birth_date, birth_time, timezone_name)
    planets = _planet_longitudes_skyfield(dt_utc)

    result: dict[str, Any] = {
        "engine": SKYFIELD_ENGINE_ID,
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

    _ensure_skyfield()
    assert _TS is not None
    t = _TS.from_datetime(dt_utc)
    asc_deg, mc_deg = _ascendant_and_mc(t, float(latitude), float(longitude))
    asc = sign_of(asc_deg)
    mc = sign_of(mc_deg)
    result["ascendant"] = asc
    result["midheaven"] = mc
    result["houses"] = whole_sign_houses(asc["sign_index"])
    result["house_system"] = "whole_sign"
    for data in planets.values():
        data["house"] = ((data["sign_index"] - asc["sign_index"]) % 12) + 1
    result["notes"] = []
    return result


def _calculate_sky_now_skyfield(when: Optional[datetime] = None) -> dict[str, Any]:
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    planets = _planet_longitudes_skyfield(moment.astimezone(timezone.utc))
    return {
        "engine": SKYFIELD_ENGINE_ID,
        "datetime_utc": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "planets": planets,
    }


# --- facade --------------------------------------------------------------

def active_engine() -> str:
    """Натал всегда Swiss Ephemeris (Skill 01). Skyfield не участвует в карте."""
    return "swiss"


def calculate_positions(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    """Публичный хелпер: положения планет на момент UTC."""
    from core.services import swiss_engine

    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return swiss_engine.calculate_positions(dt_utc)


def calculate_natal(
    *,
    birth_date: date,
    birth_time: Optional[time],
    latitude: float,
    longitude: float,
    timezone_name: str,
    place: str = "",
) -> dict[str, Any]:
    """
    Основной расчёт натала.

    Без времени: планеты на полдень local, Asc/дома не отдаём.
    Натал всегда Swiss Ephemeris — ASTRO_ENGINE больше не переключает карту.
    """
    from core.services import swiss_engine

    return swiss_engine.calculate_natal(
        birth_date=birth_date,
        birth_time=birth_time,
        latitude=latitude,
        longitude=longitude,
        timezone_name=timezone_name,
        place=place,
    )


def calculate_sky_now(when: Optional[datetime] = None) -> dict[str, Any]:
    """Текущие положения планет (для циклов на онбординге). Всегда Swiss."""
    from core.services import swiss_engine

    return swiss_engine.calculate_sky_now(when)


# Back-compat aliases used elsewhere
ENGINE_ID = SKYFIELD_ENGINE_ID  # legacy; реальный engine смотри в chart_data["engine"]
_sign_of = sign_of
_whole_sign_houses = whole_sign_houses
