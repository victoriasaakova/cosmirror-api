"""
Персонализация инсайта через LLM (Polza.ai / Groq): перепись шаблонов + оффер.

Без ключа / при ошибке — шаблоны + дефолтный оффер из фокуса квиза.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from core.services import llm_client

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

Задача: подготовить тексты онбординг-воронки после квиза:
1) переписать influences и cycles (кратко, лично);
2) два продающих экрана по двум фоновым циклам — как сервис поможет прожить этот фон;
3) экран «что отмечают пользователи» через неделю;
4) финальный оффер подписки.

Правила:
- Язык: русский.
- Тон: спокойный, взрослый; без прогнозов, гарантий и медицинских диагнозов.
- Без астро-жаргона; можно «длинные циклы», Солнце/Луна/Асцендент.
- Обращение на «ты». Имя — уместно один раз.
- Привяжи к фокусу, intent и жизненному этапу.
- influences/cycles: key НЕ МЕНЯЙ; text до ~280 символов.
- cycle_pitches: РОВНО 2 элемента по первым двум cycles (если один — второй с другим углом).
  title до 70 символов; text 2–3 предложения: фон + как Cosmirror поможет.
- outcomes: title до 80 символов; items — 4 фразы про результат через ~неделю.
- offer: title ТОЧНО «Стань ближе к своему истинному я»; text 1–2 предложения; cta до 40 символов; price ТОЧНО «777 ₽/мес».

Верни ТОЛЬКО JSON:
{
  "influences": [{"key": "...", "title": "...", "text": "..."}],
  "cycles": [{"key": "...", "title": "...", "text": "..."}],
  "cycle_pitches": [
    {"cycle_key": "...", "title": "...", "text": "..."},
    {"cycle_key": "...", "title": "...", "text": "..."}
  ],
  "outcomes": {"title": "...", "items": ["...", "..."]},
  "offer": {"title": "Стань ближе к своему истинному я", "text": "...", "cta": "...", "price": "777 ₽/мес"}
}
"""


def is_personalized(insight: Optional[dict[str, Any]]) -> bool:
    """Уже есть воронка онбординга — не дергаем LLM повторно."""
    if not isinstance(insight, dict):
        return False
    offer = insight.get("offer")
    if not isinstance(offer, dict):
        return False
    if not (str(offer.get("title") or "").strip() and str(offer.get("text") or "").strip()):
        return False
    pitches = insight.get("cycle_pitches")
    return isinstance(pitches, list) and len(pitches) >= 2


def personalize_insight(
    *,
    insight: dict[str, Any],
    natal: dict[str, Any],
    quiz: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Вернуть инсайт с offer.
    Если уже personalized — вернуть как есть.
    Если LLM недоступен — шаблоны + default offer.
    """
    if is_personalized(insight):
        return insight

    quiz = quiz or {}
    base_insight = copy.deepcopy(insight) if insight else {}
    offer = default_offer(quiz)

    if not llm_client.is_configured():
        return _with_templates(base_insight, offer, quiz)

    try:
        rewritten = _call_llm(base_insight, natal, quiz)
    except Exception:
        logger.warning("Insight personalization failed; using templates", exc_info=False)
        return _with_templates(base_insight, offer, quiz)

    provider = llm_client.active_provider() or "llm"
    return _merge_llm_result(base_insight, rewritten, offer_fallback=offer, quiz=quiz, source=provider)


def default_offer(quiz: dict[str, Any]) -> dict[str, str]:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    primary = focus_keys[0] if focus_keys else "path"
    focus_label = FOCUS_LABELS.get(primary, FOCUS_LABELS["path"])
    intent_label = INTENT_LABELS.get(str(quiz.get("intent") or ""), INTENT_LABELS["other"])
    name = (quiz.get("name") or "").strip()
    who = f"{name}, " if name else ""
    return {
        "title": "Стань ближе к своему истинному я",
        "text": (
            f"{who}персональный разбор поможет увидеть, как фон циклов пересекается с темой «{focus_label}» — "
            f"чтобы {intent_label} без общих гороскопов."
        ),
        "cta": "Оформить подписку",
        "price": "777 ₽/мес",
    }


def default_outcomes(quiz: dict[str, Any]) -> dict[str, Any]:
    name = (quiz.get("name") or "").strip()
    title = f"{name}, что меняется уже через неделю" if name else "Что меняется уже через неделю"
    return {
        "title": title,
        "items": [
            "Понимаешь, что даёт энергию, а что её забирает",
            "Видишь свои сильные стороны и как их масштабировать",
            "Замечаешь повторяющиеся сценарии до того, как они снова уведут в круг",
            "Легче выбирать решения, которые ближе к твоему ритму",
        ],
    }


def default_cycle_pitches(cycles: list[dict[str, Any]], quiz: dict[str, Any]) -> list[dict[str, str]]:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    focus_label = FOCUS_LABELS.get(focus_keys[0], "жизни") if focus_keys else "жизни"

    def pitch_for(cycle: dict[str, Any], idx: int) -> dict[str, str]:
        key = str(cycle.get("key") or f"cycle_{idx}")
        cycle_title = str(cycle.get("title") or "Фон цикла")
        cycle_text = str(cycle.get("text") or "")
        return {
            "cycle_key": key,
            "title": f"Как пройти «{cycle_title}» с опорой",
            "text": (
                f"Сейчас в фоне: {cycle_text} "
                f"Cosmirror поможет связать это с твоей картой и фокусом «{focus_label}» — "
                "чтобы не тонуть в ощущениях, а видеть, где тебе нужна опора и где — шаг."
            )[:480],
        }

    if not cycles:
        generic = {
            "cycle_key": "cycle_generic",
            "title": "Как Cosmirror поможет в этом периоде",
            "text": (
                "Мы соберём персональный разбор: что сейчас в фоне, "
                "как это пересекается с твоей картой и куда направить внимание на этой неделе."
            ),
        }
        return [generic, {**generic, "title": "Твой ритм и опора в переменах"}]

    first = pitch_for(cycles[0], 0)
    second = pitch_for(cycles[1] if len(cycles) > 1 else cycles[0], 1)
    return [first, second]


def _with_templates(insight: dict[str, Any], offer: dict[str, str], quiz: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(insight) if insight else {}
    out.setdefault("tone", "pattern_psych")
    cycles = out.get("cycles") or []
    out["cycle_pitches"] = default_cycle_pitches(cycles, quiz)
    out["outcomes"] = default_outcomes(quiz)
    out["offer"] = offer
    out["source"] = "templates"
    return out


def _call_llm(
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
    return llm_client.chat_json(system=SYSTEM_PROMPT, user=user)


def _merge_llm_result(
    base_insight: dict[str, Any],
    rewritten: dict[str, Any],
    *,
    offer_fallback: dict[str, str],
    quiz: dict[str, Any],
    source: str = "llm",
) -> dict[str, Any]:
    out = copy.deepcopy(base_insight)
    for section in ("influences", "cycles"):
        original = out.get(section) or []
        llm_items = rewritten.get(section)
        if not isinstance(llm_items, list):
            continue
        out[section] = _merge_section(original, llm_items)

    cycles = out.get("cycles") or []
    pitches = rewritten.get("cycle_pitches")
    if isinstance(pitches, list) and len(pitches) >= 2:
        merged_pitches: list[dict[str, str]] = []
        for idx, item in enumerate(pitches[:2]):
            if not isinstance(item, dict):
                continue
            cycle_key = str(item.get("cycle_key") or (cycles[idx].get("key") if idx < len(cycles) else f"cycle_{idx}"))
            title = str(item.get("title") or "").strip()
            text = str(item.get("text") or "").strip()
            if title and text:
                merged_pitches.append({"cycle_key": cycle_key, "title": title[:120], "text": text[:500]})
        if len(merged_pitches) >= 2:
            out["cycle_pitches"] = merged_pitches
    if not out.get("cycle_pitches"):
        out["cycle_pitches"] = default_cycle_pitches(cycles, quiz)

    outcomes = rewritten.get("outcomes")
    if isinstance(outcomes, dict):
        o_title = str(outcomes.get("title") or "").strip()
        items = outcomes.get("items")
        if o_title and isinstance(items, list):
            clean_items = [str(i).strip() for i in items if str(i).strip()][:6]
            if clean_items:
                out["outcomes"] = {"title": o_title[:120], "items": clean_items}
    if not out.get("outcomes"):
        out["outcomes"] = default_outcomes(quiz)

    offer = rewritten.get("offer")
    if isinstance(offer, dict):
        title = str(offer.get("title") or offer_fallback.get("title") or "").strip()
        text = str(offer.get("text") or "").strip()
        cta = str(offer.get("cta") or "").strip()
        price = str(offer.get("price") or offer_fallback.get("price") or "777 ₽/мес").strip()
        if title and text:
            out["offer"] = {
                "title": title[:120],
                "text": text[:500],
                "cta": (cta or offer_fallback.get("cta") or "Оформить подписку")[:60],
                "price": price[:40],
            }
        else:
            out["offer"] = offer_fallback
    else:
        out["offer"] = offer_fallback

    out["tone"] = "pattern_psych_llm"
    out["source"] = source
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
