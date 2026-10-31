"""Четыре индекса совместимости. Числа считает только этот модуль.

Веса — черновик compatibility-scoring-v2-draft, не вероятности событий.
relationship_type меняет только множитель гармонии. Статус пары, имена,
пол и текст вопроса на числа не влияют. Транзиты здесь не считаются.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from .insight import aspect_ru, basis_line, decline_name
from .insight_select import aspect_signal
from .policy import ANGLES, BODY_RU, NODES, PERSONAL, SCORING_POLICY_VERSION, SLOW, SOCIAL

ALPHA = 2.0
KARMIC_SCALE = 1.6
TRANSFORMATION_SCALE = 1.8

_PLANET_WEIGHT = {
    "sun": 1.30,
    "moon": 1.30,
    "mercury": 1.15,
    "venus": 1.15,
    "mars": 1.15,
    "jupiter": 0.90,
    "saturn": 1.05,
    "uranus": 0.75,
    "neptune": 0.75,
    "pluto": 0.75,
    "north_node": 1.05,
    "south_node": 1.05,
    "asc": 0.90,
    "mc": 0.60,
}

_RELATIONSHIP = {
    frozenset({"venus", "mars"}): {"romantic": 1.25, "friendship": 0.75, "family": 0.60},
    frozenset({"venus"}): {"romantic": 1.15, "friendship": 1.10, "family": 1.00},
    frozenset({"moon"}): {"romantic": 1.20, "friendship": 1.15, "family": 1.25},
    frozenset({"sun", "moon"}): {"romantic": 1.15, "friendship": 1.00, "family": 1.15},
    frozenset({"mercury"}): {"romantic": 1.00, "friendship": 1.30, "family": 1.20},
    frozenset({"mercury", "saturn"}): {"romantic": 1.00, "friendship": 1.05, "family": 1.25},
    frozenset({"moon", "saturn"}): {"romantic": 1.00, "friendship": 1.10, "family": 1.25},
    frozenset({"sun", "mars"}): {"romantic": 1.10, "friendship": 1.15, "family": 1.05},
}

_SOFT_CONJUNCTIONS = frozenset(
    {
        frozenset({"moon", "venus"}),
        frozenset({"moon", "jupiter"}),
        frozenset({"venus", "jupiter"}),
        frozenset({"mercury"}),
    }
)
_HARD_CONJUNCTIONS = frozenset(
    {
        frozenset({"moon", "saturn"}),
        frozenset({"sun", "saturn"}),
        frozenset({"mars", "saturn"}),
    }
)

_HARD = frozenset({"conjunction", "square", "opposition"})
_SOFT = frozenset({"trine", "sextile"})
_INDEX_KEYS = ("harmony", "karmic_patterns", "current_tension", "transformation")


def harmony_percent(support: float, tension: float) -> Optional[int]:
    total = support + tension
    if total == 0:
        return None
    raw = 100 * (support + ALPHA) / (total + 2 * ALPHA)
    return _clamp_percent(raw)


def motif_percent(raw: float, scale: float) -> int:
    if raw <= 0:
        return 0
    return _clamp_percent(100 * (1 - math.exp(-raw / scale)))


def score_compatibility(
    aspects: Optional[list[dict[str, Any]]],
    *,
    relationship_type: str = "romantic",
    persons: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    people = _people(persons)
    omitted = _omitted_factors(people)
    quality = _quality(people)
    tension = _pending_tension()
    if aspects is None:
        missing = _unavailable("INSUFFICIENT_INPUT", "Для этого индекса не хватает рассчитанных аспектов.")
        return _envelope(missing, missing, tension, missing, omitted)
    records = _records(aspects, people, relationship_type)
    return _envelope(
        _harmony(records, quality),
        _motif_index(records, quality, "karmic"),
        tension,
        _motif_index(records, quality, "transformation"),
        omitted,
    )


def _envelope(
    harmony: dict[str, Any],
    karmic: dict[str, Any],
    tension: dict[str, Any],
    transformation: dict[str, Any],
    omitted: list[str],
) -> dict[str, Any]:
    return {
        "scoring_policy_version": SCORING_POLICY_VERSION,
        "source": "calculated",
        "not_probability": True,
        "omitted_factors": omitted,
        "harmony": harmony,
        "karmic_patterns": karmic,
        "current_tension": tension,
        "transformation": transformation,
    }


def _records(
    aspects: list[dict[str, Any]],
    people: list[dict[str, Any]],
    relationship_type: str,
) -> list[dict[str, Any]]:
    names = _names(people)
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for row in aspects:
        record = _record(row, people, names, relationship_type, seen)
        if record is not None:
            found.append(record)
    return found


def _record(
    row: dict[str, Any],
    people: list[dict[str, Any]],
    names: tuple[str, str],
    relationship_type: str,
    seen: set[str],
) -> Optional[dict[str, Any]]:
    if not isinstance(row, dict) or row.get("direction", "A_to_B") != "A_to_B":
        return None
    if row.get("bond_eligible") is False:
        return None
    evidence_id = str(row.get("id") or "")
    if not evidence_id or evidence_id in seen:
        return None
    point_a = str(row.get("person_a_point") or "")
    point_b = str(row.get("person_b_point") or "")
    aspect = str(row.get("aspect") or "")
    if point_a not in _PLANET_WEIGHT or point_b not in _PLANET_WEIGHT:
        return None
    if _unreliable(point_a, "A", people) or _unreliable(point_b, "B", people):
        return None
    orb = _finite(row.get("orb_deg"))
    allowed = _finite(row.get("allowed_orb_deg"))
    if orb is None or allowed is None or allowed <= 0 or orb < 0 or orb > allowed:
        return None
    class_factor = _class_factor(point_a, point_b)
    if class_factor <= 0:
        return None
    polarity = _polarity(point_a, point_b, aspect)
    if polarity is None:
        return None
    closeness = max(0.0, min(1.0, 1 - orb / allowed))
    orb_weight = 0.20 + 0.80 * closeness**2
    body_pair = math.sqrt(_PLANET_WEIGHT[point_a] * _PLANET_WEIGHT[point_b])
    relationship = _relationship_factor(point_a, point_b, relationship_type)
    support, tension = polarity
    seen.add(evidence_id)
    return {
        "evidence_id": evidence_id,
        "point_a": point_a,
        "point_b": point_b,
        "aspect": aspect,
        "orb_deg": round(orb, 4),
        "orb_weight": orb_weight,
        "class_factor": class_factor,
        "body_pair_weight": body_pair,
        "relationship_factor": relationship,
        "support": support,
        "tension": tension,
        "w": orb_weight * body_pair * class_factor * relationship,
        "node_key": _node_axis_key(point_a, point_b, aspect),
        "karmic_motif": _karmic_motif(point_a, point_b, aspect),
        "transformation_motif": _transformation_motif(point_a, point_b, aspect),
        "aspect_ru": basis_line(point_a, names[0], aspect, point_b, names[1]),
    }


def _harmony(records: list[dict[str, Any]], quality: tuple[str, str]) -> dict[str, Any]:
    kept = _dedup(records, lambda row: row["w"])
    support = sum(row["w"] * row["support"] for row in kept)
    tension = sum(row["w"] * row["tension"] for row in kept)
    value = harmony_percent(support, tension)
    if value is None:
        return _unavailable("NO_ELIGIBLE_EVIDENCE", "Отдельной межкартной связки для этого индекса не нашлось.")
    status, confidence = quality
    ranked = sorted(kept, key=lambda row: (-row["w"], row["evidence_id"]))[:4]
    factors = [_factor(row, _harmony_type(row)) for row in ranked]
    summary = _harmony_summary(support, tension, ranked)
    return _ready(
        value=value,
        status=status,
        confidence=confidence,
        method="weighted_aspect_balance_v2",
        summary=summary,
        factors=factors,
    )


def _motif_index(records: list[dict[str, Any]], quality: tuple[str, str], kind: str) -> dict[str, Any]:
    motif_key = "karmic_motif" if kind == "karmic" else "transformation_motif"
    scale = KARMIC_SCALE if kind == "karmic" else TRANSFORMATION_SCALE
    method = "karmic_motif_saturation_v2" if kind == "karmic" else "transformative_motif_saturation_v2"
    contribution_type = "karmic" if kind == "karmic" else "transformative"
    candidates = [row for row in records if row[motif_key]]

    def contribution(row: dict[str, Any]) -> float:
        return row[motif_key] * row["orb_weight"] * row["class_factor"]

    kept = _dedup(candidates, contribution)
    ranked = sorted(kept, key=lambda row: (-contribution(row), row["evidence_id"]))[:4]
    value = motif_percent(sum(contribution(row) for row in ranked), scale)
    status, confidence = quality
    factors = [_factor(row, contribution_type) for row in ranked] if ranked else []
    if value == 0:
        summary = (
            "В рамках выбранных критериев мотив не выражен. "
            "Персональное объяснение пока ограничено по глубине."
            if kind == "karmic"
            else "В рамках выбранных критериев тема изменения привычного сценария не выражена. "
            "Персональное объяснение пока ограничено по глубине."
        )
        factors = []
    else:
        summary = _motif_summary(kind, ranked)
    return _ready(
        value=value,
        status=status,
        confidence=confidence,
        method=method,
        summary=summary,
        factors=factors,
    )


def _pending_tension() -> dict[str, Any]:
    return {
        "value": None,
        "unit": "index_percent",
        "status": "pending",
        "reason_code": "TRANSITS_NOT_IMPLEMENTED",
        "not_probability": True,
        "reference_instant_utc": None,
        "summary": "Период, который задаёт напряжение сейчас, ещё не посчитан.",
        "top_factors": [],
    }


def _ready(
    *,
    value: int,
    status: str,
    confidence: str,
    method: str,
    summary: str,
    factors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": "index_percent",
        "status": status,
        "confidence": confidence,
        "method": method,
        "not_probability": True,
        "summary": summary,
        "top_factors": factors,
        "interpretation_depth": "limited",
    }


def _unavailable(reason_code: str, summary: str) -> dict[str, Any]:
    return {
        "value": None,
        "unit": "index_percent",
        "status": "unavailable",
        "reason_code": reason_code,
        "not_probability": True,
        "summary": summary,
        "top_factors": [],
    }


def _factor(row: dict[str, Any], contribution_type: str) -> dict[str, Any]:
    return {
        "evidence_id": row["evidence_id"],
        "aspect_ru": row["aspect_ru"],
        "contribution_type": contribution_type,
        "orb_deg": row["orb_deg"],
    }


def _harmony_type(row: dict[str, Any]) -> str:
    if row["support"] > row["tension"]:
        return "support"
    if row["tension"] > row["support"]:
        return "tension"
    return "mixed"


def _harmony_summary(support: float, tension: float, ranked: list[dict[str, Any]]) -> str:
    if support > tension * 1.15:
        balance = "Поддерживающих связей в этих картах больше, чем напряжённых."
    elif tension > support * 1.15:
        balance = "Напряжённых связей в этих картах больше, чем поддерживающих."
    else:
        balance = "Поддерживающие и напряжённые связи в этих картах близки по весу."
    lead = ranked[0] if ranked else None
    tension_row = next((row for row in ranked if row["tension"] > row["support"]), None)
    if tension_row and lead and tension_row is not lead:
        contact = f" Один из сильных напряжённых контактов — {tension_row['aspect_ru']}."
    elif lead:
        contact = f" Один из самых сильных контактов — {lead['aspect_ru']}."
    else:
        contact = ""
    return (
        f"{balance}{contact} Это не прогноз того, сложатся ли отношения. "
        "Персональное объяснение пока ограничено по глубине."
    )


def _motif_summary(kind: str, ranked: list[dict[str, Any]]) -> str:
    contacts = _contact_list(ranked)
    if kind == "karmic":
        return (
            f"Среди заметных контактов — {contacts}. "
            "В астрологической интерпретации это символические мотивы значимости связи, "
            "а не доказательство предназначения друг другу. "
            "Персональное объяснение пока ограничено по глубине."
        )
    return (
        f"Среди заметных контактов — {contacts}. "
        "Это выраженность тем пересмотра привычных представлений, "
        "а не обещание, что кто-то обязательно изменится, и не повтор кармического мотива. "
        "Персональное объяснение пока ограничено по глубине."
    )


def _contact_list(ranked: list[dict[str, Any]]) -> str:
    lines = [str(row.get("aspect_ru") or "") for row in ranked[:2] if row.get("aspect_ru")]
    if len(lines) <= 1:
        return lines[0] if lines else "переданные факторы"
    return f"{lines[0]}; также {lines[1]}"


def _dedup(records: list[dict[str, Any]], contribution: Callable[[dict[str, Any]], float]) -> list[dict[str, Any]]:
    plain: list[dict[str, Any]] = []
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in records:
        key = row["node_key"]
        if key is None:
            plain.append(row)
            continue
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        left = contribution(row)
        right = contribution(current)
        if left > right or (left == right and row["evidence_id"] < current["evidence_id"]):
            best[key] = row
    return plain + list(best.values())


def _class_factor(point_a: str, point_b: str) -> float:
    pair = {point_a, point_b}
    has_personal = bool(pair & PERSONAL)
    if pair <= SLOW or not has_personal:
        return 0.0
    if pair & ANGLES:
        return 0.75
    if pair & NODES:
        return 0.90
    if pair <= PERSONAL:
        return 1.0
    if pair & SOCIAL:
        return 0.90
    if pair & SLOW:
        return 0.80
    return 0.0


def _relationship_factor(point_a: str, point_b: str, relationship_type: str) -> float:
    table = _RELATIONSHIP.get(frozenset((point_a, point_b)))
    if table is None:
        return 1.0
    return float(table.get(relationship_type, 1.0))


def _polarity(point_a: str, point_b: str, aspect: str) -> Optional[tuple[float, float]]:
    if aspect in _SOFT:
        return 1.0, 0.0
    if aspect in {"square", "opposition"}:
        return 0.0, 1.0
    if aspect != "conjunction":
        return None
    pair = frozenset((point_a, point_b))
    if pair in _SOFT_CONJUNCTIONS:
        return 0.80, 0.20
    if pair in _HARD_CONJUNCTIONS:
        return 0.25, 0.75
    return 0.50, 0.50


def _karmic_motif(point_a: str, point_b: str, aspect: str) -> float:
    node, other = _node_and_personal(point_a, point_b)
    if node:
        if aspect in {"conjunction", "opposition"}:
            if other in {"sun", "moon"}:
                return 1.00
            if other in {"venus", "mercury", "mars"}:
                return 0.80
        if aspect == "square" and other in PERSONAL:
            return 0.55
        return 0.0
    if "saturn" in {point_a, point_b}:
        other = point_b if point_a == "saturn" else point_a
        if other not in PERSONAL:
            return 0.0
        if aspect in _HARD:
            return 0.80 if other in {"sun", "moon"} else 0.60
        if aspect in _SOFT:
            return 0.40
    if "pluto" in {point_a, point_b}:
        other = point_b if point_a == "pluto" else point_a
        if other in PERSONAL and aspect in _HARD:
            return 0.45
    return 0.0


def _transformation_motif(point_a: str, point_b: str, aspect: str) -> float:
    if point_a in PERSONAL and point_b not in PERSONAL:
        personal, other = point_a, point_b
    elif point_b in PERSONAL and point_a not in PERSONAL:
        personal, other = point_b, point_a
    else:
        return 0.0
    hard = aspect in _HARD
    if other in NODES:
        return 0.55 if aspect in {"conjunction", "opposition"} else 0.0
    if other == "pluto" and hard:
        if personal in {"sun", "moon"}:
            return 1.00
        if personal in {"mercury", "venus", "mars"}:
            return 0.85
        return 0.0
    if other == "uranus" and hard:
        return 0.85
    if other == "saturn" and hard:
        return 0.70
    if other == "neptune" and hard:
        return 0.60
    if other in SLOW | SOCIAL and aspect in _SOFT:
        return 0.35
    return 0.0


def _node_and_personal(point_a: str, point_b: str) -> tuple[str, str]:
    if point_a in NODES and point_b in PERSONAL:
        return point_a, point_b
    if point_b in NODES and point_a in PERSONAL:
        return point_b, point_a
    return "", ""


def _node_axis_key(point_a: str, point_b: str, aspect: str) -> Optional[tuple[str, str, str]]:
    if point_a in NODES and point_b not in NODES:
        owner, partner, node = "A", point_b, point_a
    elif point_b in NODES and point_a not in NODES:
        owner, partner, node = "B", point_a, point_b
    else:
        return None
    if aspect == "square":
        activation = "square"
    elif (aspect == "conjunction" and node == "north_node") or (aspect == "opposition" and node == "south_node"):
        activation = "hard_north"
    elif (aspect == "conjunction" and node == "south_node") or (aspect == "opposition" and node == "north_node"):
        activation = "hard_south"
    else:
        activation = f"{aspect}:{node}"
    return owner, partner, activation


def _people(persons: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if persons:
        return [row for row in persons if isinstance(row, dict)]
    return [
        {"id": "A", "display_name": "Ты", "birth_time_status": "known"},
        {"id": "B", "display_name": "Партнёр", "birth_time_status": "known"},
    ]


def _names(people: list[dict[str, Any]]) -> tuple[str, str]:
    found = {str(row.get("id")): str(row.get("display_name") or "").strip() for row in people}
    return found.get("A") or "Ты", found.get("B") or "Партнёр"


def _quality(people: list[dict[str, Any]]) -> tuple[str, str]:
    statuses = [_status(people, "A"), _status(people, "B")]
    if all(status == "known" for status in statuses):
        return "ready", "high"
    if all(status == "unknown" for status in statuses):
        return "limited", "low"
    return "limited", "medium"


def _status(people: list[dict[str, Any]], person_id: str) -> str:
    for row in people:
        if str(row.get("id")) == person_id:
            status = str(row.get("birth_time_status") or "known")
            return status if status in {"known", "approximate", "unknown"} else "known"
    return "known"


def _unreliable(point: str, person_id: str, people: list[dict[str, Any]]) -> bool:
    status = _status(people, person_id)
    if point in ANGLES and status != "known":
        return True
    return point == "moon" and status == "unknown"


def _omitted_factors(people: list[dict[str, Any]]) -> list[str]:
    labels = {"moon": "Луна", "asc": "Асцендент", "mc": "MC"}
    rows: list[str] = []
    for person_id, fallback in (("A", "Ты"), ("B", "Партнёр")):
        status = _status(people, person_id)
        name = _names(people)[0 if person_id == "A" else 1] or fallback
        points = ("moon", "asc", "mc") if status == "unknown" else ("asc", "mc") if status == "approximate" else ()
        rows.extend(f"{labels[point]} — {name}" for point in points)
    return rows


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _clamp_percent(value: float) -> int:
    return max(0, min(100, int(round(value))))


def index_keys() -> tuple[str, ...]:
    return _INDEX_KEYS


_TENSION_TRANSITS = {
    "mars": 2.0,
    "jupiter": 2.0,
    "saturn": 2.0,
    "uranus": 1.5,
    "neptune": 1.5,
    "pluto": 1.5,
}
_TENSION_PLANET = {
    "mars": 0.60,
    "jupiter": 0.35,
    "saturn": 1.00,
    "uranus": 0.85,
    "neptune": 0.70,
    "pluto": 0.95,
}
_TENSION_TARGET = {"sun": 1.0, "moon": 1.0, "mercury": 0.85, "venus": 0.85, "mars": 0.85, "asc": 0.70}
_TENSION_HARD_CONJUNCTION = frozenset({"mars", "saturn", "uranus", "pluto"})
_TENSION_SCALE = 1.6


def score_current_tension(
    hits_a: list[dict[str, Any]],
    hits_b: list[dict[str, Any]],
    synastry: list[dict[str, Any]],
    *,
    reference_instant_utc: Optional[str],
    persons: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Напряжение сейчас только из переданных транзитов. Пустой расчёт — 0, не pending."""
    personal_a = _tension_signals(hits_a)
    personal_b = _tension_signals(hits_b)
    shared = _shared_tension(hits_a, hits_b, synastry)
    raw = 0.35 * _top_sum(personal_a) + 0.35 * _top_sum(personal_b) + 0.30 * _top_sum(shared)
    value = motif_percent(raw, _TENSION_SCALE)
    factors = []
    for bucket, label in ((personal_a, "A"), (personal_b, "B"), (shared, "shared")):
        for row in sorted(bucket, key=lambda item: -item["weight"])[:2]:
            factors.append(
                {
                    "evidence_id": row["evidence_id"],
                    "aspect_ru": row["aspect_ru"],
                    "contribution_type": "tension",
                    "orb_deg": row["orb_deg"],
                    "person": label,
                }
            )
    people = _people(persons)
    summary = _tension_summary(value, factors, people)
    return {
        "value": value,
        "unit": "index_percent",
        "status": "ready",
        "confidence": _quality(people)[1],
        "method": "transit_tension_v2",
        "not_probability": True,
        "reference_instant_utc": reference_instant_utc,
        "summary": summary,
        "top_factors": factors[:4] if value else [],
        "interpretation_depth": "limited",
    }


def _tension_summary(value: int, factors: list[dict[str, Any]], people: list[dict[str, Any]]) -> str:
    if value == 0:
        return _tension_zero_summary(people)
    lead = factors[0]["aspect_ru"] if factors else "рассчитанный напряжённый транзит"
    return (
        f"На выбранную дату выделяется {lead}. "
        "Это текущий транзитный фон, а не признак скорой ссоры и не постоянный рисунок карт. "
        "Персональное объяснение пока ограничено по глубине."
    )


def _tension_zero_summary(people: list[dict[str, Any]]) -> str:
    base = (
        "На выбранную дату среди надёжно рассчитанных точек не найдено сильных напряжённых транзитов "
        "по установленным критериям."
    )
    names = _names(people)
    unknown = []
    approximate = False
    for person_id, index in (("A", 0), ("B", 1)):
        status = _status(people, person_id)
        if status == "unknown":
            name = names[index]
            unknown.append(decline_name(name).get("genitive") or name)
        elif status == "approximate":
            approximate = True
    if unknown:
        who = " и ".join(unknown)
        return (
            f"{base} Время рождения {who} неизвестно, поэтому оценка ограничена "
            "и не означает отсутствия сложностей в отношениях."
        )
    if approximate:
        return (
            f"{base} Время рождения приблизительное, поэтому углы в оценку не входят. "
            "Это не означает отсутствия сложностей в отношениях."
        )
    return f"{base} Это не означает отсутствия сложностей в отношениях."


def _transit_phrase(transit: str, aspect: str, natal: str) -> str:
    phrase = aspect_ru(transit, aspect, natal) or BODY_RU.get(transit, transit)
    planet = BODY_RU.get(transit, transit)
    if phrase.startswith(planet):
        return f"Транзитный {planet}{phrase[len(planet):]}"
    return f"Транзитный {phrase}"


def _tension_signals(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for hit in hits:
        transit = str(hit.get("transit") or "")
        natal = str(hit.get("natal") or "")
        aspect = str(hit.get("aspect") or "")
        if transit not in _TENSION_TRANSITS or natal not in _TENSION_TARGET:
            continue
        if aspect not in {"square", "opposition", "conjunction"}:
            continue
        if aspect == "conjunction" and transit not in _TENSION_HARD_CONJUNCTION:
            continue
        try:
            orb = float(hit.get("orb"))
        except (TypeError, ValueError):
            continue
        allowed = _TENSION_TRANSITS[transit]
        if orb < 0 or orb > allowed:
            continue
        closeness = max(0.0, min(1.0, 1 - orb / allowed))
        weight = _TENSION_PLANET[transit] * _TENSION_TARGET[natal] * (0.20 + 0.80 * closeness**2)
        found.append(
            {
                "evidence_id": f"transit-{transit}-{aspect}-{natal}",
                "aspect_ru": _transit_phrase(transit, aspect, natal),
                "orb_deg": round(orb, 4),
                "weight": weight,
                "natal": natal,
            }
        )
    return found


def _shared_tension(
    hits_a: list[dict[str, Any]],
    hits_b: list[dict[str, Any]],
    synastry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    leading = []
    for row in synastry:
        if not isinstance(row, dict) or row.get("direction", "A_to_B") != "A_to_B":
            continue
        signal = aspect_signal(row)
        if signal is None:
            continue
        leading.append((signal, row))
    leading.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    activated = []
    for _signal, row in leading[:5]:
        ends = {str(row.get("person_a_point") or ""), str(row.get("person_b_point") or "")}
        best = 0.0
        evidence = str(row.get("id") or "")
        for hit in list(hits_a) + list(hits_b):
            if str(hit.get("natal") or "") not in ends:
                continue
            signals = _tension_signals([hit])
            if signals:
                best = max(best, signals[0]["weight"])
        if best > 0 and evidence:
            phrase = aspect_ru(
                str(row.get("person_a_point") or ""),
                str(row.get("aspect") or ""),
                str(row.get("person_b_point") or ""),
            )
            activated.append(
                {
                    "evidence_id": evidence,
                    "aspect_ru": phrase or evidence,
                    "orb_deg": row.get("orb_deg"),
                    "weight": best,
                    "natal": "",
                }
            )
    return activated


def _top_sum(rows: list[dict[str, Any]]) -> float:
    ordered = sorted(rows, key=lambda row: -row["weight"])[:2]
    return sum(row["weight"] for row in ordered)
