"""Сборка публичного compatibility-v2 из двух уже посчитанных карт."""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from core.services.natal_common import sign_of
from core.services.report_facts import natal_aspects, transits_now

from .active_cycles_select import select_active_cycles
from .bond import build_bond
from .conclusion_select import select_conclusion
from .deep_dive_select import select_deep_dive
from .insight import build_insight_slot
from .policy import (
    ACTIVE_CYCLES_POLICY_VERSION,
    CHART_BODIES,
    CONCLUSION_POLICY_VERSION,
    DEEP_DIVE_POLICY_VERSION,
    EDITORIAL_VERSION,
    HORIZON_FUTURE_MONTHS,
    HORIZON_PAST_DAYS,
    SCHEMA_VERSION,
    SCORING_POLICY_VERSION,
    SYNASTRY_POLICY_VERSION,
)
from .scoring import score_compatibility, score_current_tension

logger = logging.getLogger(__name__)
from .signs import build_signs
from .tarot import pair_card_section
from .synastry import (
    aspect_matrix,
    chart_point_order,
    cross_aspects,
    house_overlays,
    positions_for,
)

_ANGLE_KEYS = ("asc", "mc")
_PUBLIC_ASPECT_KEYS = (
    "id",
    "person_a_point",
    "person_b_point",
    "aspect",
    "angle",
    "orb_deg",
    "allowed_orb_deg",
    "normalized_closeness",
    "direction",
    "sign_a",
    "sign_b",
    "quality",
    "source_ids",
)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def within_horizon(anchor: date, day: date) -> bool:
    if HORIZON_PAST_DAYS:
        start = anchor.fromordinal(anchor.toordinal() - HORIZON_PAST_DAYS)
    else:
        start = anchor
    end = add_months(anchor, HORIZON_FUTURE_MONTHS)
    return start <= day <= end


def transits_section(reference: date) -> dict[str, Any]:
    return {
        "status": "pending",
        "reference_date": reference.isoformat(),
        "horizon": {
            "past_days": HORIZON_PAST_DAYS,
            "future_months": HORIZON_FUTURE_MONTHS,
        },
        "person": {
            "A": {"active": [], "upcoming": []},
            "B": {"active": [], "upcoming": []},
        },
        "relationship": [],
    }


def build_public_document(
    *,
    report_id: str,
    relationship_type: str,
    reference_date: date,
    person_a: Any,
    person_b: Any,
    natal_a: dict[str, Any],
    natal_b: dict[str, Any],
    relationship_status: Optional[str] = None,
    family_role: Optional[str] = None,
    user_question: Optional[str] = None,
) -> dict[str, Any]:
    points_a, cusps_a = _points(natal_a, person_a)
    points_b, cusps_b = _points(natal_b, person_b)
    points_a = chart_point_order(points_a)
    points_b = chart_point_order(points_b)
    aspects = cross_aspects(points_a, points_b)
    warnings = _warnings(person_a, person_b)
    bond = build_bond(aspects)
    signs = build_signs(
        points_a,
        points_b,
        aspects,
        include_moon=person_a.moon_reliable and person_b.moon_reliable,
        include_asc=person_a.angles_reliable and person_b.angles_reliable,
    )
    public_aspects = [{key: row[key] for key in _PUBLIC_ASPECT_KEYS} for row in aspects]
    public_persons = [
        _public_person(person_a, "Ты"),
        _public_person(person_b, "Партнёр"),
    ]
    as_of_utc, transit_hits = _sky_hits(reference_date, natal_a, natal_b, person_a, person_b)
    scoring = score_compatibility(
        aspects,
        relationship_type=relationship_type,
        persons=public_persons,
    )
    if transit_hits is None:
        scoring["current_tension"]["reason_code"] = "TRANSIT_SNAPSHOT_FAILED"
        scoring["current_tension"]["summary"] = (
            "Напряжение на выбранную дату не посчитано: снимок транзитов не собрался. "
            "Пустое значение здесь — сбой расчёта, а не отсутствие сложностей."
        )
    else:
        scoring["current_tension"] = score_current_tension(
            [_angle_alias(hit) for hit in transit_hits["A"]],
            [_angle_alias(hit) for hit in transit_hits["B"]],
            aspects,
            reference_instant_utc=as_of_utc,
            persons=public_persons,
        )
    names = {row["id"]: row["display_name"] for row in public_persons}
    anchors = {
        "A": _natal_anchors(natal_a, "A", person_a.birth_time_status),
        "B": _natal_anchors(natal_b, "B", person_b.birth_time_status),
    }
    document = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "relationship_type": relationship_type,
        "relationship_context": {
            "type": relationship_type,
            "status": relationship_status,
            "family_role": family_role,
            "user_question": user_question,
        },
        "status": "partial",
        "persons": public_persons,
        "scoring": scoring,
        "bond": bond,
        "transits": transits_section(reference_date),
        "signs": signs,
        "chart": {
            "status": "ready",
            "biwheel": {"inner": "A", "outer": "B"},
            "positions": {"A": positions_for(points_a), "B": positions_for(points_b)},
            "cross_aspects": public_aspects,
            "natal_anchors": anchors,
            "aspect_matrix": aspect_matrix(points_a, points_b, aspects),
            "overlays": house_overlays(points_a, points_b, cusps_a, cusps_b),
            "legend": ["conjunction", "sextile", "square", "trine", "opposition"],
            "warnings": list(warnings),
        },
        "pair_card": pair_card_section(person_a, person_b),
        "natal_anchors": anchors,
        "meta": {
            "data_quality": _data_quality(person_a.birth_time_status, person_b.birth_time_status),
            "engine_version": _engine_version(natal_a),
            "synastry_policy_version": SYNASTRY_POLICY_VERSION,
            "scoring_policy_version": SCORING_POLICY_VERSION,
            "deep_dive_policy_version": DEEP_DIVE_POLICY_VERSION,
            "conclusion_policy_version": CONCLUSION_POLICY_VERSION,
            "active_cycles_policy_version": ACTIVE_CYCLES_POLICY_VERSION,
            "editorial_version": EDITORIAL_VERSION,
            "as_of_utc": as_of_utc,
            "warnings": warnings,
        },
    }
    document["insight"] = build_insight_slot(document)
    insight = document["insight"]
    if insight.get("title") and not insight.get("headline"):
        insight["headline"] = insight["title"]
    deep_dive = select_deep_dive(
        aspects,
        relationship_type=relationship_type,
        relationship_status=relationship_status,
        persons=public_persons,
        natal_anchors=anchors,
        insight_evidence_ids=list(insight.get("evidence_ids") or []),
    )
    deep_dive["conclusion"] = select_conclusion(
        relationship_type=relationship_type,
        relationship_status=relationship_status,
        sections=deep_dive["sections"],
    )
    document["deep_dive"] = deep_dive
    document["active_cycles"] = select_active_cycles(
        transit_hits or {"A": [], "B": []},
        as_of_utc=as_of_utc,
        birth_time_status={
            person_a.person_id: person_a.birth_time_status,
            person_b.person_id: person_b.birth_time_status,
        },
        names=names,
        relationship_type=relationship_type,
        relationship_status=relationship_status,
    )
    if transit_hits is None:
        document["active_cycles"]["status"] = "error"
        for person_id in ("A", "B"):
            document["active_cycles"]["persons"][person_id] = {
                "status": "error",
                "reason_code": "TRANSIT_SNAPSHOT_FAILED",
                "cycle_id": None,
                "facts": None,
                "interpretation": None,
            }
    return document


def _sky_hits(
    reference: date,
    natal_a: dict[str, Any],
    natal_b: dict[str, Any],
    person_a: Any,
    person_b: Any,
) -> tuple[str, Optional[dict[str, list[dict[str, Any]]]]]:
    as_of = datetime(reference.year, reference.month, reference.day, 12, 0, tzinfo=timezone.utc)
    stamp = as_of.isoformat().replace("+00:00", "Z")
    try:
        from core.services.natal import calculate_sky_now

        sky = calculate_sky_now(as_of)
        hits = {
            "A": _reliable_hits(transits_now(natal_a, sky), person_a.birth_time_status),
            "B": _reliable_hits(transits_now(natal_b, sky), person_b.birth_time_status),
        }
    except Exception:
        logger.warning("Compatibility transit snapshot failed")
        return stamp, None
    return stamp, hits


def _reliable_hits(hits: list[dict[str, Any]], birth_status: str) -> list[dict[str, Any]]:
    rows = []
    for hit in hits:
        natal = str(hit.get("natal") or "")
        if natal == "moon" and birth_status == "unknown":
            continue
        if natal in {"ascendant", "midheaven"} and birth_status != "known":
            continue
        rows.append(hit)
    return rows


def _angle_alias(hit: dict[str, Any]) -> dict[str, Any]:
    natal = str(hit.get("natal") or "")
    alias = {"ascendant": "asc", "midheaven": "mc"}.get(natal)
    if alias is None:
        return hit
    return {**hit, "natal": alias}


def _natal_anchors(natal: dict[str, Any], person_id: str, birth_status: str) -> list[dict[str, Any]]:
    rows = []
    for row in natal_aspects(natal):
        bodies = {_point(str(row.get("a") or "")), _point(str(row.get("b") or ""))}
        if "moon" in bodies and birth_status == "unknown":
            continue
        if bodies & {"asc", "mc"} and birth_status != "known":
            continue
        if not bodies & {"sun", "moon", "mercury", "venus", "mars", "asc", "mc"}:
            continue
        rows.append(
            {
                "id": f"natal-{person_id}-{row.get('id')}",
                "a": _point(str(row.get("a") or "")),
                "b": _point(str(row.get("b") or "")),
                "aspect": row.get("aspect"),
                "orb": row.get("orb"),
            }
        )
    return rows


def _point(body: str) -> str:
    return {"ascendant": "asc", "midheaven": "mc"}.get(body, body)


def _public_person(person: Any, default_name: str) -> dict[str, Any]:
    name = (person.display_name or "").strip() or default_name
    return {
        "id": person.person_id,
        "display_name": name,
        "birth_time_status": person.birth_time_status,
    }


def _warnings(person_a: Any, person_b: Any) -> list[str]:
    rows = []
    for person in (person_a, person_b):
        if person.birth_time_status == "unknown":
            rows.append(
                f"Время рождения {person.person_id} неизвестно: "
                f"углы и дома {person.person_id} не используются. "
                f"Аспекты Луны {person.person_id} не входят в Bond и в сравнение знаков."
            )
        elif person.birth_time_status == "approximate":
            rows.append(
                f"Время рождения {person.person_id} приблизительное: "
                f"углы и дома {person.person_id} не используются."
            )
    return rows


def _data_quality(status_a: str, status_b: str) -> str:
    if status_a == "known" and status_b == "known":
        return "full"
    if status_a == "unknown" and status_b == "unknown":
        return "limited"
    return "partial"


def _engine_version(natal: dict[str, Any]) -> str:
    calculation = natal.get("calculation") if isinstance(natal.get("calculation"), dict) else {}
    return str(calculation.get("engine_version") or "")


def _points(natal: dict[str, Any], person: Any) -> tuple[list[dict[str, Any]], Optional[list[float]]]:
    bodies = _bodies(natal)
    use_houses = person.angles_reliable
    cusps = _cusps(natal) if use_houses else None
    points: list[dict[str, Any]] = []
    for body in CHART_BODIES:
        raw = bodies.get(body)
        if not isinstance(raw, dict) or raw.get("longitude") is None:
            continue
        moon = body == "moon"
        points.append(
            _as_point(
                person.person_id,
                body,
                raw,
                bond_eligible=not moon or person.moon_reliable,
                overlay_eligible=not moon or person.moon_reliable,
                use_house=use_houses,
            )
        )
    if person.angles_reliable:
        angles = natal.get("angles") if isinstance(natal.get("angles"), dict) else {}
        for body in _ANGLE_KEYS:
            raw = angles.get(body)
            if not isinstance(raw, dict) or raw.get("longitude") is None:
                legacy_key = "ascendant" if body == "asc" else "midheaven"
                raw = natal.get(legacy_key)
            if not isinstance(raw, dict) or raw.get("longitude") is None:
                continue
            points.append(
                _as_point(
                    person.person_id,
                    body,
                    raw,
                    bond_eligible=True,
                    overlay_eligible=False,
                    use_house=False,
                )
            )
    return points, cusps


def _bodies(natal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in natal.get("bodies") or []:
        if isinstance(row, dict) and row.get("id"):
            found[str(row["id"])] = row
    planets = natal.get("planets")
    if isinstance(planets, dict):
        for key, row in planets.items():
            if key not in found and isinstance(row, dict):
                copied = dict(row)
                copied.setdefault("id", key)
                found[str(key)] = copied
    return found


def _cusps(natal: dict[str, Any]) -> Optional[list[float]]:
    houses = natal.get("houses") or []
    if not isinstance(houses, list):
        return None
    rows = [row for row in houses if isinstance(row, dict) and row.get("cusp_longitude") is not None]
    rows.sort(key=lambda row: int(row.get("house") or 0))
    if len(rows) < 12:
        return None
    return [float(row["cusp_longitude"]) % 360.0 for row in rows[:12]]


def _as_point(
    person_id: str,
    body: str,
    raw: dict[str, Any],
    *,
    bond_eligible: bool,
    overlay_eligible: bool,
    use_house: bool,
) -> dict[str, Any]:
    longitude = float(raw["longitude"])
    signed = sign_of(longitude)
    house = raw.get("house") if use_house else None
    degree = raw.get("degree")
    return {
        "person_id": person_id,
        "body": body,
        "longitude": longitude,
        "sign": raw.get("sign") or signed["sign"],
        "degree": signed["degree"] if degree is None else degree,
        "house": house,
        "bond_eligible": bond_eligible,
        "overlay_eligible": overlay_eligible,
    }
