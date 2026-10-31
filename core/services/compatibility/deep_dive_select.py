"""Четыре темы глубокого разбора. Факты и механизм выбирает код, не модель.

Публичная карточка: section_title, headline, body, evidence_ids.
План сюжета остаётся в analysis и не попадает в пользовательский текст.
"""

from __future__ import annotations

from typing import Any, Optional

from .insight_select import aspect_signal
from .policy import DEEP_DIVE_POLICY_VERSION
from .story_plan import SECTION_IDS, plan_sections

_TITLES = {
    "romantic": {
        "common_ground": "Что вас сближает и притягивает",
        "differences": "Где вы различаетесь и что может задевать",
        "values_needs": "Ваши ценности и потребности",
        "mutual_expression": "Как вы проявляетесь друг с другом",
    },
    "friendship": {
        "common_ground": "Что поддерживает вашу дружбу",
        "differences": "Где возникают споры и непонимание",
        "values_needs": "Что каждый ценит в дружбе",
        "mutual_expression": "Как вы проявляете дружбу",
    },
    "family": {
        "common_ground": "Что вас объединяет и поддерживает",
        "differences": "Где расходятся привычные реакции",
        "values_needs": "Потребности, роли и границы",
        "mutual_expression": "Как вы проявляете заботу и самостоятельность",
    },
}


def select_deep_dive(
    aspects: list[dict[str, Any]],
    *,
    relationship_type: str,
    relationship_status: Optional[str],
    persons: list[dict[str, Any]],
    natal_anchors: Optional[dict[str, list[dict[str, Any]]]] = None,
    insight_evidence_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    names = _names(persons)
    rows = [row for row in (_row(aspect) for aspect in aspects) if row is not None]
    sections = plan_sections(
        rows,
        relationship_type=relationship_type,
        relationship_status=relationship_status,
        names=names,
        anchors=natal_anchors or {"A": [], "B": []},
        insight_ids=set(insight_evidence_ids or []),
        titles=_TITLES.get(relationship_type, _TITLES["romantic"]),
    )
    ready = sum(1 for section in sections if section["status"] == "ready")
    return {
        "schema_version": "compatibility-deep-dive-v2",
        "policy_version": DEEP_DIVE_POLICY_VERSION,
        "status": "ready" if ready == 4 else "partial" if ready else "limited",
        "sections": sections,
    }


def _row(aspect: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(aspect, dict) or aspect.get("direction", "A_to_B") != "A_to_B":
        return None
    if aspect.get("bond_eligible") is False:
        return None
    evidence_id = str(aspect.get("id") or "")
    point_a = str(aspect.get("person_a_point") or "")
    point_b = str(aspect.get("person_b_point") or "")
    kind = str(aspect.get("aspect") or "")
    if not evidence_id or not point_a or not point_b:
        return None
    signal = aspect_signal(aspect)
    if signal is None:
        return None
    return {
        "evidence_id": evidence_id,
        "point_a": point_a,
        "point_b": point_b,
        "aspect": kind,
        "orb_deg": aspect.get("orb_deg"),
        "signal": signal,
    }


def _names(persons: list[dict[str, Any]]) -> tuple[str, str]:
    found = {str(row.get("id")): str(row.get("display_name") or "").strip() for row in persons}
    return found.get("A") or "Ты", found.get("B") or "Партнёр"


__all__ = ["SECTION_IDS", "select_deep_dive"]
