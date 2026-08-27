"""
Вкладка «Запрос»: синтез по скиллу paid_report_request.

Интегрирует онбординг с уже готовыми natal / aspects / cycles.
GET отдаёт детерминированный semantic fallback из YAML.
LLM — только generate_request_interpretation().
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
    PROMPT_PAID_REPORT_REQUEST,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import grammatical_gender, reader_voice
from core.services.report_request_fallback import fallback_request_interpretation
from core.services.report_types import SECTION_REQUEST

logger = logging.getLogger(__name__)

MIN_TEXT = 40

REQUEST_USER_CONTRACT = """\
Верни ТОЛЬКО JSON по контракту скилла. Схему ещё раз не дублируй.

Это интеграция запроса с уже прочитанными слоями, не пересказ карты.
Не дублируй natal / aspects / cycles. Не выдумывай аспекты и транзиты.
Не включай вопросы, эксперименты и workbook — это вкладка «Практика».

connections: 2–3.
Русский, «ты». Род ТОЛЬКО из reader.grammatical_gender:
feminine — женский; masculine — мужской;
unspecified — нейтрально, без мужского по умолчанию.
Не заполняй поле generic-фразой только потому, что оно есть в схеме.
"""


def request_cache_key(document: dict[str, Any]) -> str:
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    natal = ((document.get("interpretive") or {}).get("natal") or {}).get("payload") or {}
    aspects = ((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {}
    cycles = ((document.get("interpretive") or {}).get("cycles") or {}).get("payload") or {}
    portrait = natal.get("core_portrait") if isinstance(natal.get("core_portrait"), dict) else {}
    intro = aspects.get("intro") if isinstance(aspects.get("intro"), dict) else {}
    overview = cycles.get("period_overview") if isinstance(cycles.get("period_overview"), dict) else {}
    raw = json.dumps(
        {
            "gender": grammatical_gender(quiz),
            "focus": quiz.get("focus") or quiz.get("focus_labels") or [],
            "intent": quiz.get("intent_label") or "",
            "life_stage": quiz.get("life_stage_label") or quiz.get("life_stage") or "",
            "trigger": quiz.get("astrology_trigger_label") or "",
            "natal": portrait.get("headline") or "",
            "aspects": intro.get("headline") or "",
            "cycles": overview.get("headline") or "",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def apply_request_to_document(
    document: dict[str, Any],
    payload: dict[str, Any],
    *,
    source: str,
    model: str = "",
    error: str = "",
    sealed: bool = False,
) -> dict[str, Any]:
    if sealed and source == "llm" and isinstance(payload, dict) and isinstance(payload.get("request"), dict):
        payload = {**payload, "source": "llm", "report_type": payload.get("report_type") or "request"}
    elif source == "llm":
        accepted = accept_generated_request(payload, fallback_request_interpretation(document))
        if accepted is None:
            source = "fallback"
            payload = fallback_request_interpretation(document)
            error = error or "invalid_llm_payload"
        else:
            payload = accepted
    else:
        payload = fallback_request_interpretation(document)

    interpretive = document.setdefault("interpretive", {})
    if interpretive.get("status") != "llm":
        interpretive["status"] = "llm" if source == "llm" else "fallback"
    interpretive["request"] = {
        "source": source,
        "status": "ready",
        "model": model,
        "error": error,
        "can_generate": llm_client.is_configured(),
        "payload": payload,
    }
    sections = document.setdefault("sections", {})
    section = sections.get(SECTION_REQUEST) or {
        "id": SECTION_REQUEST,
        "title": "Запрос",
        "layer": "interpretive",
        "blocks": [],
    }
    section["layer"] = "interpretive"
    section["blocks"] = request_blocks_from_payload(payload)
    sections[SECTION_REQUEST] = section
    return document


def request_blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    if request.get("title") or request.get("text"):
        blocks.append(
            {
                "title": str(request.get("title") or "Твой запрос"),
                "text": str(request.get("text") or ""),
                "kind": "request",
            }
        )
    for row in payload.get("connections") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        source = str(row.get("source_id") or row.get("source") or "").strip()
        source_type = str(row.get("source_type") or "").strip()
        meta = " · ".join(part for part in (source_type, source) if part)
        if meta:
            text = f"{meta}\n\n{text}".strip() if text else meta
        if not text and not row.get("title"):
            continue
        blocks.append(
            {
                "title": str(row.get("title") or "Пересечение с картой"),
                "text": text,
                "kind": "connection",
            }
        )
    distinction = (
        payload.get("core_distinction")
        if isinstance(payload.get("core_distinction"), dict)
        else payload.get("core_pattern")
        if isinstance(payload.get("core_pattern"), dict)
        else {}
    )
    if distinction.get("title") or distinction.get("text"):
        blocks.append(
            {
                "title": str(distinction.get("title") or "Главное различение"),
                "text": str(distinction.get("text") or ""),
                "kind": "distinction",
            }
        )
    resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
    if resource.get("text") or resource.get("title"):
        text = str(resource.get("text") or "").strip()
        source = str(resource.get("source_id") or resource.get("source") or "").strip()
        if source:
            text = f"{source}\n\n{text}".strip() if text else source
        blocks.append(
            {
                "title": str(resource.get("title") or "На что можно опереться"),
                "text": text,
                "kind": "resource",
            }
        )
    takeaway = str(payload.get("takeaway") or "").strip()
    if takeaway:
        blocks.append({"title": "Главное", "text": takeaway, "kind": "takeaway"})
    return blocks


def generate_request_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_request_interpretation(document)
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
        + load_prompt(PROMPT_PAID_REPORT_REQUEST).body.strip()
        + "\n\n"
        + REQUEST_USER_CONTRACT
    )
    user = json.dumps(_request_llm_user(document), ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=PROMPT_PAID_REPORT_REQUEST,
            temperature=0.55,
            max_tokens=4000,
        )
    except llm_client.LLMError as exc:
        logger.warning("Request LLM failed: %s", exc)
        return {"ok": False, "source": "fallback", "payload": fallback, "error": str(exc)}

    accepted = accept_generated_request(raw, fallback)
    if accepted is None:
        logger.warning("Request LLM payload failed validation; keeping fallback")
        return {
            "ok": False,
            "source": "fallback",
            "payload": fallback,
            "error": "invalid_llm_payload",
        }
    model = resolve_model(PROMPT_PAID_REPORT_REQUEST)
    return {
        "ok": True,
        "source": "llm",
        "payload": accepted,
        "error": "",
        "model": model,
    }


def cached_request_layer(order, document: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Вернуть sealed LLM-слой. Уже сгенерированный текст не сбрасывается."""
    store = getattr(order, "interpretive", None)
    if not isinstance(store, dict):
        return None
    layer = store.get("request")
    if not isinstance(layer, dict) or layer.get("status") != "ready":
        return None
    if str(layer.get("source") or "") != "llm":
        return None
    payload = layer.get("payload")
    if not isinstance(payload, dict):
        return None
    report_type = str(payload.get("report_type") or "")
    if report_type not in {"request", "paid_report_request"}:
        return None
    request = payload.get("request")
    if not isinstance(request, dict):
        return None
    return layer


def save_request_layer(order, document: dict[str, Any], result: dict[str, Any]) -> None:
    from core.services.report_jobs import save_interpretive_layer

    source = str(result.get("source") or "fallback")
    save_interpretive_layer(
        order,
        "request",
        {
            "cache_key": request_cache_key(document),
            "source": source,
            "status": "ready",
            "model": result.get("model") or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": result.get("error") or "",
            "payload": result.get("payload") or fallback_request_interpretation(document),
        },
    )


def accept_generated_request(raw: Any, fallback: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = raw if isinstance(raw, dict) else None
    if data is None:
        return None
    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    title = str(request.get("title") or "").strip()
    text = str(request.get("text") or "").strip()
    if len(title) < 4 or len(text) < MIN_TEXT:
        return None

    connections_raw = data.get("connections")
    if not isinstance(connections_raw, list):
        return None
    connections: list[dict[str, str]] = []
    for row in connections_raw:
        if not isinstance(row, dict):
            continue
        c_title = str(row.get("title") or "").strip()
        c_text = str(row.get("text") or "").strip()
        if len(c_title) < 3 or len(c_text) < MIN_TEXT:
            continue
        source_type = str(row.get("source_type") or "").strip()
        if source_type not in {"cycle", "aspect", "natal_theme"}:
            source_type = "natal_theme"
        connections.append(
            {
                "source_id": str(row.get("source_id") or row.get("source") or "").strip(),
                "source_type": source_type,
                "title": c_title,
                "text": c_text,
            }
        )
    if len(connections) < 2:
        return None

    distinction = (
        data.get("core_distinction")
        if isinstance(data.get("core_distinction"), dict)
        else data.get("core_pattern")
        if isinstance(data.get("core_pattern"), dict)
        else {}
    )
    d_title = str(distinction.get("title") or "").strip()
    d_text = str(distinction.get("text") or "").strip()
    if len(d_title) < 3 or len(d_text) < MIN_TEXT:
        return None
    provenance = [
        str(item).strip()
        for item in (distinction.get("provenance") or [])
        if str(item).strip()
    ]

    resource = data.get("resource") if isinstance(data.get("resource"), dict) else {}
    r_text = str(resource.get("text") or "").strip()
    if len(r_text) < MIN_TEXT:
        return None
    r_source_type = str(resource.get("source_type") or "").strip()
    if r_source_type not in {"cycle", "aspect", "natal_theme"}:
        r_source_type = "natal_theme"

    takeaway = str(data.get("takeaway") or "").strip()
    if len(takeaway) < MIN_TEXT:
        return None

    return {
        "report_type": "request",
        "source": "llm",
        "request": {"title": title, "text": text},
        "connections": connections[:3],
        "core_distinction": {
            "title": d_title,
            "text": d_text,
            "provenance": provenance[:6],
        },
        "resource": {
            "source_id": str(resource.get("source_id") or resource.get("source") or "").strip(),
            "source_type": r_source_type,
            "title": str(resource.get("title") or "На что можно опереться").strip(),
            "text": r_text,
        },
        "takeaway": takeaway,
    }


def _request_llm_user(document: dict[str, Any]) -> dict[str, Any]:
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    accents = document.get("accents") if isinstance(document.get("accents"), dict) else {}
    natal_payload = ((document.get("interpretive") or {}).get("natal") or {}).get("payload") or {}
    aspects_payload = ((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {}
    cycles_payload = ((document.get("interpretive") or {}).get("cycles") or {}).get("payload") or {}
    portrait = natal_payload.get("core_portrait") if isinstance(natal_payload, dict) else {}
    aspects_intro = aspects_payload.get("intro") if isinstance(aspects_payload, dict) else {}
    aspect_cards = []
    for row in (aspects_payload.get("aspects") or [])[:6]:
        if not isinstance(row, dict):
            continue
        aspect_cards.append(
            {
                "aspect_id": row.get("aspect_id"),
                "category": row.get("category"),
                "label": row.get("aspect_label_ru"),
                "headline": row.get("headline"),
                "summary": row.get("summary"),
            }
        )
    overview = cycles_payload.get("period_overview") if isinstance(cycles_payload, dict) else {}
    cycle_cards = []
    for bucket in ("primary_cycles", "secondary_cycles"):
        for row in cycles_payload.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            cycle_cards.append(
                {
                    "cycle_id": row.get("cycle_id"),
                    "category": row.get("category"),
                    "technical_title": row.get("technical_title"),
                    "headline": row.get("headline"),
                    "summary": row.get("summary") or row.get("short_explanation"),
                }
            )
    return {
        "reader": reader_voice(quiz),
        "onboarding": {
            "life_stage": quiz.get("life_stage_label") or quiz.get("life_stage") or None,
            "focus_areas": quiz.get("focus_labels") or quiz.get("focus") or [],
            "desired_outcome": quiz.get("intent_label") or None,
            "immediate_trigger": quiz.get("astrology_trigger_label") or None,
            "astrology_literacy": quiz.get("chart_knowledge_label")
            or quiz.get("knowledge_depth")
            or None,
        },
        "accents": {
            "through_line": accents.get("through_line"),
            "primary": (accents.get("primary") or [])[:2],
            "pressure": (accents.get("pressure") or [])[:3],
            "resource": (accents.get("resource") or [])[:3],
            "focus_matches": (accents.get("focus_matches") or [])[:3],
        },
        "natal_summary": {
            "headline": (portrait or {}).get("headline") or "",
            "summary": (portrait or {}).get("summary") or "",
        },
        "natal_aspects_summary": {
            "intro": (aspects_intro or {}).get("summary") or (aspects_intro or {}).get("headline") or "",
            "aspects": aspect_cards,
        },
        "current_cycles_summary": {
            "overview": (overview or {}).get("summary") or (overview or {}).get("headline") or "",
            "cycles": cycle_cards[:6],
        },
    }
