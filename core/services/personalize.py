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
1) первый экран разбора: opening + body — психологический ПОРТРЕТ паттернов;
2) переписать influences и cycles (кратко, лично, про поведение, не про знаки);
3) один продающий экран product_pitch — какие паттерны у человека и чем Cosmirror поможет;
4) экран outcomes с наглядными карточками динамики через неделю;
5) финальный оффер.

Правила:
- Язык: русский.
- Тон: спокойный, взрослый; без прогнозов, гарантий и медицинских диагнозов.
- Обращение на «ты». Имя в opening/body НЕ пиши — его покажут отдельно.
- Натальные данные (Солнце/Луна/Асцендент) — только внутренний контекст для тебя.
  ЗАПРЕЩЕНО в body, product_pitch, opening.insight, outcomes: конструкции
  «Солнце в …», «Луна в …», «Асцендент в …», перечисления знаков и «карта говорит».
  Пиши про наблюдаемые паттерны поведения, энергии, выбора и отношений.

Первый экран (opening + body) — портрет:
- opening.bridge: выбери РОВНО одну фразу из списка (дословно):
{json.dumps(OPENING_BRIDGES, ensure_ascii=False)}
- opening.insight: продолжение после «что» — главная мягкая рекомендация/наблюдение.
  Бери смысл из title первого influence (переформулируй как клаузу, без заглавной буквы).
  Пример: title «Тяга выйти из тесной роли» → insight «пора выйти из тесной роли».
  До 90 символов. Читается как: «Имя, {{bridge}} {{insight}}».
- body: один абзац-портрет, 4–6 предложений, до ~700 символов.
  Склей квиз (этап/фокус/цель) с influences в живой портрет: как человек обычно устроен,
  где застревает, что сейчас громче. Без каталога планет и знаков.
  ЗАПРЕЩЕНО: списки ответов квиза; дословные focus_labels / intent_label / life_stage_label;
  «сейчас: …», «в фокусе — …», «цель: …»; дублировать opening.insight.

Остальное:
- influences/cycles: key НЕ МЕНЯЙ; title до 60 символов; text до ~280 символов.
  Title/text — про паттерн и опыт, не «Солнце в X».
- product_pitch: экран «что у тебя происходит и чем Cosmirror поможет».
  title до 70 символов — про паттерн/напряжение/фокус человека, НЕ про планеты.
  text 2–3 предложения: назвать его повторяющийся сценарий + как продукт свяжет
  карту/циклы/фокус, чтобы это увидеть раньше и выбирать иначе. Без Солнца/Луны/Асцендента в тексте.
- outcomes: title до 80 символов; cards — РОВНО 4 карточки метрик.
  Каждая card: key (латиница), label (1–2 слова), before/after («32%»), hint до 60 символов.
  after всегда выше before.
- offer: title ТОЧНО «Стань ближе к своему истинному я через подробный разбор»;
  text — 2 строки через \\n; cta ТОЧНО «Получить за 777»; price ТОЧНО «777 ₽/мес».

Верни ТОЛЬКО JSON:
{{
  "opening": {{"bridge": "сейчас пространство показывает, что", "insight": "пора выйти из тесной роли"}},
  "body": "Один связный абзац-портрет без названий знаков...",
  "influences": [{{"key": "...", "title": "...", "text": "..."}}],
  "cycles": [{{"key": "...", "title": "...", "text": "..."}}],
  "product_pitch": {{"title": "...", "text": "..."}},
  "outcomes": {{
    "title": "...",
    "cards": [
      {{"key": "clarity", "label": "Ясность", "before": "32%", "after": "81%", "hint": "видишь, что даёт энергию"}},
      {{"key": "patterns", "label": "Паттерны", "before": "24%", "after": "76%", "hint": "замечаешь повторения раньше"}}
    ]
  }},
  "offer": {{
    "title": "Стань ближе к своему истинному я через подробный разбор",
    "text": "Персональный разбор под твои паттерны.\\nОтслеживание энергии и повторяющихся сценариев.",
    "cta": "Получить за 777",
    "price": "777 ₽/мес"
  }}
}}
"""


def _has_funnel_structure(insight: Optional[dict[str, Any]]) -> bool:
    """Есть opening + body + product_pitch + outcomes + offer."""
    if not isinstance(insight, dict):
        return False
    offer = insight.get("offer")
    if not isinstance(offer, dict):
        return False
    if not (str(offer.get("title") or "").strip() and str(offer.get("text") or "").strip()):
        return False
    pitch = insight.get("product_pitch")
    if not isinstance(pitch, dict):
        return False
    if not (str(pitch.get("title") or "").strip() and str(pitch.get("text") or "").strip()):
        return False
    outcomes = insight.get("outcomes")
    cards_ok = (
        isinstance(outcomes, dict)
        and isinstance(outcomes.get("cards"), list)
        and len(outcomes.get("cards") or []) >= 4
    )
    if not cards_ok:
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
    Готовый инсайт: структура воронки v2 есть.
    Шаблоны не финал, если LLM настроен — перегенерируем.
    Для LLM-источников дополнительно требуется editorial_passed.
    """
    if not _has_funnel_structure(insight):
        return False
    if int((insight or {}).get("funnel_version") or 1) < 3:
        return False
    source = str((insight or {}).get("source") or "")
    if source in ("", "templates"):
        if llm_client.is_configured():
            return False
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
        return _with_templates(base_insight, offer, quiz, natal)

    try:
        rewritten = _call_llm(base_insight, natal, quiz)
        provider = llm_client.active_provider() or "llm"
        merged = _merge_llm_result(
            base_insight,
            rewritten,
            offer_fallback=offer,
            quiz=quiz,
            natal=natal,
            source=provider,
            require_llm_fields=True,
        )
    except Exception:
        logger.warning("Insight personalization failed; retrying once", exc_info=False)
        try:
            rewritten = _call_llm(base_insight, natal, quiz)
            provider = llm_client.active_provider() or "llm"
            merged = _merge_llm_result(
                base_insight,
                rewritten,
                offer_fallback=offer,
                quiz=quiz,
                natal=natal,
                source=provider,
                require_llm_fields=True,
            )
        except Exception:
            logger.warning("Insight personalization failed; using templates", exc_info=False)
            return _with_templates(base_insight, offer, quiz, natal)

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
    return {
        "title": "Стань ближе к своему истинному я через подробный разбор",
        "text": (
            f"Персональный разбор под твою карту и тему «{focus_label}».\n"
            f"Отслеживание энергии, паттернов и циклов — чтобы {intent_label}."
        ),
        "cta": "Получить за 777",
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
        "cards": [
            {
                "key": "clarity",
                "label": "Ясность",
                "before": "32%",
                "after": "81%",
                "hint": "видишь, что даёт энергию",
            },
            {
                "key": "patterns",
                "label": "Паттерны",
                "before": "24%",
                "after": "76%",
                "hint": "замечаешь повторения раньше",
            },
            {
                "key": "strengths",
                "label": "Сильные стороны",
                "before": "38%",
                "after": "84%",
                "hint": "понимаешь, что масштабировать",
            },
            {
                "key": "rhythm",
                "label": "Свой ритм",
                "before": "29%",
                "after": "79%",
                "hint": "легче выбирать решения",
            },
        ],
    }


def default_product_pitch(
    cycles: list[dict[str, Any]],
    quiz: dict[str, Any],
    natal: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    focus_label = FOCUS_LABELS.get(focus_keys[0], "жизни") if focus_keys else "жизни"
    intent_label = INTENT_LABELS.get(str(quiz.get("intent") or ""), INTENT_LABELS["other"])
    title = f"Увидеть свой паттерн в теме «{focus_label}»"
    cycle_hint = ""
    if cycles:
        cycle_hint = f" На фоне сейчас громче «{cycles[0].get('title', 'текущий цикл')}»."
    text = (
        f"Cosmirror помогает заметить, как повторяющиеся сценарии сходятся с фокусом «{focus_label}», "
        f"чтобы {intent_label}.{cycle_hint} Не общий гороскоп — разбор того, что уже происходит у тебя."
    )
    return {"title": title[:120], "text": text[:500]}


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


def _with_templates(
    insight: dict[str, Any],
    offer: dict[str, str],
    quiz: dict[str, Any],
    natal: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = copy.deepcopy(insight) if insight else {}
    out.setdefault("tone", "pattern_psych")
    cycles = out.get("cycles") or []
    influences = out.get("influences") or []
    out["opening"] = default_opening(quiz, influences)
    out["body"] = default_body(quiz, influences)
    out["product_pitch"] = default_product_pitch(cycles, quiz, natal)
    out["outcomes"] = default_outcomes(quiz)
    out["offer"] = offer
    out["funnel_version"] = 3
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
        "Экран 1: opening + body. Экран 2: product_pitch. Экран 3: outcomes.cards (4 метрики). "
        "Экран 4: offer.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return llm_client.chat_json(system=SYSTEM_PROMPT, user=user)


def _merge_llm_result(
    base_insight: dict[str, Any],
    rewritten: dict[str, Any],
    *,
    offer_fallback: dict[str, str],
    quiz: dict[str, Any],
    natal: Optional[dict[str, Any]] = None,
    source: str = "llm",
    require_llm_fields: bool = False,
) -> dict[str, Any]:
    out = copy.deepcopy(base_insight)
    influences_before = out.get("influences") or []
    missing: list[str] = []

    for section in ("influences", "cycles"):
        original = out.get(section) or []
        llm_items = rewritten.get(section)
        if not isinstance(llm_items, list):
            continue
        out[section] = _merge_section(original, llm_items)

    influences = out.get("influences") or influences_before

    # User-facing funnel texts: only from LLM when require_llm_fields.
    if require_llm_fields:
        for key in ("opening", "body", "product_pitch", "outcomes", "offer"):
            out.pop(key, None)

    opening_raw = rewritten.get("opening")
    if isinstance(opening_raw, dict):
        bridge = _normalize_opening_bridge(str(opening_raw.get("bridge") or ""))
        clause = str(opening_raw.get("insight") or "").strip()
        if clause:
            clause = clause[0].lower() + clause[1:] if len(clause) > 1 else clause.lower()
            out["opening"] = {"bridge": bridge, "insight": clause[:120]}
    if not out.get("opening"):
        if require_llm_fields:
            missing.append("opening")
        else:
            out["opening"] = default_opening(quiz, influences)

    body = str(rewritten.get("body") or "").strip()
    if len(body) >= 60:
        out["body"] = body[:900]
    elif require_llm_fields:
        missing.append("body")
    else:
        out["body"] = default_body(quiz, influences)

    cycles = out.get("cycles") or []

    pitch_raw = rewritten.get("product_pitch")
    if isinstance(pitch_raw, dict):
        p_title = str(pitch_raw.get("title") or "").strip()
        p_text = str(pitch_raw.get("text") or "").strip()
        if p_title and p_text:
            out["product_pitch"] = {"title": p_title[:120], "text": p_text[:500]}
    if not out.get("product_pitch"):
        if require_llm_fields:
            missing.append("product_pitch")
        else:
            out["product_pitch"] = default_product_pitch(cycles, quiz, natal)

    outcomes = rewritten.get("outcomes")
    if isinstance(outcomes, dict):
        o_title = str(outcomes.get("title") or "").strip()
        cards = outcomes.get("cards")
        if o_title and isinstance(cards, list):
            merged_cards: list[dict[str, str]] = []
            for idx, card in enumerate(cards[:4]):
                if not isinstance(card, dict):
                    continue
                key = str(card.get("key") or f"metric_{idx}")
                label = str(card.get("label") or "").strip()
                before = str(card.get("before") or "").strip()
                after = str(card.get("after") or "").strip()
                hint = str(card.get("hint") or "").strip()
                if label and before and after:
                    merged_cards.append(
                        {
                            "key": key[:40],
                            "label": label[:40],
                            "before": before[:12],
                            "after": after[:12],
                            "hint": hint[:80],
                        }
                    )
            if len(merged_cards) >= 4:
                out["outcomes"] = {"title": o_title[:120], "cards": merged_cards}
    if not out.get("outcomes"):
        if require_llm_fields:
            missing.append("outcomes")
        else:
            out["outcomes"] = default_outcomes(quiz)

    offer = rewritten.get("offer")
    if isinstance(offer, dict):
        text = str(offer.get("text") or "").strip()
        price = str(offer.get("price") or offer_fallback.get("price") or "777 ₽/мес").strip()
        fixed_title = "Стань ближе к своему истинному я через подробный разбор"
        fixed_cta = "Получить за 777"
        if text:
            out["offer"] = {
                "title": fixed_title,
                "text": text[:500],
                "cta": fixed_cta,
                "price": price[:40],
            }
        elif require_llm_fields:
            missing.append("offer")
        else:
            out["offer"] = offer_fallback
    elif require_llm_fields:
        missing.append("offer")
    else:
        out["offer"] = offer_fallback

    if missing:
        raise ValueError(f"LLM response missing required fields: {', '.join(missing)}")

    out["tone"] = "pattern_psych_llm"
    out["funnel_version"] = 3
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
