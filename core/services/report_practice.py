"""
Вкладка «Практика»: workbook по скиллу paid_report_practice.

Опирается на уже готовый слой «Запрос» + релевантные natal / aspects / cycles.
GET отдаёт детерминированный semantic fallback из YAML.
LLM — только generate_practice_interpretation().
Слой атомарный: либо целиком сгенерированный, либо целиком fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from core.services import llm_client
from core.services.llm_prompts import (
    PROMPT_PAID_REPORT_PRACTICE,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import grammatical_gender, reader_voice
from core.services.report_practice_fallback import fallback_practice_interpretation
from core.services.report_request import request_cache_key
from core.services.report_types import SECTION_PRACTICE

logger = logging.getLogger(__name__)

MIN_TEXT = 40

PRACTICE_USER_CONTRACT = """\
Верни ТОЛЬКО JSON по контракту скилла. Схему ещё раз не дублируй.

Это workbook после вкладки «Запрос». Не пересказывай астрологию заново.
Не создавай гипотезу, которой не было в предыдущих слоях.
Не советуй необратимых решений. Не заполняй финальный вывод за пользователя.

reflection_questions: 4–6. key_distinctions: 1–3. observe_over_time: 2–4.
Русский, «ты». Род ТОЛЬКО из reader.grammatical_gender:
feminine — женский; masculine — мужской;
unspecified — нейтрально, без мужского по умолчанию.
Не заполняй поле generic-фразой только потому, что оно есть в схеме.
"""


def practice_cache_key(document: dict[str, Any]) -> str:
    request_payload = ((document.get("interpretive") or {}).get("request") or {}).get("payload") or {}
    distinction = (
        request_payload.get("core_distinction")
        if isinstance(request_payload.get("core_distinction"), dict)
        else {}
    )
    raw = json.dumps(
        {
            "request_key": request_cache_key(document),
            "request_title": ((request_payload.get("request") or {}) if isinstance(request_payload.get("request"), dict) else {}).get("title") or "",
            "distinction": distinction.get("title") or "",
            "canonical_theme": distinction.get("canonical_theme") or "",
            "gender": grammatical_gender(
                document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def apply_practice_to_document(
    document: dict[str, Any],
    payload: dict[str, Any],
    *,
    source: str,
    model: str = "",
    error: str = "",
    sealed: bool = False,
) -> dict[str, Any]:
    if sealed and source == "llm" and isinstance(payload, dict) and isinstance(payload.get("start_here"), dict):
        payload = {**payload, "source": "llm", "report_type": payload.get("report_type") or "practice"}
    elif source == "llm":
        accepted = accept_generated_practice(payload, fallback_practice_interpretation(document))
        if accepted is None:
            source = "fallback"
            payload = fallback_practice_interpretation(document)
            error = error or "invalid_llm_payload"
        else:
            payload = accepted
    else:
        payload = fallback_practice_interpretation(document)

    interpretive = document.setdefault("interpretive", {})
    if interpretive.get("status") != "llm":
        interpretive["status"] = "llm" if source == "llm" else "fallback"
    interpretive["practice"] = {
        "source": source,
        "status": "ready",
        "model": model,
        "error": error,
        "can_generate": llm_client.is_configured(),
        "payload": payload,
    }
    sections = document.setdefault("sections", {})
    section = sections.get(SECTION_PRACTICE) or {
        "id": SECTION_PRACTICE,
        "title": "Практика",
        "layer": "interpretive",
        "blocks": [],
    }
    section["layer"] = "interpretive"
    section["blocks"] = practice_blocks_from_payload(payload)
    section["questions"] = list(payload.get("reflection_questions") or [])
    sections[SECTION_PRACTICE] = section
    return document


def practice_blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    start = payload.get("start_here") if isinstance(payload.get("start_here"), dict) else {}
    if start.get("headline") or start.get("text"):
        blocks.append(
            {
                "title": str(start.get("headline") or "С чего начать"),
                "text": str(start.get("text") or ""),
                "kind": "start_here",
            }
        )
    for key, default_title, kind in (
        ("pattern", "Что может повторяться", "pattern"),
        ("protective_function", "Что эта реакция может защищать", "protective"),
        ("cost", "Где это перестаёт помогать", "cost"),
        ("values", "Что здесь важно сохранить", "values"),
    ):
        row = payload.get(key) if isinstance(payload.get(key), dict) else {}
        if row.get("title") or row.get("text"):
            blocks.append(
                {
                    "title": str(row.get("title") or default_title),
                    "text": str(row.get("text") or ""),
                    "kind": kind,
                }
            )
    distinctions = payload.get("key_distinctions") or []
    if isinstance(distinctions, list) and distinctions:
        lines = []
        for row in distinctions:
            if not isinstance(row, dict):
                continue
            left = str(row.get("left") or "").strip()
            right = str(row.get("right") or "").strip()
            note = str(row.get("note") or "").strip()
            if not left and not right:
                continue
            line = f"{left} ≠ {right}".strip(" ≠")
            if note:
                line = f"{line}: {note}"
            lines.append(line)
        if lines:
            blocks.append(
                {
                    "title": "Что важно различить",
                    "text": "\n".join(lines),
                    "kind": "distinctions",
                }
            )
    experiment = payload.get("experiment") if isinstance(payload.get("experiment"), dict) else {}
    if experiment.get("text") or experiment.get("title"):
        text = str(experiment.get("text") or "").strip()
        duration = str(experiment.get("duration") or "").strip()
        if duration and duration.lower() != "null":
            text = f"{text}\n\nСрок: {duration}".strip()
        blocks.append(
            {
                "title": str(experiment.get("title") or "Попробуй проверить"),
                "text": text,
                "kind": "experiment",
            }
        )
    observe = [
        str(item).strip()
        for item in (payload.get("observe_over_time") or [])
        if str(item).strip()
    ]
    if observe:
        blocks.append(
            {
                "title": "Что наблюдать дальше",
                "text": "\n".join(f"• {item}" for item in observe),
                "kind": "observe",
            }
        )
    return blocks


def generate_practice_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_practice_interpretation(document)
    if not llm_client.is_configured():
        return {
            "ok": False,
            "source": "fallback",
            "payload": fallback,
            "error": "llm_not_configured",
        }

    system = (
        "Перед работой держи Cosmirror editorial: гипотеза, не приговор; опыт сначала; "
        "без прогнозов, диагнозов и судьбы. Обращение на «ты». Русский как у носителя. "
        "Грамматический род — только из reader.grammatical_gender.\n\n"
        + load_prompt(PROMPT_PAID_REPORT_PRACTICE).body.strip()
        + "\n\n"
        + PRACTICE_USER_CONTRACT
    )
    user = json.dumps(_practice_llm_user(document), ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=PROMPT_PAID_REPORT_PRACTICE,
            temperature=0.55,
            max_tokens=5000,
        )
    except llm_client.LLMError as exc:
        logger.warning("Practice LLM failed: %s", exc)
        return {"ok": False, "source": "fallback", "payload": fallback, "error": str(exc)}

    accepted = accept_generated_practice(raw, fallback)
    if accepted is None:
        logger.warning("Practice LLM payload failed validation; keeping fallback")
        return {
            "ok": False,
            "source": "fallback",
            "payload": fallback,
            "error": "invalid_llm_payload",
        }
    model = resolve_model(PROMPT_PAID_REPORT_PRACTICE)
    return {
        "ok": True,
        "source": "llm",
        "payload": accepted,
        "error": "",
        "model": model,
    }


def cached_practice_layer(order, document: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Вернуть sealed LLM-слой. Уже сгенерированный текст не сбрасывается."""
    store = getattr(order, "interpretive", None)
    if not isinstance(store, dict):
        return None
    layer = store.get("practice")
    if not isinstance(layer, dict) or layer.get("status") != "ready":
        return None
    if str(layer.get("source") or "") != "llm":
        return None
    payload = layer.get("payload")
    if not isinstance(payload, dict) or payload.get("report_type") != "practice":
        return None
    start = payload.get("start_here")
    if not isinstance(start, dict):
        return None
    return layer


def save_practice_layer(order, document: dict[str, Any], result: dict[str, Any]) -> None:
    from core.services.report_jobs import save_interpretive_layer

    source = str(result.get("source") or "fallback")
    save_interpretive_layer(
        order,
        "practice",
        {
            "cache_key": practice_cache_key(document),
            "source": source,
            "status": "ready",
            "model": result.get("model") or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": result.get("error") or "",
            "payload": result.get("payload") or fallback_practice_interpretation(document),
        },
    )


def accept_generated_practice(raw: Any, fallback: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = raw if isinstance(raw, dict) else None
    if data is None:
        return None

    start = data.get("start_here") if isinstance(data.get("start_here"), dict) else {}
    headline = str(start.get("headline") or "").strip()
    start_text = str(start.get("text") or "").strip()
    if len(headline) < 4 or len(start_text) < MIN_TEXT:
        return None

    pattern = data.get("pattern") if isinstance(data.get("pattern"), dict) else {}
    pattern_text = str(pattern.get("text") or "").strip()
    if len(pattern_text) < MIN_TEXT:
        return None

    protective = (
        data.get("protective_function")
        if isinstance(data.get("protective_function"), dict)
        else {}
    )
    protective_text = str(protective.get("text") or "").strip()
    if len(protective_text) < MIN_TEXT:
        return None

    cost = data.get("cost") if isinstance(data.get("cost"), dict) else {}
    cost_text = str(cost.get("text") or "").strip()
    if len(cost_text) < MIN_TEXT:
        return None

    distinctions_raw = data.get("key_distinctions")
    if not isinstance(distinctions_raw, list):
        return None
    distinctions: list[dict[str, str]] = []
    for row in distinctions_raw:
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
    if not distinctions:
        return None

    values = data.get("values") if isinstance(data.get("values"), dict) else {}
    values_text = str(values.get("text") or "").strip()
    if len(values_text) < MIN_TEXT:
        return None

    questions = [
        str(q).strip()
        for q in (data.get("reflection_questions") or [])
        if str(q).strip()
    ]
    if len(questions) < 4:
        return None

    experiment = data.get("experiment") if isinstance(data.get("experiment"), dict) else {}
    experiment_text = str(experiment.get("text") or "").strip()
    if len(experiment_text) < MIN_TEXT:
        return None
    duration = str(experiment.get("duration") or "").strip()
    if duration.lower() == "null":
        duration = ""

    observe = [
        str(item).strip()
        for item in (data.get("observe_over_time") or [])
        if str(item).strip()
    ]
    if len(observe) < 2:
        return None

    takeaway_prompt = str(data.get("user_takeaway_prompt") or "").strip()
    if len(takeaway_prompt) < 4:
        takeaway_prompt = str(fallback.get("user_takeaway_prompt") or "Сейчас мне важно различать…")

    return {
        "report_type": "practice",
        "source": "llm",
        "start_here": {
            "headline": headline,
            "text": start_text,
            "provenance": [
                str(item).strip()
                for item in (start.get("provenance") or [])
                if str(item).strip()
            ][:6],
        },
        "pattern": {
            "title": str(pattern.get("title") or "Что может повторяться").strip(),
            "text": pattern_text,
            "source_ids": [
                str(item).strip()
                for item in (pattern.get("source_ids") or [])
                if str(item).strip()
            ][:6],
        },
        "protective_function": {
            "title": str(
                protective.get("title") or "Что эта реакция может защищать"
            ).strip(),
            "text": protective_text,
        },
        "cost": {
            "title": str(cost.get("title") or "Где это перестаёт помогать").strip(),
            "text": cost_text,
        },
        "key_distinctions": distinctions[:3],
        "values": {
            "title": str(values.get("title") or "Что здесь важно сохранить").strip(),
            "text": values_text,
        },
        "reflection_questions": questions[:6],
        "experiment": {
            "title": str(experiment.get("title") or "Попробуй проверить").strip(),
            "text": experiment_text,
            "duration": duration or None,
        },
        "observe_over_time": observe[:4],
        "user_takeaway_prompt": takeaway_prompt,
    }


def _practice_llm_user(document: dict[str, Any]) -> dict[str, Any]:
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    request_layer = ((document.get("interpretive") or {}).get("request") or {})
    request_payload = request_layer.get("payload") if isinstance(request_layer, dict) else {}
    natal_payload = ((document.get("interpretive") or {}).get("natal") or {}).get("payload") or {}
    aspects_payload = ((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {}
    cycles_payload = ((document.get("interpretive") or {}).get("cycles") or {}).get("payload") or {}
    portrait = natal_payload.get("core_portrait") if isinstance(natal_payload, dict) else {}
    return {
        "reader": reader_voice(quiz),
        "onboarding": {
            "life_stage": quiz.get("life_stage_label") or quiz.get("life_stage") or None,
            "focus_areas": quiz.get("focus_labels") or quiz.get("focus") or [],
            "desired_outcome": quiz.get("intent_label") or None,
            "immediate_trigger": quiz.get("astrology_trigger_label") or None,
        },
        "request_output": request_payload if isinstance(request_payload, dict) else {},
        "natal_summary": {
            "headline": (portrait or {}).get("headline") or "",
            "summary": (portrait or {}).get("summary") or "",
        },
        "natal_aspects_summary": {
            "intro": ((aspects_payload.get("intro") or {}) if isinstance(aspects_payload, dict) else {}).get(
                "summary"
            )
            or "",
            "aspects": [
                {
                    "aspect_id": row.get("aspect_id"),
                    "headline": row.get("headline"),
                    "summary": row.get("summary"),
                }
                for row in (aspects_payload.get("aspects") or [])[:4]
                if isinstance(row, dict)
            ],
        },
        "current_cycles_summary": {
            "overview": (
                ((cycles_payload.get("period_overview") or {}) if isinstance(cycles_payload, dict) else {}).get(
                    "summary"
                )
                or ""
            ),
            "cycles": [
                {
                    "cycle_id": row.get("cycle_id"),
                    "headline": row.get("headline"),
                    "summary": row.get("summary") or row.get("short_explanation"),
                }
                for bucket in ("primary_cycles", "secondary_cycles")
                for row in (cycles_payload.get(bucket) or [])
                if isinstance(row, dict)
            ][:4],
        },
    }
