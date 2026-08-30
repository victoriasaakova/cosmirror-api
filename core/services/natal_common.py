"""Общие хелперы натального расчёта (общие для Skyfield и Swiss)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
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


CHART_CALC_USER_ERROR = (
    "Не получилось посчитать карту. Перезагрузи страницу и попробуй ещё раз."
)

_TECHNICAL_NATAL_MARKERS = (
    "swiss",
    "ephemeris",
    "retflag",
    "placidus",
    "non-finite",
    "calc failed",
    "missing in",
    "download from",
    "invalid birth",
    "unexpected",
    "traceback",
)


def public_natal_error(exc: BaseException) -> str:
    """User-facing natal/geo error. Engine internals stay in logs and chart.error_message."""
    text = str(exc).strip()
    if not text:
        return CHART_CALC_USER_ERROR
    lowered = text.lower()
    if any(marker in lowered for marker in _TECHNICAL_NATAL_MARKERS):
        return CHART_CALC_USER_ERROR
    return text


def normalize_longitude(value: float) -> float:
    return float(value) % 360.0


def angular_distance(a: float, b: float) -> float:
    diff = abs((float(a) - float(b)) % 360.0)
    return min(diff, 360.0 - diff)


def format_utc_offset(delta: Optional[timedelta]) -> str:
    if delta is None:
        return "+00:00"
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


@dataclass(frozen=True)
class BirthMoment:
    local_dt: datetime
    utc_dt: datetime
    has_time: bool
    timezone_id: str
    utc_offset: str
    used_noon_fallback: bool


def resolve_birth_moment(
    birth_date: date,
    birth_time: Optional[time],
    tz_name: str,
) -> BirthMoment:
    """Местное время → UTC через IANA timezone (исторический DST)."""
    if not tz_name:
        raise NatalCalcError("Не задана таймзона")
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
    utc_dt = local_dt.astimezone(timezone.utc)
    return BirthMoment(
        local_dt=local_dt,
        utc_dt=utc_dt,
        has_time=has_time,
        timezone_id=tz_name,
        utc_offset=format_utc_offset(local_dt.utcoffset()),
        used_noon_fallback=not has_time,
    )


def local_to_utc(
    birth_date: date,
    birth_time: Optional[time],
    tz_name: str,
) -> tuple[datetime, bool]:
    """
    Местное время → UTC.
    Без времени: полдень местного — только технический якорь для планет, не для домов.
    """
    moment = resolve_birth_moment(birth_date, birth_time, tz_name)
    return moment.utc_dt, moment.has_time


def sign_of(longitude: float) -> dict[str, Any]:
    lon = normalize_longitude(longitude)
    idx = int(lon // 30) % 12
    degree_in_sign = lon % 30.0
    degree = int(degree_in_sign)
    minute = int(round((degree_in_sign - degree) * 60.0))
    if minute == 60:
        degree += 1
        minute = 0
        if degree == 30:
            degree = 0
            idx = (idx + 1) % 12
    key = SIGNS[idx]
    return {
        "sign": key,
        "sign_ru": SIGNS_RU[key],
        "sign_index": idx,
        "degree": degree,
        "minute": minute,
        "degree_in_sign": round(degree_in_sign, 4),
        "longitude": round(lon, 6),
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


def in_house_arc(longitude: float, start: float, end: float) -> bool:
    lon = longitude % 360.0
    start = start % 360.0
    end = end % 360.0
    if start <= end:
        return start <= lon < end
    return lon >= start or lon < end


def house_of_longitude(longitude: float, cusps: list[float]) -> int:
    """cusps — 12 куспидов домов Плацидуса, дом 1 = индекс 0."""
    if len(cusps) != 12:
        return 1
    for i in range(12):
        if in_house_arc(longitude, cusps[i], cusps[(i + 1) % 12]):
            return i + 1
    return 12


def nearest_cusp_distance(longitude: float, cusps: list[float]) -> float:
    if not cusps:
        return 0.0
    return min(angular_distance(longitude, cusp) for cusp in cusps)


def houses_from_cusps(cusps: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, cusp in enumerate(cusps):
        block = sign_of(cusp)
        rows.append(
            {
                "house": i + 1,
                "sign": block["sign"],
                "sign_ru": block["sign_ru"],
                "sign_index": block["sign_index"],
                "degree": block["degree"],
                "cusp_longitude": round(float(cusp) % 360.0, 4),
            }
        )
    return rows
