"""
Персонализация инсайта через Groq: перепись шаблонных текстов + оффер.

Без ключа / при ошибке — шаблоны + дефолтный оффер из фокуса квиза.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from core.services import groq_client

logger = logging.getLogger(__name__)

FOCUS_LABELS = {
    "love": "отношения и любовь",
    "money": "деньги и работа",
    "energy": "энергия, ресурсы и восстановление",
    "confidence": "самооценка и уверенность",
    "path": "самореализация и поиск своего пути",
    "other": "личное",
}

INTENT_LABELS = {
    "future": "узнать, что ждёт в ближайшем будущем",
    "potential": "понять себя и свой потенциал",
    "uncertainty": "найти выход из неопределённости",
    "relationships": "наладить отношения",
    "patterns": "понять закономерности своей жизни",
    "life-stage": "разобраться в текущем жизненном этапе",
    "other": "разобраться в себе",
}

LIFE_STAGE_LABELS = {
    "stable": "всё довольно стабильно",
    "one-sphere": "меняется одна важная сфера",
    "many-spheres": "перестройки в нескольких сферах",
    "ready-to-change": "пора что-то менять",
    "unclear": "пока неясно, что происходит",
}

SYSTEM_PROMPT = """\
Ты редактор психологических текстов для продукта Cosmirror (астро-психология без эзотерического пафоса).

Задача: на основе шаблонных блоков и профиля пользователя переписать тексты так,
чтобы они звучали лично и по делу, и собрать короткий персональный оффер.

Правила:
- Язык: русский.
- Тон: спокойный, взрослый, как у хорошего психолога; без «ты избранная», без прогнозов будущего, без гарантий, без медицинских/терапевтических диагнозов.
- Не используй астро-жаргон вроде «транзит Сатурна квадратит» — можно мягко упоминать Солнце/Луну/Асцендент и «длинные циклы» только если это уже есть в шаблоне.
- Обращение на «ты». Если есть имя — можно один раз использовать.
- Сохрани смысл каждого блока, но привяжи к фокусу / intent / жизненному этапу пользователя.
- Длина text каждого блока: 1–3 предложения, до ~280 символов.
- title можно слегка уточнить, но key каждого блока НЕ МЕНЯЙ.
- Не добавляй новые блоки в base / influences / cycles — только перепиши существующие.
- offer: персональное предложение продолжить разбор (ранний доступ), завязанное на фокус и intent.
  title до 60 символов, text 1–2 предложения, cta — короткая кнопка (до 40 символов).

Верни ТОЛЬКО JSON-объект такой формы:
{
  "base": [{"key": "...", "title": "...", "text": "..."}],
  "influences": [{"key": "...", "title": "...", "text": "..."}],
  "cycles": [{"key": "...", "title": "...", "text": "..."}],
  "offer": {"title": "...", "text": "...", "cta": "..."}
}
"""


def is_personalized(insight: Optional[dict[str, Any]]) -> bool:
    """Уже есть оффер — не дергаем LLM / не пересобираем fallback."""
    if not isinstance(insight, dict):
        return False
    offer = insight.get("offer")
    if not isinstance(offer, dict):
        return False
    return bool(str(offer.get("title") or "").strip() and str(offer.get("text") or "").strip())


def personalize_insight(
    *,
    insight: dict[str, Any],
    natal: dict[str, Any],
    quiz: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Вернуть инсайт с offer.
    Если уже personalized — вернуть как есть.
    Если Groq недоступен — шаблоны + default offer.
    """
    if is_personalized(insight):
        return insight

    quiz = quiz or {}
    base_insight = copy.deepcopy(insight) if insight else {}
    offer = default_offer(quiz)

    if not groq_client.is_configured():
        return _with_templates(base_insight, offer)

    try:
        rewritten = _call_groq(base_insight, natal, quiz)
    except Exception:
        logger.warning("Insight personalization failed; using templates", exc_info=False)
        return _with_templates(base_insight, offer)

    return _merge_llm_result(base_insight, rewritten, offer_fallback=offer)


def default_offer(quiz: dict[str, Any]) -> dict[str, str]:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    primary = focus_keys[0] if focus_keys else "path"
    focus_label = FOCUS_LABELS.get(primary, FOCUS_LABELS["path"])
    intent = str(quiz.get("intent") or "")
    intent_label = INTENT_LABELS.get(intent, INTENT_LABELS["other"])
    name = (quiz.get("name") or "").strip()

    title = f"{name}, разбор под твой фокус" if name else "Разбор под твой фокус"
    return {
        "title": title,
        "text": (
            f"Соберу персональный портрет вокруг темы «{focus_label}» — "
            f"чтобы помочь {intent_label}, без общих гороскопов."
        ),
        "cta": "Получить полный разбор",
    }


def _with_templates(insight: dict[str, Any], offer: dict[str, str]) -> dict[str, Any]:
    out = copy.deepcopy(insight) if insight else {}
    out.setdefault("tone", "pattern_psych")
    out["offer"] = offer
    out["source"] = "templates"
    return out


def _call_groq(
    insight: dict[str, Any],
    natal: dict[str, Any],
    quiz: dict[str, Any],
) -> dict[str, Any]:
    natal_slice = _natal_slice(natal)
    quiz_slice = _quiz_slice(quiz)
    payload = {
        "quiz": quiz_slice,
        "natal": natal_slice,
        "blocks": {
            "base": insight.get("base") or [],
            "influences": insight.get("influences") or [],
            "cycles": insight.get("cycles") or [],
        },
        "disclaimer": insight.get("disclaimer") or "",
    }
    user = (
        "Перепиши блоки и собери оффер по этим данным.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return groq_client.chat_json(system=SYSTEM_PROMPT, user=user)


def _merge_llm_result(
    base_insight: dict[str, Any],
    rewritten: dict[str, Any],
    *,
    offer_fallback: dict[str, str],
) -> dict[str, Any]:
    out = copy.deepcopy(base_insight)
    for section in ("base", "influences", "cycles"):
        original = out.get(section) or []
        llm_items = rewritten.get(section)
        if not isinstance(llm_items, list):
            continue
        out[section] = _merge_section(original, llm_items)

    offer = rewritten.get("offer")
    if isinstance(offer, dict):
        title = str(offer.get("title") or "").strip()
        text = str(offer.get("text") or "").strip()
        cta = str(offer.get("cta") or "").strip()
        if title and text:
            out["offer"] = {
                "title": title[:120],
                "text": text[:500],
                "cta": (cta or offer_fallback.get("cta") or "Получить полный разбор")[:60],
            }
        else:
            out["offer"] = offer_fallback
    else:
        out["offer"] = offer_fallback

    out["tone"] = "pattern_psych_llm"
    out["source"] = "groq"
    if not out.get("disclaimer"):
        out["disclaimer"] = base_insight.get("disclaimer") or (
            "Это не прогноз будущего и не замена терапии. "
            "Это способ заметить, какие внутренние темы могут быть громче на фоне текущих циклов."
        )
    return out


def _merge_section(
    original: list[dict[str, Any]],
    llm_items: list[Any],
) -> list[dict[str, str]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in llm_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        by_key[key] = item

    merged: list[dict[str, str]] = []
    for src in original:
        key = str(src.get("key") or "")
        llm = by_key.get(key)
        if llm:
            title = str(llm.get("title") or src.get("title") or "").strip()
            text = str(llm.get("text") or src.get("text") or "").strip()
            merged.append(
                {
                    "key": key,
                    "title": title or str(src.get("title") or ""),
                    "text": text or str(src.get("text") or ""),
                }
            )
        else:
            merged.append(
                {
                    "key": key,
                    "title": str(src.get("title") or ""),
                    "text": str(src.get("text") or ""),
                }
            )
    return merged


def _natal_slice(natal: dict[str, Any]) -> dict[str, Any]:
    planets = natal.get("planets") or {}
    sun = planets.get("sun") or {}
    moon = planets.get("moon") or {}
    asc = natal.get("ascendant") or {}
    return {
        "has_birth_time": bool(natal.get("has_birth_time")),
        "sun": {"sign": sun.get("sign"), "sign_ru": sun.get("sign_ru")},
        "moon": {"sign": moon.get("sign"), "sign_ru": moon.get("sign_ru")},
        "ascendant": {"sign": asc.get("sign"), "sign_ru": asc.get("sign_ru")} if asc else None,
    }


def _quiz_slice(quiz: dict[str, Any]) -> dict[str, Any]:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    intent = str(quiz.get("intent") or "")
    life_stage = str(quiz.get("life_stage") or quiz.get("lifeStage") or "")
    return {
        "name": (quiz.get("name") or "").strip(),
        "gender": quiz.get("gender") or "",
        "age": quiz.get("age") or "",
        "life_stage": life_stage,
        "life_stage_label": LIFE_STAGE_LABELS.get(life_stage, ""),
        "focus": focus_keys,
        "focus_labels": [FOCUS_LABELS.get(f, f) for f in focus_keys],
        "intent": intent,
        "intent_label": INTENT_LABELS.get(intent, ""),
        "chart_knowledge": quiz.get("chart_knowledge") or quiz.get("chartKnowledge") or "",
        "astrology_trigger": quiz.get("astrology_trigger")
        or quiz.get("astrologyTrigger")
        or "",
    }
