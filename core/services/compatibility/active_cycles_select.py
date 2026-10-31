"""Один активный цикл на человека. Орбы — черновик active-cycles-v2-draft.

Быстрые планеты не участвуют. Будущий транзит не подставляется вместо активного.
"""

from __future__ import annotations

from typing import Any, Optional

from core.services.report_accents import NATAL_POINT_WEIGHT, TRANSIT_PLANET_WEIGHT

from .policy import ACTIVE_CYCLES_POLICY_VERSION

CYCLE_TRANSITS = ("jupiter", "saturn", "uranus", "neptune", "pluto")
CYCLE_TARGETS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "ascendant", "midheaven")
CYCLE_ORB = {
    "jupiter": 3.0,
    "saturn": 3.0,
    "uranus": 2.0,
    "neptune": 2.0,
    "pluto": 2.0,
}
_SLOW = frozenset({"uranus", "neptune", "pluto"})
_ASPECT_WEIGHT = {
    "conjunction": 1.0,
    "opposition": 0.92,
    "square": 0.86,
    "trine": 0.70,
    "sextile": 0.55,
}
_PHASE_WEIGHT = {"applying": 1.08, "stationary": 1.12, "separating": 0.92}
_LONG_FIRST = {"pluto": 0, "neptune": 1, "uranus": 2, "saturn": 3, "jupiter": 4}
_TARGET_ORDER = {body: index for index, body in enumerate(CYCLE_TARGETS)}


def select_active_cycles(
    hits_by_person: dict[str, list[dict[str, Any]]],
    *,
    as_of_utc: Optional[str],
    birth_time_status: dict[str, str],
    names: dict[str, str],
    relationship_type: str,
    relationship_status: Optional[str],
) -> dict[str, Any]:
    persons = {}
    for person_id in ("A", "B"):
        persons[person_id] = _one(
            hits_by_person.get(person_id) or [],
            person_id=person_id,
            birth_status=birth_time_status.get(person_id) or "known",
            name=names.get(person_id) or person_id,
            relationship_type=relationship_type,
            relationship_status=relationship_status,
        )
    statuses = {row["status"] for row in persons.values()}
    if statuses == {"ready"}:
        overall = "ready"
    elif "ready" in statuses:
        overall = "partial"
    elif "error" in statuses:
        overall = "error"
    else:
        overall = "unavailable"
    return {
        "status": overall,
        "as_of_utc": as_of_utc,
        "calculation_engine": "swiss_ephemeris",
        "policy_version": ACTIVE_CYCLES_POLICY_VERSION,
        "persons": persons,
        "shared_note": None,
    }


def rank_hits(hits: list[dict[str, Any]], *, birth_status: str) -> list[dict[str, Any]]:
    ranked = []
    for hit in hits:
        row = _eligible(hit, birth_status)
        if row is None:
            continue
        ranked.append(row)
    ranked.sort(
        key=lambda row: (
            -row["significance_score"],
            row["orb_deg"],
            _LONG_FIRST.get(row["transit"], 9),
            _TARGET_ORDER.get(row["natal"], 99),
            row["cycle_id"],
        )
    )
    return ranked


def _one(
    hits: list[dict[str, Any]],
    *,
    person_id: str,
    birth_status: str,
    name: str,
    relationship_type: str,
    relationship_status: Optional[str],
) -> dict[str, Any]:
    ranked = rank_hits(hits, birth_status=birth_status)
    if not ranked:
        return {
            "status": "unavailable",
            "reason_code": "no_significant_active_cycle",
            "cycle_id": None,
            "facts": None,
            "interpretation": None,
        }
    winner = ranked[0]
    return {
        "status": "ready",
        "cycle_id": winner["cycle_id"],
        "facts": winner,
        "interpretation": _interpretation(
            winner,
            name,
            relationship_type,
            relationship_status,
            person_id=person_id,
        ),
        "source": "fallback",
    }


def _eligible(hit: dict[str, Any], birth_status: str) -> Optional[dict[str, Any]]:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    if transit not in CYCLE_ORB or natal not in CYCLE_TARGETS or aspect not in _ASPECT_WEIGHT:
        return None
    if natal == "moon" and birth_status == "unknown":
        return None
    if natal in {"ascendant", "midheaven"} and birth_status != "known":
        return None
    if transit in _SLOW and natal in _SLOW:
        return None
    try:
        orb = float(hit.get("orb"))
    except (TypeError, ValueError):
        return None
    allowed = CYCLE_ORB[transit]
    if orb < 0 or orb > allowed:
        return None
    proximity = max(0.0, 1.0 - orb / allowed)
    phase = str(hit.get("motion") or "separating")
    score = (
        proximity
        * TRANSIT_PLANET_WEIGHT.get(transit, 0.3)
        * NATAL_POINT_WEIGHT.get(natal, 0.45)
        * _ASPECT_WEIGHT[aspect]
        * _PHASE_WEIGHT.get(phase, 1.0)
    )
    return {
        "cycle_id": f"cycle-{transit}-{aspect}-{natal}",
        "transit": transit,
        "natal": natal,
        "aspect": aspect,
        "orb_deg": round(orb, 4),
        "allowed_orb_deg": allowed,
        "phase": phase,
        "significance_score": round(score, 6),
        "polarity": hit.get("polarity"),
    }


def _interpretation(
    facts: dict[str, Any],
    name: str,
    relationship_type: str,
    relationship_status: Optional[str],
    *,
    person_id: str,
) -> dict[str, str]:
    basis = (
        f"{_planet(facts['transit'])} в {_aspect(facts['aspect'])} "
        f"к {_planet(facts['natal'], case='dative')} — {name}."
    )
    tense = facts.get("polarity") == "pressure" or facts["aspect"] in {"square", "opposition"}
    if relationship_status in {"ended", "no_contact"}:
        lens = "Это фон периода, не объяснение завершения контакта и не повод его возобновлять."
    elif relationship_type == "family":
        lens = "В родстве это может касаться заботы, границ и самостоятельности."
    elif relationship_type == "friendship":
        lens = "В дружбе это может касаться надёжности, дел и права действовать отдельно."
    else:
        lens = "В паре это может менять темп близости, не доказывая чувств другого человека."
    who = "Тебе" if person_id == "A" else name
    headline = (
        "Сейчас привычная нагрузка может становиться заметнее."
        if tense
        else "Сейчас привычный способ действовать может получить больше пространства."
    )
    body = (
        f"{who} сейчас может быть заметен отдельный фон периода. {basis} "
        f"{lens} Персональное объяснение этого цикла ограничено по глубине."
    )
    return {
        "headline": headline,
        "teaser": basis,
        "body": body,
        "focus": "Заметнее становится тема этой натальной функции.",
        "sensitive_point": "Чувствительнее может быть место, где привычный ответ больше не срабатывает сразу." if tense else "Чувствительнее может быть желание взять больше, чем удаётся удержать.",
        "need": "Может быть нужна ясная рамка и время на проверку." if tense else "Может быть нужна опора, чтобы расширение не осталось только намерением.",
        "resource": "Ресурс периода в том, чтобы назвать ограничение или возможность до того, как решать за другого.",
        "relationship_lens": lens,
        "astrological_basis_ru": basis,
        "interpretation_depth": "limited",
    }


def _planet(body: str, case: str = "nominative") -> str:
    nominative = {
        "sun": "Солнце",
        "moon": "Луна",
        "mercury": "Меркурий",
        "venus": "Венера",
        "mars": "Марс",
        "jupiter": "Юпитер",
        "saturn": "Сатурн",
        "uranus": "Уран",
        "neptune": "Нептун",
        "pluto": "Плутон",
        "ascendant": "Асцендент",
        "midheaven": "MC",
    }
    dative = {
        "sun": "Солнцу",
        "moon": "Луне",
        "mercury": "Меркурию",
        "venus": "Венере",
        "mars": "Марсу",
        "jupiter": "Юпитеру",
        "saturn": "Сатурну",
        "uranus": "Урану",
        "neptune": "Нептуну",
        "pluto": "Плутону",
        "ascendant": "Асценденту",
        "midheaven": "MC",
    }
    table = dative if case == "dative" else nominative
    return table.get(body, body)


def _aspect(kind: str) -> str:
    return {
        "conjunction": "соединении",
        "sextile": "секстиле",
        "square": "квадрате",
        "trine": "тригоне",
        "opposition": "оппозиции",
    }.get(kind, "аспекте")
