"""Создание отчёта пары. Два вызова calculate_natal, без сессии и без NatalChart."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from django.db import IntegrityError, transaction

from core.models import CompatibilityReport
from core.services.natal import NatalCalcError, calculate_natal
from core.services.natal_common import public_natal_error

from .assemble import build_public_document, transits_section, within_horizon
from .input import CompatibilityError, ParsedRequest, input_hash, parse_request, parse_transit_date
from .writers import enrich_document, writers_settled

logger = logging.getLogger(__name__)


def create_compatibility_report(payload: Any) -> CompatibilityReport:
    today = datetime.now(timezone.utc).date()
    parsed = parse_request(payload, today=today)
    digest = input_hash(parsed)
    existing = CompatibilityReport.objects.filter(input_hash=digest).first()
    if existing is not None:
        if not writers_settled(existing.public_document):
            existing.public_document = enrich_document(existing.public_document)
            existing.save(update_fields=["public_document", "updated_at"])
        return existing

    natal_a = _natal(parsed.person_a)
    natal_b = _natal(parsed.person_b)
    report_id = uuid.uuid4()
    document = enrich_document(
        build_public_document(
            report_id=str(report_id),
            relationship_type=parsed.relationship_type,
            reference_date=parsed.reference_date,
            person_a=parsed.person_a,
            person_b=parsed.person_b,
            natal_a=natal_a,
            natal_b=natal_b,
        )
    )
    try:
        with transaction.atomic():
            return CompatibilityReport.objects.create(
                id=report_id,
                input_hash=digest,
                relationship_type=parsed.relationship_type,
                reference_date=parsed.reference_date,
                private_input=_private_input(parsed),
                private_natals={"A": natal_a, "B": natal_b},
                public_document=document,
            )
    except IntegrityError:
        return CompatibilityReport.objects.get(input_hash=digest)


def transit_view(report: CompatibilityReport, raw_date: str | None) -> dict[str, Any]:
    if raw_date in (None, ""):
        day = report.reference_date
    else:
        day = parse_transit_date(str(raw_date))
    if not within_horizon(report.reference_date, day):
        raise CompatibilityError("Дата вне горизонта транзитов.")
    return transits_section(day)


def _natal(person: Any) -> dict[str, Any]:
    try:
        return calculate_natal(
            birth_date=person.birth_date,
            birth_time=None if person.birth_time_status == "unknown" else person.birth_time,
            latitude=person.latitude,
            longitude=person.longitude,
            timezone_name=person.timezone_id,
            place=person.place_name,
        )
    except NatalCalcError as exc:
        logger.warning("Compatibility natal failed: %s", type(exc).__name__)
        if _ephemeris_failure(exc):
            raise CompatibilityError("Эфемериды сейчас недоступны.", 503) from exc
        raise CompatibilityError(public_natal_error(exc), 400) from exc


def _ephemeris_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("ephemeris", "swieph", "swiss"))


def _private_input(parsed: ParsedRequest) -> dict[str, Any]:
    return {
        "relationship_type": parsed.relationship_type,
        "reference_date": parsed.reference_date.isoformat(),
        "persons": [person.canonical() for person in parsed.persons],
    }
