"""Маршрут заключения по статусу связи. Текст не обещает развитие завершённого контакта."""

from __future__ import annotations

from typing import Any, Optional

from .policy import CONCLUSION_POLICY_VERSION

_VARIANT = {
    ("romantic", "crush"): "growth",
    ("romantic", "dating"): "growth",
    ("romantic", "together"): "growth",
    ("romantic", "uncertain"): "uncertainty",
    ("romantic", "ended"): "reflection",
    ("friendship", "new"): "growth",
    ("friendship", "close"): "growth",
    ("friendship", "distant"): "uncertainty",
    ("friendship", "ended"): "reflection",
    ("family", "active"): "growth",
    ("family", "strained"): "uncertainty",
    ("family", "distant"): "uncertainty",
    ("family", "no_contact"): "reflection",
}


def variant_for(relationship_type: str, relationship_status: Optional[str]) -> Optional[str]:
    if relationship_status is None:
        return None
    return _VARIANT.get((relationship_type, relationship_status))


def select_conclusion(
    *,
    relationship_type: str,
    relationship_status: Optional[str],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    variant = variant_for(relationship_type, relationship_status)
    evidence = [
        section.get("primary_evidence_id")
        for section in sections
        if section.get("status") == "ready" and section.get("primary_evidence_id")
    ]
    if variant is None:
        return _empty("STATUS_UNSPECIFIED", "Фаза связи не указана, поэтому итог не привязан к развитию или завершению.")
    if not evidence:
        return _empty("NO_ELIGIBLE_EVIDENCE", "Для итога не хватает отдельных тем глубокого разбора.")
    text = _copy(variant, relationship_type, relationship_status)
    return {
        "status": "ready",
        "variant": variant,
        "headline": text["headline"],
        "body": text["summary"],
        "summary": text["summary"],
        "potential_or_meaning": None,
        "conditions_or_limits": None,
        "evidence_ids": evidence[:4],
        "source": "fallback",
        "interpretation_depth": "limited",
        "policy_version": CONCLUSION_POLICY_VERSION,
    }


def _empty(reason_code: str, summary: str) -> dict[str, Any]:
    return {
        "status": "limited",
        "variant": None,
        "headline": None,
        "summary": summary,
        "potential_or_meaning": None,
        "conditions_or_limits": None,
        "evidence_ids": [],
        "reason_code": reason_code,
        "source": "fallback",
        "interpretation_depth": "limited",
        "policy_version": CONCLUSION_POLICY_VERSION,
    }


def _copy(variant: str, relationship_type: str, status: Optional[str]) -> dict[str, str]:
    limit = "Персональное объяснение пока ограничено по глубине."
    if variant == "reflection":
        if relationship_type == "family" or status == "no_contact":
            return {
                "headline": "В этом родстве можно различить опыт контакта, не задачу его возобновить.",
                "summary": (
                    "Карта показывает возможные способы заботы и трения. "
                    "Она не устанавливает, почему дистанция возникла, и не зовёт восстановить контакт. "
                    f"{limit}"
                ),
            }
        return {
            "headline": "В этом контакте можно различить близость и то, что её затрудняло.",
            "summary": (
                "Итог опирается на темы глубокого разбора. "
                "Он не называет причину расставания и не обещает возвращения. "
                f"{limit}"
            ),
        }
    if variant == "uncertainty":
        return {
            "headline": "Ресурс связи можно назвать, а фазу решает разговор.",
            "summary": (
                "Карта называет возможную опору и место неоднозначности. "
                "Она не сообщает, чем контакт закончится, и не обещает, что человек вернётся. "
                f"{limit}"
            ),
        }
    if relationship_type == "friendship":
        return {
            "headline": "Дружба может держаться на разном способе участвовать в одном деле.",
            "summary": (
                "Итог не превращает дружбу в романтический сюжет и не решает, станет ли она ближе. "
                f"{limit}"
            ),
        }
    if relationship_type == "family":
        return {
            "headline": "В родстве рядом оказываются забота и границы.",
            "summary": (
                "Роли берутся только из переданного контекста. "
                "Это не романтическая история. "
                f"{limit}"
            ),
        }
    return {
        "headline": "Тепло связи и разница реакций могут существовать одновременно.",
        "summary": (
            "Итог называет возможный ресурс контакта. Решение развивать его остаётся за обоими. "
            "Нет обещания срока, взаимности или брака. "
            f"{limit}"
        ),
    }
