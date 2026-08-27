"""
Вкладка «Твоя карта»: синтез по скиллу paid_report_natal.

GET отдаёт детерминированный fallback из YAML-библиотеки.
LLM вызывается только из generate_natal_interpretation().
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
    PROMPT_PAID_REPORT_NATAL,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import grammatical_gender, reader_voice
from core.services.report_natal_fallback import fallback_natal_interpretation
from core.services.report_types import SECTION_NATAL

logger = logging.getLogger(__name__)

MIN_GENERATED_TEXT = 40

NATAL_USER_CONTRACT = """\
Собери вкладку «Твоя карта» по уже посчитанной карте.

Шапка отчёта уже показывает сжатое Солнце / Луну / Асцендент.
Здесь — подробный слой: портрет, развёрнутая большая тройка, затем функции из скилла.
Не пиши транзиты, окна, «что будет», квиз онбординга.

Верни ТОЛЬКО JSON:

{
  "report_type": "natal",
  "core_portrait": {
    "headline": "человеческая тема, не «Солнце в …», до 90 символов",
    "summary": "3–5 предложений синтеза. Опыт сначала. Есть внутреннее трение."
  },
  "big_three": {
    "sun": {
      "headline": "человеческая тема",
      "body": "4–7 предложений: проявление → механизм → защитная функция → цена. На «ты».",
      "why": "Солнце в <знак> · дом n  (дом только если время надёжно)",
      "question": "один проверяемый вопрос"
    },
    "moon": { "headline": "", "body": "", "why": "", "question": "" },
    "ascendant": { "headline": "", "body": "", "why": "", "question": "" }
  },
  "sections": [
    {
      "id": "mind | relationships | action | work | inner_conflict | resource | flexibility",
      "title": "Как работает твой ум | Близость и отношения | Воля, энергия и действие | Работа, реализация и вклад | Главные внутренние противоречия | На что уже можно опираться | Где больше гибкости может дать больше свободы",
      "headline": "человеческая тема",
      "summary": "2–4 предложения",
      "deep_read": ["абзац механизма", "абзац функции и цены", "абзац более гибкого ответа"],
      "why": "точные факты карты через « · »",
      "question": "один вопрос или пустая строка"
    }
  ],
  "reflection_questions": ["3–5 вопросов, с которыми стоит пожить"],
  "limitations": ["ограничения данных, если есть"]
}

Правила:
- Только факты из JSON пользователя. Не выдумывай аспекты, дома, углы.
- Если has_birth_time=false: не интерпретируй Асцендент и дома; в ascendant.body честно скажи, что без времени не считаем.
- Язык: русский, «ты». Без кальки «тебе может быть важно» в начале каждого абзаца.
- Род бери ТОЛЬКО из reader.grammatical_gender: feminine — женский (внимательной, надёжной, готова); masculine — мужской; unspecified — нейтрально, без мужского по умолчанию. Не выводи род из карты, имени или знака.
- Не начинай абзац с «Меркурий в …». Сначала жизнь, в why — астрология.
- Не диагнозы, не судьба, не события.
"""


def natal_cache_key(document: dict[str, Any]) -> str:
    factual = (document.get("factual") or {}).get("natal") or {}
    rows = []
    for point in factual.get("points") or []:
        if not isinstance(point, dict):
            continue
        rows.append(
            (
                point.get("key"),
                point.get("sign"),
                point.get("house"),
                round(float(point.get("degree") or 0), 2),
            )
        )
    rows.sort()
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    raw = json.dumps(
        {
            "has_time": bool(factual.get("has_birth_time")),
            "points": rows,
            "gender": grammatical_gender(quiz),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def apply_natal_to_document(
    document: dict[str, Any],
    payload: dict[str, Any],
    *,
    source: str,
    model: str = "",
    sealed: bool = False,
) -> dict[str, Any]:
    if sealed and source == "llm" and isinstance(payload, dict) and payload.get("core_portrait"):
        # Atomic GET overlay: never field-merge sealed LLM with live fallback.
        payload = {**payload, "source": "llm", "report_type": payload.get("report_type") or "natal"}
    else:
        payload = normalize_natal_payload(payload, fallback_natal_interpretation(document))
        if source == "fallback":
            payload["source"] = "fallback"
    interpretive = document.setdefault("interpretive", {})
    interpretive["status"] = "llm" if source == "llm" else "fallback"
    interpretive["natal"] = {
        "source": source,
        "status": "ready",
        "model": model,
        "can_generate": llm_client.is_configured(),
        "payload": payload,
    }
    sections = document.setdefault("sections", {})
    natal_section = sections.get(SECTION_NATAL) or {
        "id": SECTION_NATAL,
        "title": "Твоя карта",
        "layer": "interpretive",
        "blocks": [],
    }
    natal_section["layer"] = "interpretive"
    natal_section["blocks"] = natal_blocks_from_payload(payload)
    natal_section["blocks"].extend(_house_blocks(document))
    sections[SECTION_NATAL] = natal_section
    return document


def _house_blocks(document: dict[str, Any]) -> list[dict[str, str]]:
    houses = ((document.get("factual") or {}).get("natal") or {}).get("houses") or []
    out: list[dict[str, str]] = []
    for house in houses:
        if not isinstance(house, dict):
            continue
        who = ", ".join(house.get("occupants") or [])
        who_text = f" Здесь в карте: {who}." if who else ""
        out.append(
            {
                "title": f"{house.get('house')}-й дом · {house.get('sign_ru')}",
                "text": f"{house.get('theme') or ''}{who_text}",
            }
        )
    return out


def natal_blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    portrait = payload.get("core_portrait") or {}
    if portrait.get("summary"):
        blocks.append(
            {
                "title": str(portrait.get("headline") or "Портрет"),
                "text": str(portrait.get("summary") or ""),
            }
        )
    placements = payload.get("placements") if isinstance(payload.get("placements"), list) else []
    if placements:
        for card in placements:
            if not isinstance(card, dict):
                continue
            parts = [str(item).strip() for item in (card.get("paragraphs") or []) if str(item).strip()]
            if not parts:
                parts = [str(card.get("summary") or "").strip()]
                parts.extend(
                    str(item).strip() for item in (card.get("deep_read") or []) if str(item).strip()
                )
            why = str(card.get("astro_explanation") or "").strip()
            if why:
                parts.append(why)
            question = str(card.get("reflection_question") or "").strip()
            if question:
                parts.append(question)
            text = " ".join(part for part in parts if part)
            if not text:
                continue
            title = " · ".join(
                part
                for part in (
                    str(card.get("body") or "").strip(),
                    str(card.get("headline") or "").strip(),
                )
                if part
            )
            blocks.append({"title": title or "Карта", "text": text})
        for theme in (portrait.get("themes") or []) + list(payload.get("repeating_themes") or []):
            if not isinstance(theme, dict):
                continue
            narrative = str(theme.get("narrative") or "").strip()
            if narrative:
                blocks.append(
                    {
                        "title": str(theme.get("headline") or "Тема"),
                        "text": narrative,
                    }
                )
        for question in payload.get("reflection_questions") or []:
            if str(question).strip():
                blocks.append({"title": "Вопрос", "text": str(question).strip()})
        return blocks
    labels = {"sun": "Солнце", "moon": "Луна", "ascendant": "Асцендент"}
    for key, label in labels.items():
        card = (payload.get("big_three") or {}).get(key) or {}
        text = str(card.get("body") or "").strip()
        if not text:
            continue
        why = str(card.get("why") or "").strip()
        question = str(card.get("question") or "").strip()
        body = text
        if why:
            body += f" Почему мы это видим: {why}."
        if question:
            body += f" {question}"
        blocks.append({"title": str(card.get("headline") or label), "text": body})
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        parts = [str(section.get("summary") or "").strip()]
        parts.extend(str(p).strip() for p in (section.get("deep_read") or []) if str(p).strip())
        why = str(section.get("why") or "").strip()
        if why:
            parts.append(f"Почему мы это видим: {why}.")
        question = str(section.get("question") or "").strip()
        if question:
            parts.append(question)
        text = " ".join(part for part in parts if part)
        if not text:
            continue
        blocks.append(
            {
                "title": str(section.get("headline") or section.get("title") or ""),
                "text": text,
            }
        )
    for question in payload.get("reflection_questions") or []:
        if str(question).strip():
            blocks.append({"title": "Вопрос", "text": str(question).strip()})
    return blocks


def generate_natal_interpretation(document: dict[str, Any]) -> dict[str, Any]:
    """Вызов Polza. При ошибке — фолбэк того же shape."""
    fallback = fallback_natal_interpretation(document)
    if not llm_client.is_configured():
        return {"ok": False, "source": "fallback", "payload": fallback, "error": "llm_not_configured"}

    system = (
        "Перед работой держи Cosmirror editorial: гипотеза, не приговор; опыт сначала; "
        "без прогнозов, диагнозов и судьбы. Обращение на «ты». Русский как у носителя, "
        "без канцелярита и без кальки «тебе может быть важно» в каждом абзаце. "
        "Грамматический род — только из reader.grammatical_gender.\n\n"
        + load_prompt(PROMPT_PAID_REPORT_NATAL).body.strip()
        + "\n\n"
        + NATAL_USER_CONTRACT
    )
    user = json.dumps(_natal_llm_user(document), ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=PROMPT_PAID_REPORT_NATAL,
            temperature=0.55,
            max_tokens=8000,
        )
    except llm_client.LLMError as exc:
        logger.warning("Natal LLM failed: %s", exc)
        return {"ok": False, "source": "fallback", "payload": fallback, "error": str(exc)}

    payload = normalize_natal_payload(raw, fallback)
    if payload.get("source") != "llm":
        return {
            "ok": False,
            "source": "fallback",
            "payload": fallback,
            "error": "invalid_generated_natal",
        }
    model = resolve_model(PROMPT_PAID_REPORT_NATAL)
    return {"ok": True, "source": "llm", "payload": payload, "error": "", "model": model}


def cached_natal_layer(order, document: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Вернуть sealed LLM-слой. cache_key не инвалидирует уже сгенерированный текст."""
    store = getattr(order, "interpretive", None)
    if not isinstance(store, dict):
        return None
    natal = store.get("natal")
    if not isinstance(natal, dict) or natal.get("status") != "ready":
        return None
    if str(natal.get("source") or "") != "llm":
        return None
    payload = natal.get("payload")
    if not isinstance(payload, dict) or not payload.get("core_portrait"):
        return None
    return natal


def save_natal_layer(order, document: dict[str, Any], result: dict[str, Any]) -> None:
    from core.services.report_jobs import save_interpretive_layer

    save_interpretive_layer(
        order,
        "natal",
        {
            "cache_key": natal_cache_key(document),
            "source": result.get("source") or "fallback",
            "status": "ready",
            "model": result.get("model") or "",
            "error": result.get("error") or "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "payload": result["payload"],
        },
    )


def normalize_natal_payload(raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict) and raw.get("source") == "fallback" and raw.get("placements"):
        return raw
    data = raw if isinstance(raw, dict) else {}
    portrait = data.get("core_portrait") if isinstance(data.get("core_portrait"), dict) else {}
    big = data.get("big_three") if isinstance(data.get("big_three"), dict) else {}
    sun = big.get("sun") if isinstance(big.get("sun"), dict) else {}
    if not _text_ok(portrait.get("summary")) or not _text_ok(sun.get("body")):
        return fallback

    out: dict[str, Any] = {
        "report_type": "natal",
        "source": "llm",
        "core_portrait": {
            "headline": str(portrait.get("headline") or "").strip(),
            "summary": str(portrait.get("summary") or "").strip(),
        },
        "big_three": {},
        "sections": list(fallback.get("sections") or []),
        "reflection_questions": list(fallback.get("reflection_questions") or []),
        "limitations": list(fallback.get("limitations") or []),
    }
    fallback_big = fallback.get("big_three") if isinstance(fallback.get("big_three"), dict) else {}
    for key in ("sun", "moon", "ascendant"):
        card = big.get(key)
        if _card_ok(card):
            out["big_three"][key] = _complete_generated_card(card)
        else:
            out["big_three"][key] = dict(fallback_big.get(key) or {})

    if isinstance(data.get("sections"), list) and data["sections"]:
        cleaned = []
        for row in data["sections"]:
            if not isinstance(row, dict) or not _text_ok(row.get("summary") or row.get("headline")):
                continue
            deep = row.get("deep_read")
            if not isinstance(deep, list):
                deep = [str(deep)] if deep else []
            cleaned.append(
                {
                    "id": str(row.get("id") or ""),
                    "title": str(row.get("title") or ""),
                    "headline": str(row.get("headline") or row.get("title") or ""),
                    "summary": str(row.get("summary") or ""),
                    "deep_read": [str(p).strip() for p in deep if str(p).strip()],
                    "why": str(row.get("why") or ""),
                    "question": str(row.get("question") or ""),
                }
            )
        if cleaned:
            out["sections"] = cleaned
    if isinstance(data.get("reflection_questions"), list) and data["reflection_questions"]:
        questions = [str(q).strip() for q in data["reflection_questions"] if str(q).strip()]
        if questions:
            out["reflection_questions"] = questions
    if isinstance(data.get("limitations"), list):
        out["limitations"] = [str(x).strip() for x in data["limitations"] if str(x).strip()]
    return out


def _text_ok(value: Any) -> bool:
    return len(str(value or "").strip()) >= MIN_GENERATED_TEXT


def _card_ok(card: Any) -> bool:
    return isinstance(card, dict) and _text_ok(card.get("body"))


def _complete_generated_card(card: dict[str, Any]) -> dict[str, str]:
    return {
        "headline": str(card.get("headline") or "").strip(),
        "body": str(card.get("body") or "").strip(),
        "why": str(card.get("why") or "").strip(),
        "question": str(card.get("question") or "").strip(),
    }


def _natal_llm_user(document: dict[str, Any]) -> dict[str, Any]:
    factual = (document.get("factual") or {}).get("natal") or {}
    points = []
    for row in factual.get("points") or []:
        if not isinstance(row, dict):
            continue
        points.append(
            {
                "key": row.get("key"),
                "name": row.get("name"),
                "sign": row.get("sign"),
                "sign_ru": row.get("sign_ru"),
                "house": row.get("house"),
                "degree": row.get("degree"),
                "retrograde": row.get("retrograde"),
            }
        )
    aspects = []
    for row in (factual.get("aspects") or [])[:16]:
        if not isinstance(row, dict):
            continue
        aspects.append(
            {
                "a": row.get("a"),
                "b": row.get("b"),
                "a_name": row.get("a_name"),
                "b_name": row.get("b_name"),
                "aspect": row.get("aspect"),
                "aspect_ru": row.get("aspect_ru"),
                "kind": row.get("kind"),
                "orb": row.get("orb"),
            }
        )
    houses = []
    for row in factual.get("houses") or []:
        if not isinstance(row, dict):
            continue
        houses.append(
            {
                "house": row.get("house"),
                "sign": row.get("sign"),
                "sign_ru": row.get("sign_ru"),
                "occupants": row.get("occupants") or [],
            }
        )
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    return {
        "task": "generate_paid_report_natal",
        "reader": reader_voice(quiz),
        "has_birth_time": bool(factual.get("has_birth_time")),
        "house_system": factual.get("house_system"),
        "points": points,
        "natal_aspects": aspects,
        "houses": houses if factual.get("has_birth_time") else [],
    }

