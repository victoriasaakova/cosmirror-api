"""
Вкладка «Циклы»: синтез по скиллу paid_report_cycles.

GET отдаёт детерминированный fallback из YAML-библиотеки.
LLM вызывается только из generate_cycles_interpretation().
Карточка атомарна: либо целиком сгенерированная, либо целиком fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from core.services import llm_client
from core.services.llm_prompts import (
    PROMPT_PAID_REPORT_CYCLES,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import grammatical_gender, reader_voice
from core.services.report_cycles_fallback import (
    PRIMARY_COUNT,
    category_for_polarity,
    fallback_cycles_interpretation,
    ranked_hits,
)
from core.services.report_types import SECTION_CYCLES

logger = logging.getLogger(__name__)

MIN_GENERATED_TEXT = 40

CYCLES_USER_CONTRACT = """\
Верни ТОЛЬКО JSON по контракту скилла. Схему ещё раз не дублируй.

Это текущее небо, не внутренние аспекты карты. Не пиши натальные квадраты
как «сейчас происходит». Не выдумывай транзиты, орбы, даты, дома.
cycle_id и category бери из входа. Не переопределяй ranking без нужды.

Русский, «ты». Род ТОЛЬКО из reader.grammatical_gender:
feminine — женский (внимательной, надёжной, готова); masculine — мужской;
unspecified — нейтрально, без мужского по умолчанию.
Не заполняй поле generic-фразой только потому, что оно есть в схеме.
"""


def cycles_cache_key(document: dict[str, Any]) -> str:
    rows = []
    for row in ranked_hits(document):
        rows.append(
            (
                row.get("id"),
                row.get("transit"),
                row.get("natal"),
                row.get("aspect"),
                round(float(row.get("orb") or 0), 2),
            )
        )
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    sky = ((document.get("factual") or {}).get("sky") or {}).get("datetime_utc") or ""
    raw = json.dumps(
        {"cycles": rows, "gender": grammatical_gender(quiz), "sky": sky[:10]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def apply_cycles_to_document(
    document: dict[str, Any],
    payload: dict[str, Any],
    *,
    source: str,
    model: str = "",
    error: str = "",
    generation_status: str = "",
    sealed: bool = False,
) -> dict[str, Any]:
    fallback = fallback_cycles_interpretation(document)
    if sealed and source == "llm" and isinstance(payload, dict) and payload.get("report_type") == "current_cycles":
        payload = {**payload, "source": "llm"}
        generation_status = generation_status or "generated"
    elif source == "llm":
        accepted = accept_generated_cycles(payload, fallback)
        if accepted is None:
            source = "fallback"
            payload = fallback
            generation_status = generation_status or "generation_failed"
            error = error or "invalid_llm_payload"
        else:
            payload = accepted
            generation_status = generation_status or "generated"
    else:
        payload = fallback
        generation_status = generation_status or (
            "generation_failed" if error else "fallback"
        )
    interpretive = document.setdefault("interpretive", {})
    if interpretive.get("status") != "llm":
        interpretive["status"] = "llm" if source == "llm" else "fallback"
    interpretive["cycles"] = {
        "source": source,
        "generation_status": generation_status,
        "status": "ready",
        "model": model,
        "error": error,
        "can_generate": llm_client.is_configured(),
        "payload": payload,
    }
    sections = document.setdefault("sections", {})
    cycle_section = sections.get(SECTION_CYCLES) or {
        "id": SECTION_CYCLES,
        "title": "Циклы",
        "layer": "interpretive",
        "blocks": [],
    }
    cycle_section["layer"] = "interpretive"
    cycle_section["blocks"] = cycles_blocks_from_payload(payload)
    sections[SECTION_CYCLES] = cycle_section
    return document


def cycles_blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    overview = payload.get("period_overview") or {}
    if overview.get("summary"):
        blocks.append(
            {
                "title": str(overview.get("headline") or "Текущий период"),
                "text": str(overview.get("summary")),
            }
        )
    for card in list(payload.get("primary_cycles") or []) + list(
        payload.get("secondary_cycles") or []
    ):
        if not isinstance(card, dict):
            continue
        source = str(card.get("source") or "")
        if source in {"fallback", "factual_fallback"} and not card.get("resource"):
            text = str(
                card.get("short_explanation") or card.get("summary") or ""
            ).strip()
        else:
            deep = card.get("deep_read")
            if isinstance(deep, list):
                deep_text = " ".join(str(p).strip() for p in deep if str(p).strip())
            else:
                deep_text = str(deep or "").strip()
            parts = [
                str(card.get("summary") or "").strip(),
                deep_text,
                str(card.get("protective_function") or card.get("protective_hypothesis") or "").strip(),
                str(card.get("resource") or "").strip(),
                str(card.get("tension_or_blind_spot") or "").strip(),
                str(card.get("how_to_work") or card.get("flexibility") or "").strip(),
            ]
            text = " ".join(part for part in parts if part)
        if not text:
            continue
        blocks.append(
            {
                "title": str(
                    card.get("headline")
                    or card.get("human_theme")
                    or card.get("technical_title")
                    or "Цикл"
                ),
                "text": text,
            }
        )
    return blocks or [
        {
            "title": "Текущие циклы",
            "text": "Значимых персональных транзитов в текущем орбе нет — смотри общий фон внешних планет.",
        }
    ]


def generate_cycles_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_cycles_interpretation(document)
    if not llm_client.is_configured():
        return {
            "ok": False,
            "source": "fallback",
            "generation_status": "fallback",
            "payload": fallback,
            "error": "llm_not_configured",
        }

    system = (
        "Перед работой держи Cosmirror editorial: гипотеза, не приговор; опыт сначала; "
        "без прогнозов, диагнозов и судьбы. Обращение на «ты». Русский как у носителя. "
        "Грамматический род — только из reader.grammatical_gender.\n\n"
        + load_prompt(PROMPT_PAID_REPORT_CYCLES).body.strip()
        + "\n\n"
        + CYCLES_USER_CONTRACT
    )
    user = json.dumps(_cycles_llm_user(document), ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=PROMPT_PAID_REPORT_CYCLES,
            temperature=0.55,
            max_tokens=8000,
        )
    except llm_client.LLMError as exc:
        logger.warning("Cycles LLM failed: %s", exc)
        return {
            "ok": False,
            "source": "fallback",
            "generation_status": "generation_failed",
            "payload": fallback,
            "error": str(exc),
        }

    accepted = accept_generated_cycles(raw, fallback)
    if accepted is None:
        logger.warning("Cycles LLM payload failed validation; keeping fallback")
        return {
            "ok": False,
            "source": "fallback",
            "generation_status": "generation_failed",
            "payload": fallback,
            "error": "invalid_llm_payload",
        }
    model = resolve_model(PROMPT_PAID_REPORT_CYCLES)
    return {
        "ok": True,
        "source": "llm",
        "generation_status": "generated",
        "payload": accepted,
        "error": "",
        "model": model,
    }


def cached_cycles_layer(order, document: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Вернуть sealed LLM-слой. Смена неба/cache_key не переписывает готовый текст."""
    store = getattr(order, "interpretive", None)
    if not isinstance(store, dict):
        return None
    layer = store.get("cycles")
    if not isinstance(layer, dict) or layer.get("status") != "ready":
        return None
    if str(layer.get("source") or "") != "llm":
        return None
    payload = layer.get("payload")
    if not isinstance(payload, dict) or payload.get("report_type") != "current_cycles":
        return None
    return layer


def save_cycles_layer(order, document: dict[str, Any], result: dict[str, Any]) -> None:
    from core.services.report_jobs import save_interpretive_layer

    source = str(result.get("source") or "fallback")
    save_interpretive_layer(
        order,
        "cycles",
        {
            "cache_key": cycles_cache_key(document),
            "source": source,
            "generation_status": result.get("generation_status")
            or ("generated" if source == "llm" else "fallback"),
            "status": "ready",
            "model": result.get("model") or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": result.get("error") or "",
            "payload": result.get("payload") or fallback_cycles_interpretation(document),
        },
    )


def accept_generated_cycles(raw: Any, fallback: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Принять LLM-отчёт целиком или отклонить. Поля фолбэка внутрь цикла не подмешиваются."""
    data = raw if isinstance(raw, dict) else None
    if data is None:
        return None
    overview = data.get("period_overview") if isinstance(data.get("period_overview"), dict) else {}
    headline = str(overview.get("headline") or "").strip()
    summary = str(overview.get("summary") or "").strip()
    if not headline or not summary:
        return None

    by_id: dict[str, dict[str, Any]] = {}
    for bucket in ("primary_cycles", "secondary_cycles", "cycles"):
        incoming = data.get(bucket)
        if not isinstance(incoming, list):
            continue
        for row in incoming:
            if isinstance(row, dict) and row.get("cycle_id"):
                by_id[str(row["cycle_id"])] = row

    expected_primary = [
        row for row in (fallback.get("primary_cycles") or []) if isinstance(row, dict)
    ]
    expected_secondary = [
        row for row in (fallback.get("secondary_cycles") or []) if isinstance(row, dict)
    ]
    if not expected_primary:
        return None

    primary: list[dict[str, Any]] = []
    generated_primary = 0
    for facts in expected_primary:
        cid = str(facts.get("cycle_id") or "")
        incoming = by_id.get(cid)
        if incoming and generated_cycle_is_valid(incoming, facts):
            primary.append(generated_cycle_from_llm(incoming, facts))
            generated_primary += 1
        else:
            return None
    if generated_primary == 0:
        return None

    secondary: list[dict[str, Any]] = []
    for facts in expected_secondary:
        cid = str(facts.get("cycle_id") or "")
        incoming = by_id.get(cid)
        if incoming and generated_cycle_is_valid(incoming, facts):
            secondary.append(generated_cycle_from_llm(incoming, facts))

    synthesis = generated_synthesis(data.get("cross_cycle_synthesis"))
    return {
        "report_type": "current_cycles",
        "source": "llm",
        "period_overview": {
            "headline": headline,
            "summary": summary,
            "main_tension": str(overview.get("main_tension") or "").strip(),
            "main_support": str(overview.get("main_support") or "").strip(),
        },
        "themes": [],
        "primary_cycles": primary,
        "secondary_cycles": secondary,
        "cross_cycle_synthesis": synthesis,
    }


def generated_cycle_is_valid(card: dict[str, Any], facts: dict[str, Any]) -> bool:
    if str(card.get("cycle_id") or "") != str(facts.get("cycle_id") or ""):
        return False
    summary = str(card.get("summary") or card.get("short_explanation") or "").strip()
    deep = card.get("deep_read")
    if isinstance(deep, list):
        deep_text = " ".join(str(part).strip() for part in deep if str(part).strip())
    else:
        deep_text = str(deep or "").strip()
    if len(summary) < MIN_GENERATED_TEXT and len(deep_text) < MIN_GENERATED_TEXT:
        return False
    expected_transit = str(facts.get("transit") or "")
    expected_natal = str(facts.get("natal") or "")
    got_transit = str(card.get("transit") or card.get("transiting_body") or "")
    got_natal = str(card.get("natal") or card.get("natal_target") or "")
    if got_transit and expected_transit and got_transit != expected_transit:
        return False
    if got_natal and expected_natal and got_natal != expected_natal:
        return False
    return True


def generated_cycle_from_llm(card: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    deep = card.get("deep_read")
    if isinstance(deep, list):
        deep_text = " ".join(str(part).strip() for part in deep if str(part).strip())
    else:
        deep_text = str(deep or "").strip()
    questions = card.get("reflection_questions")
    if not isinstance(questions, list):
        questions = []
    cleaned_questions = [str(item).strip() for item in questions if str(item).strip()]
    single = str(card.get("reflection_question") or "").strip()
    if single and single not in cleaned_questions:
        cleaned_questions = [single, *cleaned_questions]
    timing = card.get("timing") if isinstance(card.get("timing"), dict) else {}
    facts_timing = facts.get("timing") if isinstance(facts.get("timing"), dict) else {}
    manifestations = card.get("possible_manifestations")
    if not isinstance(manifestations, list):
        manifestations = []
    return {
        "source": "llm",
        "cycle_id": str(facts.get("cycle_id") or ""),
        "category": str(facts.get("category") or "mixed"),
        "technical_title": str(
            card.get("technical_title") or facts.get("technical_title") or ""
        ),
        "headline": str(card.get("headline") or card.get("human_theme") or "").strip(),
        "human_theme": str(card.get("human_theme") or card.get("headline") or "").strip(),
        "short_explanation": str(card.get("short_explanation") or "").strip(),
        "timing": {
            "orb_deg": facts_timing.get("orb_deg", timing.get("orb_deg")),
            "phase": str(facts_timing.get("phase") or timing.get("phase") or ""),
            "active_window_text": str(
                timing.get("active_window_text") or facts_timing.get("active_window_text") or ""
            ),
            "exact_passes_text": str(timing.get("exact_passes_text") or "").strip(),
        },
        "astrology_explanation": str(
            card.get("astrology_explanation") or card.get("astro_explanation") or ""
        ).strip(),
        "summary": str(card.get("summary") or card.get("short_explanation") or "").strip(),
        "deep_read": deep_text,
        "personalization": str(card.get("personalization") or "").strip(),
        "possible_manifestations": [
            str(item).strip() for item in manifestations if str(item).strip()
        ],
        "protective_function": str(
            card.get("protective_function") or card.get("protective_hypothesis") or ""
        ).strip(),
        "protective_hypothesis": str(
            card.get("protective_hypothesis") or card.get("protective_function") or ""
        ).strip(),
        "tension_or_blind_spot": str(card.get("tension_or_blind_spot") or "").strip(),
        "resource": str(card.get("resource") or "").strip(),
        "flexibility": str(card.get("flexibility") or card.get("how_to_work") or "").strip(),
        "how_to_work": str(card.get("how_to_work") or card.get("flexibility") or "").strip(),
        "astro_explanation": str(
            card.get("astro_explanation") or card.get("astrology_explanation") or ""
        ).strip(),
        "reflection_question": cleaned_questions[0] if cleaned_questions else "",
        "reflection_questions": cleaned_questions,
        "transit": str(facts.get("transit") or ""),
        "natal": str(facts.get("natal") or ""),
        "aspect": str(facts.get("aspect") or ""),
        "aspect_ru": str(facts.get("aspect_ru") or ""),
        "transit_name": str(facts.get("transit_name") or ""),
        "natal_name": str(facts.get("natal_name") or ""),
        "priority_score": facts.get("priority_score"),
    }


def generated_synthesis(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    narrative = str(raw.get("narrative") or "").strip()
    headline = str(raw.get("headline") or "").strip()
    if not narrative and not headline:
        return {}
    return {
        "headline": headline,
        "narrative": narrative,
        "what_to_watch": _str_list(raw.get("what_to_watch")),
        "available_support": _str_list(raw.get("available_support")),
        "reflection_questions": _str_list(raw.get("reflection_questions")),
    }


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _cycles_llm_user(document: dict[str, Any]) -> dict[str, Any]:
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    sky = (document.get("factual") or {}).get("sky") or {}
    primary_ids = {
        str(row.get("id"))
        for row in ((document.get("accents") or {}).get("primary") or [])
        if isinstance(row, dict) and row.get("id")
    }
    cycles = []
    for index, row in enumerate(ranked_hits(document)):
        window = row.get("window") if isinstance(row.get("window"), dict) else {}
        cid = str(row.get("id") or "")
        priority = "primary" if cid in primary_ids or index < PRIMARY_COUNT else "secondary"
        cycles.append(
            {
                "cycle_id": cid,
                "transiting_body": row.get("transit"),
                "natal_target": row.get("natal"),
                "aspect_type": row.get("aspect"),
                "category": category_for_polarity(str(row.get("polarity") or "mixed")),
                "orb_deg": row.get("orb"),
                "phase": row.get("motion"),
                "is_exact_now": float(row.get("orb") or 99) < 0.3,
                "active_window": {
                    "peak_estimate": window.get("peak_estimate"),
                    "span_note": window.get("span_note"),
                    "confidence": window.get("confidence"),
                },
                "natal_target_sign": row.get("natal_sign"),
                "natal_target_house": row.get("natal_house"),
                "transit_sign": row.get("transit_sign"),
                "significance_score": row.get("weight_hint"),
                "priority": priority,
                "technical_title": f"{row.get('transit_name')} {row.get('aspect_ru')} {row.get('natal_name')}",
            }
        )
    natal_payload = ((document.get("interpretive") or {}).get("natal") or {}).get("payload") or {}
    aspects_payload = ((document.get("interpretive") or {}).get("aspects") or {}).get("payload") or {}
    portrait = natal_payload.get("core_portrait") or {}
    return {
        "report_context": {
            "language": "ru",
            "current_date": str(sky.get("datetime_utc") or "")[:10],
            "depth": "full",
        },
        "reader": reader_voice(quiz),
        "natal_summary": {
            "headline": portrait.get("headline") or "",
            "summary": portrait.get("summary") or "",
            "identity_themes": [portrait.get("headline")] if portrait.get("headline") else [],
            "resources": _section_lines(natal_payload, "resource"),
            "tensions": _section_lines(natal_payload, "inner_conflict"),
        },
        "natal_aspects_summary": {
            "intro": ((aspects_payload.get("intro") or {}).get("headline") or ""),
            "dominant_dynamics": [
                {
                    "theme": str(card.get("headline") or ""),
                    "supporting_aspects": [str(card.get("aspect_label_ru") or "")],
                }
                for card in (aspects_payload.get("aspects") or [])[:5]
                if isinstance(card, dict) and card.get("headline")
            ],
        },
        "onboarding": {
            "focus": quiz.get("focus_labels") or quiz.get("focus") or [],
            "goals": quiz.get("focus_labels") or [],
            "intent": quiz.get("intent_label") or "",
            "life_stage": quiz.get("life_stage_label") or quiz.get("life_stage") or None,
        },
        "cycles": cycles,
        "note": "Это транзиты к наталу. Не интерпретируй как натальные аспекты.",
    }


def _section_lines(natal_payload: dict[str, Any], section_id: str) -> list[str]:
    lines = []
    for row in natal_payload.get("sections") or []:
        if not isinstance(row, dict) or str(row.get("id") or "") != section_id:
            continue
        for key in ("headline", "summary"):
            text = str(row.get(key) or "").strip()
            if text:
                lines.append(text)
    return lines
