"""
Персонализация инсайта через LLM (Polza.ai / Groq): перепись шаблонов + оффер.

Без ключа / при ошибке — шаблоны + дефолтный оффер из фокуса квиза.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from core.services import editorial, llm_client

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

# Связки для составного заголовка (после имени, перед рекомендацией).
# Выбирай одну; она должна грамматически вести к продолжению после «что».
OPENING_BRIDGES = [
    "сейчас подсвечивается, что",
    "сейчас видно, что",
    "сейчас пространство показывает, что",
    "сейчас тебе подсвечивается, что",
    "сейчас особенно заметно, что",
    "сейчас на фоне циклов видно, что",
    "сейчас карта подсказывает, что",
]

SYSTEM_PROMPT = f"""\
Ты редактор психологических текстов для продукта Cosmirror (астро-психология без эзотерического пафоса).

Задача: подготовить тексты онбординг-воронки после квиза:
1) первый экран разбора: opening + body;
2) переписать influences и cycles (кратко, лично);
3) два продающих экрана по двум фоновым циклам;
4) экран «что отмечают пользователи» через неделю;
5) финальный оффер подписки.

Правила:
- Язык: русский.
- Тон: спокойный, взрослый; без прогнозов, гарантий и медицинских диагнозов.
- Без астро-жаргона; можно «длинные циклы», Солнце/Луна/Асцендент.
- Обращение на «ты». Имя в opening/body НЕ пиши — его покажут отдельно.

Первый экран (opening + body):
- opening.bridge: выбери РОВНО одну фразу из списка (дословно):
{json.dumps(OPENING_BRIDGES, ensure_ascii=False)}
- opening.insight: продолжение предложения после «что» — главная рекомендация из разбора.
  Бери смысл из title первого influence (переформулируй как клаузу, без заглавной буквы).
  Пример: title «Тяга выйти из тесной роли» → insight «пора выйти из тесной роли».
  До 90 символов. Должно читаться как: «Имя, {{bridge}} {{insight}}».
- body: один абзац, 4–6 предложений, до ~700 символов.
  Объедини контекст квиза (жизненный этап, фокус, цель) с текстом influences в единый персональный разбор.
  Логика: чтобы решить цель из квиза — даём наблюдение и мягкую рекомендацию из анализа.
  ЗАПРЕЩЕНО: перечислять ответы квиза списком; копировать focus_labels / intent_label / life_stage_label дословно;
  конструкции «сейчас: …», «в фокусе — …», «цель: …». Пиши как живой рассказ, не дублируй opening.insight.

Остальное:
- influences/cycles: key НЕ МЕНЯЙ; title до 60 символов; text до ~280 символов.
- cycle_pitches: РОВНО 2 элемента по первым двум cycles.
  title до 70 символов; text 2–3 предложения: фон + как Cosmirror поможет.
- outcomes: title до 80 символов; items — 4 фразы про результат через ~неделю.
- offer: title ТОЧНО «Стань ближе к своему истинному я»; text 1–2 предложения; cta до 40 символов; price ТОЧНО «777 ₽/мес».

Верни ТОЛЬКО JSON:
{{
  "opening": {{"bridge": "сейчас пространство показывает, что", "insight": "пора выйти из тесной роли"}},
  "body": "Один связный абзац разбора...",
  "influences": [{{"key": "...", "title": "...", "text": "..."}}],
  "cycles": [{{"key": "...", "title": "...", "text": "..."}}],
  "cycle_pitches": [
    {{"cycle_key": "...", "title": "...", "text": "..."}},
    {{"cycle_key": "...", "title": "...", "text": "..."}}
  ],
  "outcomes": {{"title": "...", "items": ["...", "..."]}},
  "offer": {{"title": "Стань ближе к своему истинному я", "text": "...", "cta": "...", "price": "777 ₽/мес"}}
}}
"""


def _has_funnel_structure(insight: Optional[dict[str, Any]]) -> bool:
    """Есть opening + body + pitches + offer — структура воронки собрана."""
    if not isinstance(insight, dict):
        return False
    offer = insight.get("offer")
    if not isinstance(offer, dict):
        return False
    if not (str(offer.get("title") or "").strip() and str(offer.get("text") or "").strip()):
        return False
    pitches = insight.get("cycle_pitches")
    if not (isinstance(pitches, list) and len(pitches) >= 2):
        return False
    opening = insight.get("opening")
    body = str(insight.get("body") or "").strip()
    if not isinstance(opening, dict):
        return False
    bridge = str(opening.get("bridge") or "").strip()
    clause = str(opening.get("insight") or "").strip()
    return bool(bridge and clause and len(body) >= 60)


def is_personalized(insight: Optional[dict[str, Any]]) -> bool:
    """
    Готовый инсайт: структура воронки есть.
    Для LLM-источников дополнительно требуется editorial_passed
    (второй проход через Cosmirror Editorial Writing System).
    """
    if not _has_funnel_structure(insight):
        return False
    source = str((insight or {}).get("source") or "")
    if source in ("", "templates"):
        return True
    return bool((insight or {}).get("editorial_passed"))


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
    LLM-тексты дополнительно проходят через editorial.py (Editorial Writing System).
    """
    if is_personalized(insight):
        return insight

    quiz = quiz or {}
    base_insight = copy.deepcopy(insight) if insight else {}
    offer = default_offer(quiz)

    # Черновик уже есть (например после генерации без editorial) — только редактура.
    if _has_funnel_structure(base_insight) and not base_insight.get("editorial_passed"):
        source = str(base_insight.get("source") or "")
        if source and source != "templates":
            return _apply_editorial(base_insight, natal=natal, quiz=quiz)

    if not llm_client.is_configured():
        return _with_templates(base_insight, offer, quiz)

    try:
        rewritten = _call_llm(base_insight, natal, quiz)
    except Exception:
        logger.warning("Insight personalization failed; using templates", exc_info=False)
        return _with_templates(base_insight, offer, quiz)

    provider = llm_client.active_provider() or "llm"
    merged = _merge_llm_result(
        base_insight, rewritten, offer_fallback=offer, quiz=quiz, source=provider
    )
    return _apply_editorial(merged, natal=natal, quiz=quiz)


def _apply_editorial(
    insight: dict[str, Any],
    *,
    natal: dict[str, Any],
    quiz: dict[str, Any],
) -> dict[str, Any]:
    """Второй проход: редактура всех user-facing LLM-текстов."""
    if insight.get("editorial_passed"):
        return insight
    if str(insight.get("source") or "") == "templates":
        return insight

    context = {
        "quiz": _quiz_slice(quiz),
        "natal": _natal_slice(natal),
    }
    edited = editorial.edit_user_facing_texts(
        draft=insight,
        content_type="onboarding_insight",
        context=context,
    )
    if edited.get("editorial_passed"):
        source = str(edited.get("source") or "llm")
        if "+editorial" not in source:
            edited["source"] = f"{source}+editorial"
    return edited


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


def _normalize_opening_bridge(bridge: str) -> str:
    raw = bridge.strip().lower().rstrip(".")
    for candidate in OPENING_BRIDGES:
        if raw == candidate.rstrip("."):
            return candidate
    for candidate in OPENING_BRIDGES:
        if raw in candidate or candidate in raw:
            return candidate
    return OPENING_BRIDGES[0]


def _title_to_insight_clause(title: str) -> str:
    t = title.strip()
    if not t:
        return "пора прислушаться к себе"
    low = t.lower()
    replacements = {
        "тяга выйти из тесной роли": "пора выйти из тесной роли",
        "эмоциональная нагрузка цикла": "важно беречь эмоциональные границы",
        "что может отзываться сейчас": "важно замедлиться и прислушаться к себе",
        "размытие и чувствительность": "легко потерять ясность — стоит чаще сверяться с собой",
        "глубинная перестройка": "назрела внутренняя перестройка",
        "что имеет смысл наблюдать": "стоит внимательнее смотреть на свои автоматические реакции",
    }
    if low in replacements:
        return replacements[low]
    for prefix in ("тяга ", "желание ", "ощущение ", "тема "):
        if low.startswith(prefix):
            rest = t[len(prefix) :].strip()
            if rest:
                return rest[0].lower() + rest[1:]
    return t[0].lower() + t[1:] if t else "пора прислушаться к себе"


def default_opening(quiz: dict[str, Any], influences: list[dict[str, Any]]) -> dict[str, str]:
    seed = abs(hash(str(quiz.get("name") or "") + str(quiz.get("intent") or "")))
    bridge = OPENING_BRIDGES[seed % len(OPENING_BRIDGES)]
    primary = influences[0] if influences else {}
    title = str(primary.get("title") or "").strip()
    return {
        "bridge": bridge,
        "insight": _title_to_insight_clause(title),
    }


def default_body(quiz: dict[str, Any], influences: list[dict[str, Any]]) -> str:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    primary = focus_keys[0] if focus_keys else "path"
    focus_label = FOCUS_LABELS.get(primary, FOCUS_LABELS["path"])
    intent_label = INTENT_LABELS.get(str(quiz.get("intent") or ""), INTENT_LABELS["other"])
    life_stage = str(quiz.get("life_stage") or quiz.get("lifeStage") or "")
    life_label = LIFE_STAGE_LABELS.get(life_stage, "")

    primary_inf = influences[0] if influences else {}
    inf_text = str(primary_inf.get("text") or "").strip()

    lead = (
        f"Сейчас особенно заметно, где привычная роль стала тесной — особенно в теме «{focus_label}». "
        if primary == "money"
        else "Сейчас особенно заметно, где привычная роль перестала давать опору. "
    )
    if life_label:
        lead = (
            f"Когда {life_label}, в центре внимания оказывается «{focus_label}». "
            f"Чтобы {intent_label}, важно честно назвать, что уже не работает. "
        )
    parts = [lead]
    if inf_text:
        parts.append(inf_text)
    else:
        parts.append(
            "Не нужно резко всё менять: сначала полезно назвать то, что больше не подходит — "
            "и дать себе право выбирать иначе."
        )
    return " ".join(parts)[:800]


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
    influences = out.get("influences") or []
    out["opening"] = default_opening(quiz, influences)
    out["body"] = default_body(quiz, influences)
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
        "Перепиши блоки и собери оффер по этим данным.\n"
        "Первый экран: opening (bridge из списка + insight из title первого influence) "
        "и body (один абзац: цель квиза + рекомендация из influences).\n\n"
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
    influences_before = out.get("influences") or []

    for section in ("influences", "cycles"):
        original = out.get(section) or []
        llm_items = rewritten.get(section)
        if not isinstance(llm_items, list):
            continue
        out[section] = _merge_section(original, llm_items)

    influences = out.get("influences") or influences_before

    opening_raw = rewritten.get("opening")
    if isinstance(opening_raw, dict):
        bridge = _normalize_opening_bridge(str(opening_raw.get("bridge") or ""))
        clause = str(opening_raw.get("insight") or "").strip()
        if clause:
            clause = clause[0].lower() + clause[1:] if len(clause) > 1 else clause.lower()
            out["opening"] = {"bridge": bridge, "insight": clause[:120]}
    if not out.get("opening"):
        out["opening"] = default_opening(quiz, influences)

    body = str(rewritten.get("body") or "").strip()
    if len(body) >= 60:
        out["body"] = body[:900]
    else:
        out["body"] = default_body(quiz, influences)

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
