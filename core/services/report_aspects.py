"""
Вкладка «Аспекты»: синтез по скиллу paid_report_aspects.

GET отдаёт детерминированный fallback из YAML-библиотеки.
LLM вызывается только из generate_aspects_interpretation().
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
    PROMPT_PAID_REPORT_ASPECTS,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import grammatical_gender, reader_voice
from core.services.report_aspects_fallback import (
    build_aspect_card,
    fallback_aspects_interpretation,
    load_aspects_fallback_library,
    ranked_aspects,
)
from core.services.report_types import SECTION_ASPECTS

logger = logging.getLogger(__name__)

MIN_GENERATED_TEXT = 40

ASPECTS_USER_CONTRACT = """\
Верни ТОЛЬКО JSON по контракту скилла. Схему ещё раз не дублируй.

Это внутренние связи карты, не текущее небо. Не пиши транзиты, окна,
«что будет», квиз онбординга и не дублируй вкладку «Твоя карта».
Только аспекты из JSON пользователя. category бери из входа.

Для 6 аспектов с наивысшим priority_score: depth=full (deep_read 4 абзаца).
Для остальных: standard (deep_read 2–3 абзаца). Не делай synthesis всей карты.

Русский, «ты». Род ТОЛЬКО из reader.grammatical_gender:
feminine — женский (внимательной, надёжной, готова); masculine — мужской;
unspecified — нейтрально, без мужского по умолчанию.
Не заполняй поле generic-фразой только потому, что оно есть в схеме.
Не подставляй словарные функции планет механически в предложение.
"""


def aspects_cache_key(document: dict[str, Any]) -> str:
    rows = []
    for row in _factual_aspects(document):
        rows.append(
            (
                row.get("a"),
                row.get("b"),
                row.get("aspect"),
                round(float(row.get("orb") or 0), 2),
            )
        )
    rows.sort()
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    raw = json.dumps(
        {"aspects": rows, "gender": grammatical_gender(quiz)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def apply_aspects_to_document(
    document: dict[str, Any],
    payload: dict[str, Any],
    *,
    source: str,
    model: str = "",
) -> dict[str, Any]:
    payload = normalize_aspects_payload(payload, fallback_aspects_interpretation(document))
    if source == "fallback":
        payload["source"] = "fallback"
    interpretive = document.setdefault("interpretive", {})
    if interpretive.get("status") != "llm":
        interpretive["status"] = "llm" if source == "llm" else "fallback"
    interpretive["aspects"] = {
        "source": source,
        "status": "ready",
        "model": model,
        "can_generate": llm_client.is_configured(),
        "payload": payload,
    }
    sections = document.setdefault("sections", {})
    aspect_section = sections.get(SECTION_ASPECTS) or {
        "id": SECTION_ASPECTS,
        "title": "Аспекты",
        "layer": "interpretive",
        "blocks": [],
    }
    aspect_section["layer"] = "interpretive"
    aspect_section["blocks"] = aspects_blocks_from_payload(payload)
    sections[SECTION_ASPECTS] = aspect_section
    return document


def aspects_blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    intro = payload.get("intro") or {}
    if intro.get("summary"):
        blocks.append(
            {
                "title": str(intro.get("headline") or "Как темы связаны внутри"),
                "text": str(intro.get("summary")),
            }
        )
    for card in payload.get("aspects") or []:
        if not isinstance(card, dict):
            continue
        parts = [
            str(card.get("summary") or "").strip(),
            *[str(p).strip() for p in (card.get("deep_read") or []) if str(p).strip()],
            str(card.get("protective_hypothesis") or "").strip(),
            str(card.get("resource") or "").strip(),
            str(card.get("tension_or_blind_spot") or card.get("blind_spot") or "").strip(),
            str(card.get("how_to_work") or card.get("flexibility") or "").strip(),
        ]
        text = " ".join(part for part in parts if part)
        if not text:
            continue
        blocks.append(
            {
                "title": str(card.get("headline") or card.get("aspect_label_ru") or "Аспект"),
                "text": text,
            }
        )
    return blocks or [
        {
            "title": "Натальные аспекты",
            "text": "В текущем расчёте тесных натальных аспектов нет — смотри положения и дома.",
        }
    ]


def generate_aspects_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_aspects_interpretation(document)
    if not llm_client.is_configured():
        return {"ok": False, "source": "fallback", "payload": fallback, "error": "llm_not_configured"}

    system = (
        "Перед работой держи Cosmirror editorial: гипотеза, не приговор; опыт сначала; "
        "без прогнозов, диагнозов и судьбы. Обращение на «ты». Русский как у носителя. "
        "Грамматический род — только из reader.grammatical_gender.\n\n"
        + load_prompt(PROMPT_PAID_REPORT_ASPECTS).body.strip()
        + "\n\n"
        + ASPECTS_USER_CONTRACT
    )
    user = json.dumps(_aspects_llm_user(document), ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=PROMPT_PAID_REPORT_ASPECTS,
            temperature=0.55,
            max_tokens=12000,
        )
    except llm_client.LLMError as exc:
        logger.warning("Aspects LLM failed: %s", exc)
        return {"ok": False, "source": "fallback", "payload": fallback, "error": str(exc)}

    payload = normalize_aspects_payload(raw, fallback)
    if payload.get("source") != "llm":
        return {
            "ok": False,
            "source": "fallback",
            "payload": fallback,
            "error": "invalid_generated_aspects",
        }
    model = resolve_model(PROMPT_PAID_REPORT_ASPECTS)
    return {"ok": True, "source": "llm", "payload": payload, "error": "", "model": model}


def cached_aspects_layer(order, document: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Вернуть sealed LLM-слой. Уже сгенерированный текст не сбрасывается."""
    store = getattr(order, "interpretive", None)
    if not isinstance(store, dict):
        return None
    layer = store.get("aspects")
    if not isinstance(layer, dict) or layer.get("status") != "ready":
        return None
    if str(layer.get("source") or "") != "llm":
        return None
    payload = layer.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("aspects"), list):
        return None
    return layer


def save_aspects_layer(order, document: dict[str, Any], result: dict[str, Any]) -> None:
    from core.services.report_jobs import save_interpretive_layer

    save_interpretive_layer(
        order,
        "aspects",
        {
            "cache_key": aspects_cache_key(document),
            "source": result.get("source") or "fallback",
            "status": "ready",
            "model": result.get("model") or "",
            "error": result.get("error") or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "payload": result["payload"],
        },
    )


def normalize_aspects_payload(raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict) and raw.get("source") == "fallback" and isinstance(raw.get("aspects"), list):
        return raw
    data = raw if isinstance(raw, dict) else {}
    incoming = data.get("aspects")
    if not isinstance(incoming, list) or not incoming:
        return fallback

    by_id = {
        str(row.get("aspect_id") or _aspect_id(row)): row
        for row in incoming
        if isinstance(row, dict)
    }
    by_pair = {}
    for row in incoming:
        if not isinstance(row, dict):
            continue
        pair = tuple(sorted((str(row.get("a") or ""), str(row.get("b") or "")))) + (
            str(row.get("aspect") or ""),
        )
        if pair[0] and pair[1] and pair[2]:
            by_pair[pair] = row

    accepted: list[dict[str, Any]] = []
    any_generated = False
    for base in fallback.get("aspects") or []:
        if not isinstance(base, dict):
            continue
        key = str(base.get("aspect_id") or "")
        pair = tuple(sorted((str(base.get("a") or ""), str(base.get("b") or "")))) + (
            str(base.get("aspect") or ""),
        )
        card = by_id.get(key) or by_pair.get(pair)
        if _generated_card_ok(card):
            accepted.append(_complete_generated_aspect(card, base))
            any_generated = True
        else:
            accepted.append(dict(base))
    if not any_generated:
        return fallback

    intro = data.get("intro") if isinstance(data.get("intro"), dict) else {}
    if _text_ok(intro.get("summary")):
        portrait = {
            "headline": str(intro.get("headline") or "").strip(),
            "summary": str(intro.get("summary") or "").strip(),
        }
    else:
        portrait = dict(fallback.get("intro") or {})
    return {
        "report_type": "natal_aspects",
        "source": "llm",
        "intro": portrait,
        "themes": [],
        "aspects": accepted,
    }


def _text_ok(value: Any) -> bool:
    return len(str(value or "").strip()) >= MIN_GENERATED_TEXT


def _generated_card_ok(card: Any) -> bool:
    return isinstance(card, dict) and _text_ok(card.get("summary"))


def _complete_generated_aspect(card: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    deep = card.get("deep_read")
    if not isinstance(deep, list):
        deep = [str(deep)] if deep else []
    questions = card.get("reflection_questions")
    if not isinstance(questions, list):
        questions = []
    return {
        "aspect_id": str(card.get("aspect_id") or base.get("aspect_id") or ""),
        "unit_key": str(base.get("unit_key") or ""),
        "source": "llm",
        "category": str(card.get("category") or base.get("category") or "mixed"),
        "aspect_label_ru": str(card.get("aspect_label_ru") or base.get("aspect_label_ru") or ""),
        "orb_deg": card.get("orb_deg", base.get("orb_deg")),
        "headline": str(card.get("headline") or "").strip(),
        "summary": str(card.get("summary") or "").strip(),
        "deep_read": [str(p).strip() for p in deep if str(p).strip()],
        "resource": str(card.get("resource") or "").strip(),
        "tension_or_blind_spot": str(card.get("tension_or_blind_spot") or "").strip(),
        "how_to_work": str(card.get("how_to_work") or "").strip(),
        "reflection_questions": [str(q).strip() for q in questions if str(q).strip()],
        "a": str(card.get("a") or base.get("a") or ""),
        "b": str(card.get("b") or base.get("b") or ""),
        "aspect": str(card.get("aspect") or base.get("aspect") or ""),
        "aspect_ru": str(card.get("aspect_ru") or base.get("aspect_ru") or ""),
        "a_name": str(card.get("a_name") or base.get("a_name") or ""),
        "b_name": str(card.get("b_name") or base.get("b_name") or ""),
        "priority_score": base.get("priority_score"),
        "astrological_basis": base.get("astrological_basis") or {},
    }


def _factual_aspects(document: dict[str, Any]) -> list[dict[str, Any]]:
    natal = (document.get("factual") or {}).get("natal") or {}
    rows = natal.get("aspects") or []
    return [row for row in rows if isinstance(row, dict) and row.get("a") and row.get("b")]


def _aspect_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or f"natal_{row.get('a')}_{row.get('aspect')}_{row.get('b')}")


def _card_from_row(row: dict[str, Any], document: dict[str, Any]) -> Optional[dict[str, Any]]:
    return build_aspect_card(load_aspects_fallback_library(), row, document)


def _aspects_llm_user(document: dict[str, Any]) -> dict[str, Any]:
    natal = (document.get("factual") or {}).get("natal") or {}
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    aspects = []
    for row in ranked_aspects(document):
        card = _card_from_row(row, document)
        if not card:
            continue
        aspects.append(
            {
                "id": card["aspect_id"],
                "category": card["category"],
                "planet_a": {
                    "key": card["a"],
                    "name_ru": card["a_name"],
                    "sign": (card.get("astrological_basis") or {}).get("sign_a"),
                    "house": (card.get("astrological_basis") or {}).get("house_a"),
                },
                "planet_b": {
                    "key": card["b"],
                    "name_ru": card["b_name"],
                    "sign": (card.get("astrological_basis") or {}).get("sign_b"),
                    "house": (card.get("astrological_basis") or {}).get("house_b"),
                },
                "aspect_type": card["aspect"],
                "aspect_type_ru": card["aspect_ru"],
                "orb_deg": card["orb_deg"],
                "priority_score": card["priority_score"],
            }
        )
    return {
        "language": "ru",
        "depth": "full",
        "has_birth_time": bool(natal.get("has_birth_time")),
        "reader": reader_voice(quiz),
        "user_context": {
            "goals": quiz.get("focus_labels") or [],
            "intent": quiz.get("intent_label") or "",
        },
        "aspects": aspects,
        "note": "Это natal-to-natal аспекты. Не интерпретируй как транзиты.",
    }
