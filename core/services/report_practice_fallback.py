"""
Детерминированный fallback вкладки «Практика».

Выбирает один цельный workbook module из YAML по canonical_theme Запроса.
Без field-merge модулей и без новой астрологической гипотезы.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

LIBRARY_PATH = (
    Path(__file__).resolve().parent.parent / "content" / "practice_fallback_library.yaml"
)

DEFAULT_MODULE_ID = "generic_uncertainty_and_choice"

USER_TAKEAWAY_PROMPT = "Сейчас мне важно различать…"


@lru_cache(maxsize=1)
def load_practice_fallback_library() -> dict[str, Any]:
    with LIBRARY_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Practice fallback library must be a mapping")
    modules = data.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise ValueError("Practice fallback library needs modules")
    return data


def fallback_practice_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    library = load_practice_fallback_library()
    request_payload = _request_payload(document)
    module_id = _select_module_id(library, request_payload)
    module = _module(library, module_id)
    provenance = _provenance(request_payload)
    values_text = _values_text(module, document)

    distinctions: list[dict[str, str]] = []
    for row in module.get("distinctions") or []:
        if not isinstance(row, dict):
            continue
        left = str(row.get("left") or "").strip()
        right = str(row.get("right") or "").strip()
        if len(left) < 2 or len(right) < 2:
            continue
        distinctions.append(
            {
                "left": left,
                "right": right,
                "note": str(row.get("note") or "").strip(),
            }
        )

    questions = [
        str(item).strip()
        for item in (module.get("questions") or [])
        if str(item).strip()
    ]
    observe = [
        str(item).strip()
        for item in (module.get("observe") or [])
        if str(item).strip()
    ]

    return {
        "report_type": "practice",
        "source": "semantic_fallback",
        "module_id": module_id,
        "start_here": {
            "headline": str(module.get("headline") or "").strip(),
            "text": str(module.get("start_here") or "").strip(),
            "provenance": provenance[:6],
        },
        "pattern": {
            "title": "Что может повторяться",
            "text": str(module.get("pattern") or "").strip(),
            "source_ids": provenance[:6],
        },
        "protective_function": {
            "title": "Что эта реакция может защищать",
            "text": str(module.get("protective_function") or "").strip(),
        },
        "cost": {
            "title": "Где это перестаёт помогать",
            "text": str(module.get("cost") or "").strip(),
        },
        "key_distinctions": distinctions[:3],
        "values": {
            "title": "Что здесь важно сохранить",
            "text": values_text,
        },
        "reflection_questions": questions[:6],
        "experiment": {
            "title": "Попробуй проверить",
            "text": str(module.get("experiment") or "").strip(),
            "duration": "несколько дней",
        },
        "observe_over_time": observe[:4],
        "user_takeaway_prompt": USER_TAKEAWAY_PROMPT,
        "provenance": provenance[:6],
    }


def _request_payload(document: dict[str, Any]) -> dict[str, Any]:
    layer = ((document.get("interpretive") or {}).get("request") or {})
    payload = layer.get("payload") if isinstance(layer, dict) else None
    return payload if isinstance(payload, dict) else {}


def _select_module_id(library: dict[str, Any], request_payload: dict[str, Any]) -> str:
    modules = library.get("modules") if isinstance(library.get("modules"), dict) else {}
    theme_map = (
        library.get("request_theme_to_module")
        if isinstance(library.get("request_theme_to_module"), dict)
        else {}
    )

    candidates: list[str] = []

    distinction = (
        request_payload.get("core_distinction")
        if isinstance(request_payload.get("core_distinction"), dict)
        else {}
    )
    theme = str(distinction.get("canonical_theme") or "").strip()
    if theme:
        candidates.append(theme)

    for row in request_payload.get("connections") or []:
        if not isinstance(row, dict):
            continue
        conn_theme = str(row.get("canonical_theme") or "").strip()
        if conn_theme:
            candidates.append(conn_theme)

    # Repeated theme among connections + distinction.
    counts: dict[str, int] = {}
    for item in candidates:
        counts[item] = counts.get(item, 0) + 1
    repeated = sorted(
        ((count, key) for key, count in counts.items() if count >= 2),
        reverse=True,
    )
    if repeated:
        candidates.insert(0, repeated[0][1])

    for raw in candidates:
        mapped = str(theme_map.get(raw) or raw).strip()
        if mapped in modules:
            return mapped

    if DEFAULT_MODULE_ID in modules:
        return DEFAULT_MODULE_ID
    return next(iter(modules))


def _module(library: dict[str, Any], module_id: str) -> dict[str, Any]:
    modules = library.get("modules") if isinstance(library.get("modules"), dict) else {}
    row = modules.get(module_id)
    if isinstance(row, dict):
        return row
    fallback = modules.get(DEFAULT_MODULE_ID)
    return fallback if isinstance(fallback, dict) else {}


def _provenance(request_payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    distinction = (
        request_payload.get("core_distinction")
        if isinstance(request_payload.get("core_distinction"), dict)
        else {}
    )
    for item in distinction.get("provenance") or []:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            found.append(value)
    for row in request_payload.get("connections") or []:
        if not isinstance(row, dict):
            continue
        value = str(row.get("source_id") or "").strip()
        if value and value not in seen:
            seen.add(value)
            found.append(value)
    resource = (
        request_payload.get("resource")
        if isinstance(request_payload.get("resource"), dict)
        else {}
    )
    value = str(resource.get("source_id") or "").strip()
    if value and value not in seen:
        found.append(value)
    if not found:
        found = ["request"]
    return found


def _values_text(module: dict[str, Any], document: dict[str, Any]) -> str:
    base = str(module.get("values") or "").strip()
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    explicit = str(quiz.get("intent_label") or "").strip()
    if not explicit:
        return base
    note = (
        f"Из онбординга уже звучит желание: {explicit}. "
        "Имей это в виду как явную ценность, не как готовый вывод."
    )
    if not base:
        return note
    return f"{base}\n\n{note}"
