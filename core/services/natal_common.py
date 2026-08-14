"""Общие хелперы натального расчёта (общие для Skyfield и Swiss)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

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


def sign_of(longitude: float) -> dict[str, Any]:
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


def whole_sign_houses(asc_sign_index: int) -> list[dict[str, Any]]:
    return [
        {
            "house": i + 1,
            "sign": SIGNS[(asc_sign_index + i) % 12],
            "sign_ru": SIGNS_RU[SIGNS[(asc_sign_index + i) % 12]],
            "cusp_longitude": ((asc_sign_index + i) % 12) * 30,
        }
        for i in range(12)
    ]
