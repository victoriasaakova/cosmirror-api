"""
Правила выбора акцентов длинного отчёта.

Модель не выбирает, о чём писать: она получает уже отобранный сюжет.
"""

from __future__ import annotations

from typing import Any

from core.services.personalize import (
    FOCUS_LABELS,
    INTENT_LABELS,
    LIFE_STAGE_LABELS,
)
from core.services.report_facts import estimate_window
from core.services.report_lexicon import WORK_WITH
from core.services.report_types import (
    CHART_KNOWLEDGE_LABELS,
    FOCUS_HOUSES,
    FOCUS_PLANETS,
    KNOWLEDGE_DEPTH,
    NATAL_POINT_WEIGHT,
    POLARITY_MIXED,
    POLARITY_PRESSURE,
    POLARITY_RESOURCE,
    PRESSURE_LIMIT,
    PRIMARY_LIMIT,
    PROMPT_NATAL_ASPECT_LIMIT,
    PROMPT_TRANSIT_LIMIT,
    RESOURCE_LIMIT,
    SUPPORT_LIMIT,
    THROUGH_LINE_HITS,
    TRANSIT_PLANET_WEIGHT,
    TRIGGER_LABELS,
)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def quiz_profile(quiz: dict[str, Any] | None) -> dict[str, Any]:
    quiz = quiz or {}
    focus = _as_list(quiz.get("focus"))
    intent = str(quiz.get("intent") or "")
    life_stage = str(quiz.get("life_stage") or quiz.get("lifeStage") or "")
    knowledge = str(quiz.get("chart_knowledge") or quiz.get("chartKnowledge") or "")
    trigger = str(quiz.get("astrology_trigger") or quiz.get("astrologyTrigger") or "")
    return {
        "name": str(quiz.get("name") or "").strip(),
        "gender": quiz.get("gender") or "",
        "age": quiz.get("age") or "",
        "focus": focus,
        "focus_labels": [FOCUS_LABELS.get(key, key) for key in focus],
        "intent": intent,
        "intent_label": INTENT_LABELS.get(intent, ""),
        "life_stage": life_stage,
        "life_stage_label": LIFE_STAGE_LABELS.get(life_stage, ""),
        "chart_knowledge": knowledge,
        "chart_knowledge_label": CHART_KNOWLEDGE_LABELS.get(knowledge, ""),
        "knowledge_depth": KNOWLEDGE_DEPTH.get(knowledge, "explain_transits"),
        "astrology_trigger": trigger,
        "astrology_trigger_label": TRIGGER_LABELS.get(trigger, ""),
    }


def _focus_boost(hit: dict[str, Any], focus_keys: list[str]) -> float:
    boost = 1.0
    natal = str(hit.get("natal") or "")
    house = hit.get("natal_house")
    for key in focus_keys:
        planets = FOCUS_PLANETS.get(key, ())
        houses = FOCUS_HOUSES.get(key, ())
        if natal in planets:
            boost += 0.22
        if house and int(house) in houses:
            boost += 0.16
    return min(boost, 1.7)


def score_transit(hit: dict[str, Any], focus_keys: list[str]) -> float:
    orb = float(hit.get("orb") or 0)
    max_orb = 6.0
    tightness = max(0.0, 1.0 - orb / max_orb)
    aspect_w = {
        "conjunction": 1.0,
        "opposition": 0.92,
        "square": 0.86,
        "trine": 0.7,
        "sextile": 0.55,
    }.get(str(hit.get("aspect") or ""), 0.5)
    natal_w = NATAL_POINT_WEIGHT.get(str(hit.get("natal") or ""), 0.45)
    transit_w = TRANSIT_PLANET_WEIGHT.get(str(hit.get("transit") or ""), 0.3)
    motion_w = {"applying": 1.08, "stationary": 1.12, "separating": 0.92}.get(
        str(hit.get("motion") or ""), 1.0
    )
    return tightness * aspect_w * natal_w * transit_w * motion_w * _focus_boost(hit, focus_keys)


def _with_score(hits: list[dict[str, Any]], focus_keys: list[str]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for hit in hits:
        row = dict(hit)
        row["score"] = round(score_transit(hit, focus_keys), 4)
        scored.append(row)
    scored.sort(key=lambda row: (-row["score"], row["orb"]))
    return scored


def _matches_focus(hit: dict[str, Any], focus_keys: list[str]) -> list[str]:
    natal = str(hit.get("natal") or "")
    house = hit.get("natal_house")
    matched: list[str] = []
    for key in focus_keys:
        planets = FOCUS_PLANETS.get(key, ())
        houses = FOCUS_HOUSES.get(key, ())
        if natal in planets or (house and int(house) in houses):
            matched.append(key)
    return matched


def through_line(scored: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Сквозная линия = планета главного акцента и все её попадания."""
    if not scored:
        return None
    lead = scored[0]
    key = str(lead.get("transit") or "")
    group = [hit for hit in scored if str(hit.get("transit") or "") == key][:THROUGH_LINE_HITS]
    if not group:
        return None
    natal_names = [str(item["natal_name"]) for item in group]
    total = sum(float(item["score"]) for item in group)
    return {
        "transit": key,
        "transit_name": group[0]["transit_name"],
        "score": round(total, 4),
        "hits": group,
        "natal_points": natal_names,
        "summary_fact": (
            f"Транзитный {group[0]['transit_name']} сейчас касается нескольких "
            f"натальных точек: {', '.join(natal_names)}. "
            "Это один растянутый сюжет, а не набор отдельных событий."
        ),
    }


def select_accents(
    *,
    transits: list[dict[str, Any]],
    natal_aspects: list[dict[str, Any]],
    quiz: dict[str, Any] | None,
    sky_iso: str = "",
) -> dict[str, Any]:
    profile = quiz_profile(quiz)
    focus = profile["focus"]
    scored = _with_score(transits, focus)
    for hit in scored:
        hit["window"] = estimate_window(hit, sky_iso)
        hit["work_with"] = WORK_WITH.get(str(hit.get("polarity") or ""), WORK_WITH["mixed"])
        hit["focus_match"] = _matches_focus(hit, focus)

    primary = scored[:PRIMARY_LIMIT]
    featured_ids = {row["id"] for row in primary}
    supporting = [row for row in scored if row["id"] not in featured_ids][:SUPPORT_LIMIT]
    pressure = [row for row in scored if row["polarity"] == POLARITY_PRESSURE][:PRESSURE_LIMIT]
    resource = [
        row
        for row in scored
        if row["polarity"] in (POLARITY_RESOURCE, POLARITY_MIXED)
    ][:RESOURCE_LIMIT]

    focus_matches = [row for row in scored if row.get("focus_match")][:6]
    natal_ranked = sorted(natal_aspects, key=lambda row: float(row.get("orb") or 99))[
        :PROMPT_NATAL_ASPECT_LIMIT
    ]

    return {
        "knowledge_depth": profile["knowledge_depth"],
        "primary": primary,
        "supporting": supporting,
        "pressure": pressure,
        "resource": resource,
        "focus_matches": focus_matches,
        "through_line": through_line(scored),
        "prompt_transits": scored[:PROMPT_TRANSIT_LIMIT],
        "natal_aspects": natal_ranked,
        "rules_applied": [
            "тесный орб важнее широкого",
            "внешние транзиты (Уран, Плутон, Нептун, Сатурн) задают сюжет отчёта",
            "соединение / оппозиция / квадрат громче тригона и секстиля",
            "светила и углы важнее внешних натальных точек",
            " overlapping hits одной транзитной планеты складываются в сквозную линию",
            "квиз (focus / life_stage / intent) поднимает релевантные дома и планеты, но не выдумывает аспекты",
        ],
    }
