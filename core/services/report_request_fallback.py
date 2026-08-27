"""
Детерминированный fallback вкладки «Запрос».

Целые pre-authored blocks из YAML. Без склейки PLANET_FN и без новой
астрологической интерпретации — только релевантность к онбордингу.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

LIBRARY_PATH = (
    Path(__file__).resolve().parent.parent / "content" / "request_fallback_library.yaml"
)

MAX_CONNECTIONS = 3

# Product onboarding keys → library focus_sentences / focus_relevance keys.
FOCUS_TO_LIBRARY = {
    "love": "relationships",
    "relationships": "relationships",
    "money": "money",
    "energy": "energy",
    "confidence": "self_understanding",
    "path": "self_realization",
    "self_realization": "self_realization",
    "work": "work",
    "decision": "decision",
    "change": "change",
    "family_home": "family_home",
    "self_expression": "self_expression",
    "self_understanding": "self_understanding",
    "other": "default",
}

LIFE_STAGE_TO_LIBRARY = {
    "stable": "stable_search",
    "stable_search": "stable_search",
    "one-sphere": "transition",
    "many-spheres": "transition",
    "transition": "transition",
    "ready-to-change": "stuck",
    "stuck": "stuck",
    "unclear": "uncertainty",
    "uncertainty": "uncertainty",
    "new_beginning": "new_beginning",
    "growth": "growth",
}

INTENT_TO_OUTCOME = {
    "future": "understand_period",
    "potential": "understand_self",
    "uncertainty": "clarity",
    "relationships": "relationships",
    "patterns": "understand_self",
    "life-stage": "understand_period",
    "life_stage": "understand_period",
    "other": "default",
    "understand_self": "understand_self",
    "make_decision": "make_decision",
    "find_direction": "find_direction",
    "understand_period": "understand_period",
    "clarity": "clarity",
    "change": "change",
}

# Trigger can refine outcome when intent is vague.
TRIGGER_TO_OUTCOME = {
    "understand-self": "understand_self",
    "person": "relationships",
    "decision": "make_decision",
    "check-feelings": "clarity",
    "curious": "default",
}

# Bridge common Natal/Aspects/Cycles theme_tags → Request canonical themes.
EXTRA_THEME_ALIASES = {
    "freedom_vs_commitment": "structure_and_freedom",
    "freedom_and_commitment": "structure_and_freedom",
    "freedom_and_work": "structure_and_freedom",
    "growth_and_freedom": "structure_and_freedom",
    "action_and_freedom": "structure_and_freedom",
    "structure_and_creativity": "structure_and_freedom",
    "structure_and_visibility": "visibility_and_self_direction",
    "safety_and_structure": "safety_and_change",
    "closeness_and_structure": "closeness_and_autonomy",
    "intensity_and_closeness": "closeness_and_autonomy",
    "control_and_relationships": "closeness_and_autonomy",
    "identity_and_needs": "identity_and_autonomy",
    "identity_and_idealism": "idealism_and_reality",
    "idealism_and_growth": "idealism_and_reality",
    "image_and_values": "idealism_and_reality",
    "recognition_and_values": "visibility_and_self_direction",
    "power_and_visibility": "visibility_and_self_direction",
    "power_and_work": "meaning_and_direction",
    "power_and_growth": "growth_and_limits",
    "action_and_growth": "growth_and_limits",
    "emotion_and_growth": "growth_and_limits",
    "pleasure_and_limits": "growth_and_limits",
    "values_and_work": "meaning_and_direction",
    "voice_and_work": "visibility_and_self_direction",
    "voice_and_interface": "sensitivity_and_boundaries",
    "agency_and_interface": "sensitivity_and_boundaries",
    "emotional_regulation": "sensitivity_and_boundaries",
    "action_and_imagination": "idealism_and_reality",
    "innovation_and_thought": "analysis_and_spontaneity",
    "mind_and_structure": "analysis_and_spontaneity",
    "self_doubt_and_action": "quality_and_action",
    "self_understanding": "identity_and_autonomy",
    "change": "safety_and_change",
    "identity": "identity_and_autonomy",
}


@lru_cache(maxsize=1)
def load_request_fallback_library() -> dict[str, Any]:
    with LIBRARY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Request fallback library must be a mapping")
    indexed = dict(data)
    alias_map: dict[str, str] = {}
    themes = data.get("canonical_themes") if isinstance(data.get("canonical_themes"), dict) else {}
    for theme_id, row in themes.items():
        if not isinstance(row, dict):
            continue
        alias_map[str(theme_id)] = str(theme_id)
        for alias in row.get("aliases") or []:
            alias_map[str(alias).strip()] = str(theme_id)
    indexed["alias_map"] = alias_map
    return indexed


def fallback_request_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    library = load_request_fallback_library()
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    focus_keys = _library_focus_keys(quiz)
    life_key = _library_life_stage(quiz)
    outcome_key = _library_outcome(quiz)

    request_block = _request_summary(library, focus_keys, life_key, outcome_key)
    signals = _upstream_signals(document, library)
    relevant = _relevant_theme_ids(library, focus_keys)
    connections = _select_connections(library, signals, relevant, focus_keys)
    distinction = _core_distinction(library, connections, signals, relevant)
    resource = _resource_card(library, document, distinction, connections, signals)
    takeaway = _takeaway(library, focus_keys, outcome_key)

    return {
        "report_type": "request",
        "source": "semantic_fallback",
        "request": request_block,
        "connections": connections,
        "core_distinction": distinction,
        "resource": resource,
        "takeaway": takeaway,
    }


def _request_summary(
    library: dict[str, Any],
    focus_keys: list[str],
    life_key: str,
    outcome_key: str,
) -> dict[str, str]:
    life_sentences = library.get("life_stage_sentences") or {}
    focus_sentences = library.get("focus_sentences") or {}
    outcomes = library.get("outcomes") or {}

    life = str((life_sentences.get(life_key) or life_sentences.get("default") or "")).strip()
    if len(focus_keys) >= 2:
        focus = str(focus_sentences.get("multi") or focus_sentences.get("default") or "").strip()
    elif focus_keys:
        focus = str(
            focus_sentences.get(focus_keys[0]) or focus_sentences.get("default") or ""
        ).strip()
    else:
        focus = str(focus_sentences.get("default") or "").strip()

    outcome = outcomes.get(outcome_key) if isinstance(outcomes.get(outcome_key), dict) else {}
    if not outcome:
        outcome = outcomes.get("default") if isinstance(outcomes.get("default"), dict) else {}
    frame = str(outcome.get("text") or "").strip()
    title = str(outcome.get("title") or "Понять, что именно стоит различить").strip()

    parts = [part for part in (life, focus, frame) if part]
    return {"title": title, "text": " ".join(parts[:3]).strip()}


def _upstream_signals(document: dict[str, Any], library: dict[str, Any]) -> list[dict[str, Any]]:
    alias_map = library.get("alias_map") if isinstance(library.get("alias_map"), dict) else {}
    signals: list[dict[str, Any]] = []

    natal = ((document.get("interpretive") or {}).get("natal") or {}).get("payload") or {}
    for bucket in ("core_portrait",):
        portrait = natal.get(bucket) if isinstance(natal.get(bucket), dict) else {}
        for theme in portrait.get("themes") or []:
            if not isinstance(theme, dict):
                continue
            theme_id = _resolve_theme(str(theme.get("theme_id") or ""), alias_map)
            if not theme_id:
                continue
            signals.append(
                {
                    "source_id": str(theme.get("theme_id") or theme_id),
                    "source_type": "natal_theme",
                    "canonical_theme": theme_id,
                    "priority": 0.55,
                    "category": "mixed",
                    "is_resource": False,
                }
            )
    for theme in natal.get("repeating_themes") or []:
        if not isinstance(theme, dict):
            continue
        theme_id = _resolve_theme(str(theme.get("theme_id") or ""), alias_map)
        if not theme_id:
            continue
        signals.append(
            {
                "source_id": str(theme.get("theme_id") or theme_id),
                "source_type": "natal_theme",
                "canonical_theme": theme_id,
                "priority": 0.45,
                "category": "mixed",
                "is_resource": False,
            }
        )
    for card in natal.get("placements") or []:
        if not isinstance(card, dict) or card.get("factual"):
            continue
        for tag in card.get("theme_tags") or []:
            theme_id = _resolve_theme(str(tag), alias_map)
            if not theme_id:
                continue
            signals.append(
                {
                    "source_id": str(card.get("key") or card.get("point_key") or theme_id),
                    "source_type": "natal_theme",
                    "canonical_theme": theme_id,
                    "priority": 0.4,
                    "category": "mixed",
                    "is_resource": False,
                }
            )

    aspects = ((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {}
    for index, card in enumerate(aspects.get("aspects") or []):
        if not isinstance(card, dict) or card.get("factual"):
            continue
        priority = float(card.get("priority_score") or max(0.3, 0.9 - index * 0.08))
        category = str(card.get("category") or "mixed")
        tags = list(card.get("theme_tags") or [])
        if not tags:
            continue
        for tag in tags:
            theme_id = _resolve_theme(str(tag), alias_map)
            if not theme_id:
                continue
            signals.append(
                {
                    "source_id": str(card.get("aspect_id") or card.get("unit_key") or theme_id),
                    "source_type": "aspect",
                    "canonical_theme": theme_id,
                    "priority": priority,
                    "category": category,
                    "is_resource": category == "resource",
                    "resource_text": str(card.get("resource") or "").strip(),
                }
            )

    cycles = ((document.get("interpretive") or {}).get("cycles") or {}).get("payload") or {}
    cycle_index = 0
    for bucket in ("primary_cycles", "secondary_cycles"):
        for card in cycles.get(bucket) or []:
            if not isinstance(card, dict) or card.get("factual"):
                continue
            priority = float(card.get("priority_score") or max(0.35, 0.95 - cycle_index * 0.1))
            cycle_index += 1
            category = str(card.get("category") or "mixed")
            tags = list(card.get("theme_tags") or [])
            if not tags and card.get("unit_key"):
                tags = []
            for tag in tags:
                theme_id = _resolve_theme(str(tag), alias_map)
                if not theme_id:
                    continue
                signals.append(
                    {
                        "source_id": str(card.get("cycle_id") or card.get("unit_key") or theme_id),
                        "source_type": "cycle",
                        "canonical_theme": theme_id,
                        "priority": priority + (0.15 if bucket == "primary_cycles" else 0.0),
                        "category": category,
                        "is_resource": category in {"support", "resource"},
                        "resource_text": str(card.get("resource") or "").strip(),
                    }
                )

    # Accents fallback when interpretive cards lack theme_tags.
    accents = document.get("accents") if isinstance(document.get("accents"), dict) else {}
    for bucket, boost, is_resource in (
        ("primary", 0.85, False),
        ("pressure", 0.7, False),
        ("resource", 0.65, True),
        ("focus_matches", 0.6, False),
    ):
        for hit in accents.get(bucket) or []:
            if not isinstance(hit, dict):
                continue
            theme_ids = _themes_from_hit(hit, alias_map)
            if not theme_ids:
                continue
            for theme_id in theme_ids[:2]:
                signals.append(
                    {
                        "source_id": str(hit.get("id") or theme_id),
                        "source_type": "cycle",
                        "canonical_theme": theme_id,
                        "priority": float(hit.get("weight_hint") or boost),
                        "category": "support" if is_resource else "tension",
                        "is_resource": is_resource,
                        "resource_text": "",
                    }
                )

    return signals


def _themes_from_hit(hit: dict[str, Any], alias_map: dict[str, str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for tag in hit.get("theme_tags") or []:
        theme_id = _resolve_theme(str(tag), alias_map)
        if theme_id and theme_id not in seen:
            seen.add(theme_id)
            found.append(theme_id)
    if found:
        return found

    transit = _body_key(hit.get("transit") or hit.get("transit_key") or hit.get("transit_name") or "")
    natal = _body_key(hit.get("natal") or hit.get("natal_key") or hit.get("natal_name") or "")
    if not transit or not natal:
        transit, natal = _bodies_from_source_id(str(hit.get("id") or ""))
    guesses: list[str] = []
    if natal in {"sun", "ascendant"} or transit in {"uranus", "pluto"}:
        guesses.append("identity_and_autonomy")
    if natal in {"moon", "venus"} or transit == "neptune":
        guesses.append("closeness_and_autonomy")
    if natal == "saturn" or transit == "saturn":
        guesses.append("structure_and_freedom")
    if natal == "mars" or transit == "mars":
        guesses.append("action_and_pressure")
    if natal == "jupiter" or transit == "jupiter":
        guesses.append("growth_and_limits")
    for guess in guesses:
        resolved = _resolve_theme(guess, alias_map)
        if resolved and resolved not in seen:
            seen.add(resolved)
            found.append(resolved)
    if found:
        return found
    fallback = _resolve_theme("control_and_uncertainty", alias_map)
    return [fallback] if fallback else []


def _body_key(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    mapping = {
        "солнце": "sun",
        "луна": "moon",
        "меркурий": "mercury",
        "венера": "venus",
        "марс": "mars",
        "юпитер": "jupiter",
        "сатурн": "saturn",
        "уран": "uranus",
        "нептун": "neptune",
        "плутон": "pluto",
        "asc": "ascendant",
        "асц": "ascendant",
    }
    if text in mapping:
        return mapping[text]
    for key, value in mapping.items():
        if key in text:
            return value
    token = text.replace("натальн", "").replace("транзитн", "").strip()
    latin = {
        "sun",
        "moon",
        "mercury",
        "venus",
        "mars",
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
        "pluto",
        "ascendant",
    }
    return token if token in latin else ""


def _bodies_from_source_id(source_id: str) -> tuple[str, str]:
    # e.g. t_uranus_square_sun / natal_mercury_square_saturn
    parts = [part for part in str(source_id).lower().replace("-", "_").split("_") if part]
    bodies = {
        "sun",
        "moon",
        "mercury",
        "venus",
        "mars",
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
        "pluto",
        "asc",
        "ascendant",
        "mc",
    }
    found = [part if part != "asc" else "ascendant" for part in parts if part in bodies]
    if len(found) >= 2:
        return found[0], found[1]
    if len(found) == 1:
        return found[0], ""
    return "", ""


def _select_connections(
    library: dict[str, Any],
    signals: list[dict[str, Any]],
    relevant: set[str],
    focus_keys: list[str],
) -> list[dict[str, Any]]:
    themes = library.get("canonical_themes") if isinstance(library.get("canonical_themes"), dict) else {}
    ranked = sorted(
        signals,
        key=lambda row: (
            1 if row.get("canonical_theme") in relevant else 0,
            float(row.get("priority") or 0),
            1 if row.get("source_type") == "cycle" else 0,
        ),
        reverse=True,
    )
    chosen: list[dict[str, Any]] = []
    used_themes: set[str] = set()
    used_sources: set[str] = set()
    type_counts = {"cycle": 0, "aspect": 0, "natal_theme": 0}

    for row in ranked:
        theme_id = str(row.get("canonical_theme") or "")
        source_id = str(row.get("source_id") or "")
        source_type = str(row.get("source_type") or "natal_theme")
        if not theme_id or theme_id not in themes:
            continue
        if theme_id in used_themes:
            continue
        if source_id and source_id in used_sources:
            continue
        if source_type in type_counts and type_counts[source_type] >= 2 and len(chosen) < 2:
            # Prefer mix early; allow later if still short.
            if any(type_counts[key] == 0 for key in ("cycle", "aspect")):
                continue
        entry = themes[theme_id]
        if not isinstance(entry, dict):
            continue
        chosen.append(
            {
                "source_id": source_id or theme_id,
                "source_type": source_type if source_type in {"cycle", "aspect", "natal_theme"} else "natal_theme",
                "canonical_theme": theme_id,
                "title": str(entry.get("title") or theme_id).strip(),
                "text": str(entry.get("connection") or "").strip(),
            }
        )
        used_themes.add(theme_id)
        if source_id:
            used_sources.add(source_id)
        type_counts[source_type] = type_counts.get(source_type, 0) + 1
        if len(chosen) >= MAX_CONNECTIONS:
            break

    if len(chosen) < 2:
        # Prefer mix: add another focus-relevant theme block without inventing astrology.
        for theme_id in list(relevant) + ["control_and_uncertainty", "identity_and_autonomy"]:
            if len(chosen) >= 2:
                break
            if theme_id in used_themes or theme_id not in themes:
                continue
            entry = themes.get(theme_id)
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("connection") or "").strip()
            if len(text) < 40:
                continue
            chosen.append(
                {
                    "source_id": "onboarding_x_chart",
                    "source_type": "natal_theme",
                    "canonical_theme": theme_id,
                    "title": str(entry.get("title") or theme_id).strip(),
                    "text": text,
                }
            )
            used_themes.add(theme_id)

    if not chosen:
        # Safe minimal connection without inventing a hidden pattern.
        default_theme = next(iter(relevant), "control_and_uncertainty")
        if default_theme not in themes:
            default_theme = "control_and_uncertainty"
        entry = themes.get(default_theme) if isinstance(themes.get(default_theme), dict) else {}
        chosen.append(
            {
                "source_id": "onboarding_x_chart",
                "source_type": "natal_theme",
                "canonical_theme": default_theme,
                "title": str((entry or {}).get("title") or "Что проверить в запросе").strip(),
                "text": str(
                    (entry or {}).get("connection")
                    or (
                        "Прямого устойчивого совпадения между запросом и уже "
                        "интерпретированными слоями мало. Имеет смысл смотреть, "
                        "какие фрагменты карты и периода вообще отзываются — это тоже ответ."
                    )
                ).strip(),
            }
        )
    return chosen[:MAX_CONNECTIONS]


def _core_distinction(
    library: dict[str, Any],
    connections: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    relevant: set[str],
) -> dict[str, Any]:
    themes = library.get("canonical_themes") if isinstance(library.get("canonical_themes"), dict) else {}
    counts: dict[str, int] = {}
    for row in signals:
        theme_id = str(row.get("canonical_theme") or "")
        if not theme_id:
            continue
        counts[theme_id] = counts.get(theme_id, 0) + 1

    candidates: list[tuple[int, float, str]] = []
    for theme_id, count in counts.items():
        if theme_id not in themes:
            continue
        boost = 1 if theme_id in relevant else 0
        priority = max(
            (float(row.get("priority") or 0) for row in signals if row.get("canonical_theme") == theme_id),
            default=0.0,
        )
        candidates.append((boost, count + priority, theme_id))
    candidates.sort(reverse=True)

    theme_id = ""
    if candidates and (candidates[0][0] == 1 or candidates[0][1] >= 2):
        theme_id = candidates[0][2]
    elif connections:
        theme_id = str(connections[0].get("canonical_theme") or "")

    if not theme_id or theme_id not in themes:
        return {
            "canonical_theme": "",
            "title": "Своё желание ↔ привычная опора",
            "text": (
                "Уверенного повторяющегося совпадения между запросом и уже "
                "интерпретированными слоями сейчас нет. Полезно не придумывать "
                "скрытый паттерн, а проверять, какие фрагменты карты и периода "
                "вообще узнаются в опыте."
            ),
            "provenance": [row.get("source_id") for row in connections if row.get("source_id")],
        }

    entry = themes[theme_id]
    provenance = []
    for row in connections:
        if row.get("canonical_theme") == theme_id and row.get("source_id"):
            provenance.append(str(row["source_id"]))
    for row in signals:
        if row.get("canonical_theme") == theme_id and row.get("source_id"):
            sid = str(row["source_id"])
            if sid not in provenance:
                provenance.append(sid)
        if len(provenance) >= 4:
            break
    return {
        "canonical_theme": theme_id,
        "title": str(entry.get("title") or theme_id).strip(),
        "text": str(entry.get("distinction") or "").strip(),
        "provenance": provenance[:4],
    }


def _resource_card(
    library: dict[str, Any],
    document: dict[str, Any],
    distinction: dict[str, Any],
    connections: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    themes = library.get("canonical_themes") if isinstance(library.get("canonical_themes"), dict) else {}
    theme_id = str(distinction.get("canonical_theme") or "")
    support = [
        row
        for row in signals
        if row.get("is_resource") and (not theme_id or row.get("canonical_theme") == theme_id)
    ]
    support.sort(key=lambda row: float(row.get("priority") or 0), reverse=True)
    if not support:
        support = [row for row in signals if row.get("is_resource")]
        support.sort(key=lambda row: float(row.get("priority") or 0), reverse=True)

    if support:
        lead = support[0]
        theme_id = str(lead.get("canonical_theme") or theme_id)
        entry = themes.get(theme_id) if isinstance(themes.get(theme_id), dict) else {}
        text = str(lead.get("resource_text") or "").strip() or str((entry or {}).get("resource") or "").strip()
        return {
            "source_id": str(lead.get("source_id") or theme_id),
            "source_type": str(lead.get("source_type") or "natal_theme"),
            "title": "На что можно опереться",
            "text": text
            or (
                "Опора — то, что уже можно проверить в опыте: какие реакции повторяются, "
                "а какие оказываются разовыми."
            ),
        }

    entry = themes.get(theme_id) if isinstance(themes.get(theme_id), dict) else {}
    source_id = ""
    if connections:
        source_id = str(connections[0].get("source_id") or "")
    return {
        "source_id": source_id or theme_id or "lived_experience",
        "source_type": "natal_theme",
        "title": "На что можно опереться",
        "text": str((entry or {}).get("resource") or "").strip()
        or (
            "Самая надёжная опора здесь — то, что ты уже можешь проверить на неделях: "
            "какие реакции повторяются, а какие оказываются разовыми."
        ),
    }


def _takeaway(library: dict[str, Any], focus_keys: list[str], outcome_key: str) -> str:
    rows = library.get("takeaways") or []
    if not isinstance(rows, list) or not rows:
        return (
            "Карта не отвечает вместо тебя, но помогает точнее увидеть, "
            "какой вопрос стоит отделить от общего напряжения."
        )
    seed = abs(hash(("|".join(focus_keys), outcome_key)))
    return str(rows[seed % len(rows)]).strip()


def _relevant_theme_ids(library: dict[str, Any], focus_keys: list[str]) -> set[str]:
    matrix = library.get("focus_relevance") if isinstance(library.get("focus_relevance"), dict) else {}
    out: set[str] = set()
    for key in focus_keys:
        for theme_id in matrix.get(key) or []:
            out.add(str(theme_id))
    return out


def _library_focus_keys(quiz: dict[str, Any]) -> list[str]:
    raw = quiz.get("focus") or []
    if isinstance(raw, str):
        raw = [raw]
    mapped: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = FOCUS_TO_LIBRARY.get(str(item).strip(), "")
        if not key or key == "default" or key in seen:
            continue
        seen.add(key)
        mapped.append(key)
    return mapped


def _library_life_stage(quiz: dict[str, Any]) -> str:
    raw = str(quiz.get("life_stage") or "").strip()
    return LIFE_STAGE_TO_LIBRARY.get(raw, "default")


def _library_outcome(quiz: dict[str, Any]) -> str:
    intent = str(quiz.get("intent") or "").strip()
    if intent in INTENT_TO_OUTCOME:
        return INTENT_TO_OUTCOME[intent]
    trigger = str(quiz.get("astrology_trigger") or "").strip()
    if trigger in TRIGGER_TO_OUTCOME:
        return TRIGGER_TO_OUTCOME[trigger]
    return "default"


def _resolve_theme(tag: str, alias_map: dict[str, str]) -> str:
    key = str(tag or "").strip()
    if not key:
        return ""
    if key in alias_map:
        return str(alias_map[key])
    bridged = EXTRA_THEME_ALIASES.get(key)
    if bridged and bridged in alias_map:
        return bridged
    if bridged:
        return bridged
    return ""
