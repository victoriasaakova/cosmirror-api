"""
Натальный расчёт на Skyfield (MIT) + NASA JPL.

Движок сменный: позже можно добавить SwissEphemerisEngine
с тем же контрактом chart_data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from skyfield.api import load
from skyfield.framelib import ecliptic_frame

# Эфемериды рядом с сервисом (скачиваются один раз)
_EPHE_DIR = Path(__file__).resolve().parent / "ephemeris"
_EPHE_DIR.mkdir(parents=True, exist_ok=True)
_LOADER = load
_LOADER.directory = str(_EPHE_DIR)

_TS = None
_EPH = None
_EARTH = None

SIGNS = [
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

SIGNS_RU = {
    "aries": "Овен",
    "taurus": "Телец",
    "gemini": "Близнецы",
    "cancer": "Рак",
    "leo": "Лев",
    "virgo": "Дева",
    "libra": "Весы",
    "scorpio": "Скорпион",
    "sagittarius": "Стрелец",
    "capricorn": "Козерог",
    "aquarius": "Водолей",
    "pisces": "Рыбы",
}

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

ENGINE_ID = "skyfield_de421"


def _ensure_ephemeris():
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


class NatalCalcError(Exception):
    pass


def local_to_utc(
    birth_date: date,
    birth_time: Optional[time],
    tz_name: str,
) -> tuple[datetime, bool]:
    """
    Местное время → UTC.
    Без времени: полдень местного — стандарт для космограммы без Asc.
    """
    has_time = birth_time is not None
    local_t = birth_time if has_time else time(12, 0)
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:
        raise NatalCalcError(f"Неизвестная таймзона: {tz_name}") from exc

    local_dt = datetime(
        birth_date.year,
        birth_date.month,
        birth_date.day,
        local_t.hour,
        local_t.minute,
        local_t.second or 0,
        tzinfo=tz,
    )
    return local_dt.astimezone(timezone.utc), has_time


def _obliquity_deg(t) -> float:
    T = (t.tt - 2451545.0) / 36525.0
    return 23.439291111 - 0.0130042 * T - 1.64e-7 * T**2 + 5.04e-7 * T**3


def _sign_of(longitude: float) -> dict[str, Any]:
    lon = longitude % 360.0
    idx = int(lon // 30) % 12
    key = SIGNS[idx]
    return {
        "sign": key,
        "sign_ru": SIGNS_RU[key],
        "sign_index": idx,
        "degree": round(lon % 30, 2),
        "longitude": round(lon, 4),
    }


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


def _whole_sign_houses(asc_sign_index: int) -> list[dict[str, Any]]:
    return [
        {
            "house": i + 1,
            "sign": SIGNS[(asc_sign_index + i) % 12],
            "sign_ru": SIGNS_RU[SIGNS[(asc_sign_index + i) % 12]],
            "cusp_longitude": ((asc_sign_index + i) % 12) * 30,
        }
        for i in range(12)
    ]


def _planet_longitudes(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    _ensure_ephemeris()
    assert _TS is not None and _EPH is not None and _EARTH is not None

    t = _TS.from_datetime(dt_utc)
    # Геоцентрически — стандарт натальной карты
    planets: dict[str, dict[str, Any]] = {}
    for key, body_name in BODIES.items():
        astrometric = _EARTH.at(t).observe(_EPH[body_name]).apparent()
        _lat, lon_ecl, _ = astrometric.frame_latlon(ecliptic_frame)
        planets[key] = _sign_of(lon_ecl.degrees)
    return planets


def calculate_positions(dt_utc: datetime) -> dict[str, dict[str, Any]]:
    """Публичный хелпер: положения планет на момент UTC."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return _planet_longitudes(dt_utc.astimezone(timezone.utc))


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
    Основной расчёт натала для онбординга.

    Без времени: планеты точны для знаков (полдень local), Asc/дома не отдаём.
    """
    dt_utc, has_time = local_to_utc(birth_date, birth_time, timezone_name)
    planets = _planet_longitudes(dt_utc)

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

    _ensure_ephemeris()
    assert _TS is not None
    t = _TS.from_datetime(dt_utc)
    asc_deg, mc_deg = _ascendant_and_mc(t, float(latitude), float(longitude))
    asc = _sign_of(asc_deg)
    mc = _sign_of(mc_deg)
    result["ascendant"] = asc
    result["midheaven"] = mc
    result["houses"] = _whole_sign_houses(asc["sign_index"])
    result["house_system"] = "whole_sign"
    for data in planets.values():
        data["house"] = ((data["sign_index"] - asc["sign_index"]) % 12) + 1
    result["notes"] = []
    return result


def calculate_sky_now(when: Optional[datetime] = None) -> dict[str, Any]:
    """Текущие положения планет (для циклов на онбординге)."""
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    planets = _planet_longitudes(moment.astimezone(timezone.utc))
    return {
        "engine": ENGINE_ID,
        "datetime_utc": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "planets": planets,
    }
