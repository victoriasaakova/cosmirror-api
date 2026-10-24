"""Разбор входа пары. Публичные ошибки не содержат дату и координаты."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .policy import SYNASTRY_POLICY_VERSION, TAXONOMY_VERSION, WRITER_VERSION


class CompatibilityError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class PersonInput:
    person_id: str
    display_name: str
    birth_date: date
    birth_time: Optional[time]
    birth_time_status: str
    place_name: str
    latitude: float
    longitude: float
    timezone_id: str

    @property
    def angles_reliable(self) -> bool:
        return self.birth_time_status == "known"

    @property
    def moon_reliable(self) -> bool:
        return self.birth_time_status in {"known", "approximate"}

    def canonical(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "display_name": self.display_name,
            "birth_date": self.birth_date.isoformat(),
            "birth_time": self.birth_time.isoformat() if self.birth_time else None,
            "birth_time_status": self.birth_time_status,
            "place_name": self.place_name,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "timezone_id": self.timezone_id,
        }


@dataclass(frozen=True)
class ParsedRequest:
    relationship_type: str
    reference_date: date
    persons: tuple[PersonInput, PersonInput]

    @property
    def person_a(self) -> PersonInput:
        return self.persons[0]

    @property
    def person_b(self) -> PersonInput:
        return self.persons[1]


def parse_request(payload: Any, *, today: date) -> ParsedRequest:
    if not isinstance(payload, dict):
        raise CompatibilityError("Нужно передать JSON с двумя профилями.")
    relationship = payload.get("relationship_type") or "romantic"
    if relationship != "romantic":
        raise CompatibilityError("В этой версии поддерживается только romantic.")
    reference = payload.get("reference_date")
    if reference in (None, ""):
        anchor = today
    else:
        anchor = _parse_date(reference, "Дата транзита указана неверно.")
        if not _create_horizon(today, anchor):
            raise CompatibilityError("Дата вне горизонта транзитов.")
    persons_raw = payload.get("persons")
    if not isinstance(persons_raw, list) or len(persons_raw) != 2:
        raise CompatibilityError("Нужны два профиля, A и B.")
    persons = tuple(_parse_person(row) for row in persons_raw)
    ids = [person.person_id for person in persons]
    if sorted(ids) != ["A", "B"]:
        raise CompatibilityError("Нужны два профиля, A и B.")
    ordered = tuple(sorted(persons, key=lambda person: person.person_id))
    return ParsedRequest(relationship_type="romantic", reference_date=anchor, persons=ordered)


def input_hash(parsed: ParsedRequest) -> str:
    payload = {
        "persons": [person.canonical() for person in parsed.persons],
        "relationship_type": parsed.relationship_type,
        "synastry_policy_version": SYNASTRY_POLICY_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "writer_version": WRITER_VERSION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_transit_date(value: str) -> date:
    return _parse_date(value, "Дата транзита указана неверно.")


def _create_horizon(today: date, day: date) -> bool:
    from .assemble import within_horizon

    return within_horizon(today, day)


def _parse_person(row: Any) -> PersonInput:
    if not isinstance(row, dict):
        raise CompatibilityError("Нужны два профиля, A и B.")
    person_id = row.get("person_id")
    if person_id not in {"A", "B"}:
        raise CompatibilityError("Нужны два профиля, A и B.")
    status = row.get("birth_time_status")
    if status not in {"known", "approximate", "unknown"}:
        raise CompatibilityError("Статус времени рождения указан неверно.")
    birth_date = _parse_date(row.get("birth_date"), "Дата рождения указана неверно.")
    birth_time = _parse_time(row.get("birth_time"))
    if status == "unknown":
        if birth_time is not None:
            raise CompatibilityError("При неизвестном времени birth_time должен быть пустым.")
    elif birth_time is None:
        raise CompatibilityError("Для известного времени нужно передать время рождения.")
    latitude = _coordinate(row.get("latitude"), minimum=-90.0, maximum=90.0)
    longitude = _coordinate(row.get("longitude"), minimum=-180.0, maximum=180.0)
    timezone_id = row.get("timezone_id")
    if not isinstance(timezone_id, str) or not timezone_id.strip():
        raise CompatibilityError("Нужны координаты и часовой пояс.")
    timezone_id = timezone_id.strip()
    try:
        ZoneInfo(timezone_id)
    except Exception as exc:
        raise CompatibilityError("Неизвестная таймзона.") from exc
    place_name = row.get("place_name") or ""
    if not isinstance(place_name, str):
        place_name = ""
    display_name = row.get("display_name") or ""
    if not isinstance(display_name, str):
        display_name = ""
    return PersonInput(
        person_id=person_id,
        display_name=display_name.strip()[:120],
        birth_date=birth_date,
        birth_time=birth_time,
        birth_time_status=status,
        place_name=place_name.strip()[:255],
        latitude=latitude,
        longitude=longitude,
        timezone_id=timezone_id,
    )


def _parse_date(value: Any, message: str) -> date:
    if not isinstance(value, str):
        raise CompatibilityError(message)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CompatibilityError(message) from exc


def _parse_time(value: Any) -> Optional[time]:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise CompatibilityError("Время рождения указано неверно.")
    parts = value.strip().split(":")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3:
        raise CompatibilityError("Время рождения указано неверно.")
    try:
        hour, minute, second = (int(part) for part in parts)
        return time(hour, minute, second)
    except ValueError as exc:
        raise CompatibilityError("Время рождения указано неверно.") from exc


def _coordinate(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompatibilityError("Координаты места рождения не подходят.")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise CompatibilityError("Координаты места рождения не подходят.")
    return number
