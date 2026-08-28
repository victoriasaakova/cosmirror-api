"""
Deterministic onboarding insight fallback (screen 0).

Normalize quiz enums, score themes from ranked influences, pick an authored
atomic opening+body. No LLM, no sentence Lego from quiz labels.
"""

from __future__ import annotations

import copy
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

SEMANTICS_PATH = Path(__file__).resolve().parent.parent / "content" / "onboarding_semantics.yaml"
LIBRARY_PATH = Path(__file__).resolve().parent.parent / "content" / "onboarding_fallback_library.yaml"

INFLUENCE_KEY_RE = re.compile(
    r"^(jupiter|saturn|uranus|neptune|pluto)_on_(sun|moon|ascendant|midheaven|venus|mars)$"
)


@lru_cache(maxsize=1)
def load_onboarding_semantics() -> dict[str, Any]:
    data = yaml.safe_load(SEMANTICS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Onboarding semantics must be a mapping")
    return data


@lru_cache(maxsize=1)
def load_onboarding_fallback_library() -> dict[str, Any]:
    data = yaml.safe_load(LIBRARY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("themes"), dict):
        raise ValueError("Onboarding fallback library must include themes")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_onboarding(raw_quiz: Optional[dict[str, Any]]) -> dict[str, Any]:
    quiz = raw_quiz if isinstance(raw_quiz, dict) else {}
    semantics = load_onboarding_semantics()
    adapter = ((semantics.get("adapters") or {}).get("current_onboarding_v1") or {}).get("fields") or {}
    vocab = semantics.get("stable_vocabulary") or {}

    focuses: list[str] = []
    focus_map = ((adapter.get("focus") or {}).get("raw_to_semantic") or {})
    for raw in _as_list(quiz.get("focus")):
        mapped = focus_map.get(raw)
        if mapped is None:
            logger.info("Unmapped onboarding focus: %s", raw)
            continue
        for tag in _as_list(mapped):
            if tag not in focuses:
                focuses.append(tag)

    def _map_single(field: str, raw_key: str, vocab_key: str) -> list[str]:
        raw = str(quiz.get(raw_key) or "").strip()
        if not raw:
            return []
        mapping = (adapter.get(field) or {}).get("raw_to_semantic") or {}
        mapped = mapping.get(raw)
        if mapped is None:
            logger.info("Unmapped onboarding %s: %s", raw_key, raw)
            return []
        allowed = set(vocab.get(vocab_key) or [])
        return [tag for tag in _as_list(mapped) if not allowed or tag in allowed]

    gender_raw = str(quiz.get("gender") or "").strip()
    gender_map = (adapter.get("gender") or {}).get("raw_to_semantic") or {}
    gender = gender_map.get(gender_raw) or (adapter.get("gender") or {}).get("missing_or_unknown") or "unknown"

    return {
        "focuses": focuses,
        "desired_outcomes": _map_single("intent", "intent", "desired_outcomes"),
        "life_context": _map_single("life_stage", "life_stage", "life_context"),
        "triggers": _map_single("astrology_trigger", "astrology_trigger", "triggers"),
        "astrology_literacy": _map_single("chart_knowledge", "chart_knowledge", "astrology_literacy"),
        "gender": gender if gender in (vocab.get("gender") or ["female", "male", "unknown"]) else "unknown",
    }


def _parse_influence_key(key: str) -> Optional[tuple[str, str]]:
    match = INFLUENCE_KEY_RE.match(key)
    if not match:
        return None
    return match.group(1), match.group(2)


def _theme_support_for_key(key: str) -> dict[str, float]:
    mappings = load_onboarding_semantics().get("signal_mappings") or {}
    exact = (mappings.get("exact_rules") or {}).get(key)
    if isinstance(exact, dict):
        support = exact.get("theme_support") or {}
        if isinstance(support, dict):
            return {str(theme): float(weight) for theme, weight in support.items() if float(weight) > 0}

    parsed = _parse_influence_key(key)
    if parsed is None:
        logger.info("Unmapped onboarding influence key: %s", key)
        return {}
    planet, target = parsed
    for rule in mappings.get("family_rules") or []:
        if not isinstance(rule, dict):
            continue
        match = rule.get("match") or {}
        if match.get("planet") != planet:
            continue
        targets = match.get("natal_targets") or []
        if target not in targets:
            continue
        support = rule.get("theme_support") or {}
        if not isinstance(support, dict):
            return {}
        return {str(theme): float(weight) for theme, weight in support.items() if float(weight) > 0}
    logger.info("Unmapped onboarding influence key: %s", key)
    return {}


def _position_multiplier(index: int) -> float:
    scoring = (load_onboarding_semantics().get("selection_v1") or {}).get("theme_scoring") or {}
    table = scoring.get("influence_position_multipliers") or {}
    if index in table:
        return float(table[index])
    if str(index) in table:
        return float(table[str(index)])
    last = table.get(2, table.get("2", 0.40))
    return float(last)


def score_themes(influences: list[dict[str, Any]]) -> dict[str, Any]:
    library = load_onboarding_fallback_library()
    themes_meta = library.get("themes") or {}
    totals: dict[str, float] = {}
    best_single: dict[str, float] = {}
    earliest: dict[str, int] = {}

    for index, item in enumerate(influences or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        support = _theme_support_for_key(key)
        if not support:
            continue
        multiplier = _position_multiplier(index)
        for theme, weight in support.items():
            contribution = weight * multiplier
            totals[theme] = totals.get(theme, 0.0) + contribution
            if contribution > best_single.get(theme, 0.0):
                best_single[theme] = contribution
            if theme not in earliest or index < earliest[theme]:
                earliest[theme] = index

    if not totals:
        return {"theme_id": None, "scores": {}, "source": "global_fallback"}

    def sort_key(theme_id: str) -> tuple:
        meta = themes_meta.get(theme_id) or {}
        priority = int(meta.get("priority") or 0)
        return (
            -totals[theme_id],
            -best_single.get(theme_id, 0.0),
            earliest.get(theme_id, 99),
            -priority,
            theme_id,
        )

    winner = min(totals, key=sort_key)
    return {
        "theme_id": winner,
        "scores": totals,
        "best_single": best_single,
        "earliest": earliest,
        "source": "theme",
    }


def _non_selecting_tags() -> dict[str, set[str]]:
    raw = (load_onboarding_semantics().get("selection_v1") or {}).get("non_selecting_tags") or {}
    return {str(kind): {str(tag) for tag in (tags or [])} for kind, tags in raw.items()}


def _variant_score(variant: dict[str, Any], context: dict[str, Any]) -> int:
    weights = (
        ((load_onboarding_semantics().get("selection_v1") or {}).get("variant_scoring") or {}).get("weights")
        or {}
    )
    skip = _non_selecting_tags()
    tags = variant.get("tags") or {}
    score = 0
    for kind, context_key in (
        ("focuses", "focuses"),
        ("desired_outcomes", "desired_outcomes"),
        ("life_context", "life_context"),
        ("triggers", "triggers"),
    ):
        blocked = skip.get(kind, set())
        present = set(context.get(context_key) or [])
        weight = int(weights.get(kind) or 0)
        for tag in tags.get(kind) or []:
            if tag in blocked:
                continue
            if tag in present:
                score += weight
    return score


def select_variant(theme_id: str, context: dict[str, Any]) -> dict[str, Any]:
    library = load_onboarding_fallback_library()
    theme = (library.get("themes") or {}).get(theme_id) or {}
    variants = theme.get("variants") or {}
    default = variants.get("default") if isinstance(variants.get("default"), dict) else None
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for variant_id, variant in variants.items():
        if variant_id == "default" or not isinstance(variant, dict):
            continue
        points = _variant_score(variant, context)
        if points <= 0:
            continue
        priority = int(variant.get("priority") or 0)
        scored.append((-points, -priority, variant_id, variant))
    if scored:
        scored.sort()
        _, _, variant_id, variant = scored[0]
        return {"variant_id": variant_id, "unit": variant}
    if default:
        return {"variant_id": "default", "unit": default}
    return {"variant_id": "global_fallback", "unit": library.get("global_fallback") or {}}


def _realize_gender(unit: dict[str, Any], gender: str) -> dict[str, str]:
    opening = str(unit.get("opening") or "").strip()
    body = str(unit.get("body") or "").strip()
    overrides = unit.get("gender_overrides") if isinstance(unit.get("gender_overrides"), dict) else {}
    chosen = overrides.get(gender) if gender in ("female", "male") else None
    if isinstance(chosen, dict):
        if chosen.get("opening"):
            opening = str(chosen["opening"]).strip()
        if chosen.get("body"):
            body = str(chosen["body"]).strip()
    return {"opening": opening, "body": body}


def _render_opening(unit: dict[str, Any], gender: str) -> dict[str, str]:
    library = load_onboarding_fallback_library()
    bridges = library.get("canonical_bridges") or {}
    realized = _realize_gender(unit, gender)
    bridge_key = str(unit.get("bridge_key") or "recognition")
    bridge = str(bridges.get(bridge_key) or bridges.get("recognition") or "").strip()
    return {"bridge": bridge, "insight": realized["opening"]}


def build_onboarding_fallback(
    *,
    insight: dict[str, Any],
    natal: Optional[dict[str, Any]] = None,
    quiz: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from core.services.personalize import default_offer, default_outcomes, default_product_pitch

    quiz = quiz or {}
    natal = natal or {}
    out = copy.deepcopy(insight) if insight else {}
    context = normalize_onboarding(quiz)
    influences = [item for item in (out.get("influences") or []) if isinstance(item, dict)]
    theme_result = score_themes(influences)
    library = load_onboarding_fallback_library()

    if theme_result["theme_id"]:
        chosen = select_variant(theme_result["theme_id"], context)
        theme_id = theme_result["theme_id"]
        variant_id = chosen["variant_id"]
        unit = chosen["unit"]
    else:
        theme_id = "self_observation_and_direction"
        variant_id = "global_fallback"
        unit = library.get("global_fallback") or {}

    gender = str(context.get("gender") or "unknown")
    realized = _realize_gender(unit, gender)
    opening = _render_opening(unit, gender)

    out.setdefault("tone", "pattern_psych")
    out["opening"] = opening
    out["body"] = realized["body"]
    out["product_pitch"] = default_product_pitch(out.get("cycles") or [], quiz, natal)
    out["outcomes"] = default_outcomes(quiz)
    out["offer"] = default_offer(quiz)
    out["funnel_version"] = 5
    out["source"] = "templates"
    out["fallback_theme"] = theme_id
    out["fallback_variant"] = variant_id
    return out
