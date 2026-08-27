"""
Персонализация инсайта через LLM (Polza.ai / Groq): перепись шаблонов + оффер.

Без ключа / при ошибке — шаблоны + дефолтный оффер из фокуса квиза.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
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

# Связки для составного заголовка (после имени, перед наблюдением).
# Ответ на вопрос/намерение пользователя: «Имя, {bridge} {insight}».
OPENING_BRIDGES = [
    "ты можешь замечать, что",
    "ты можешь чувствовать, что",
    "сейчас важно",
]

SYSTEM_PROMPT = f"""\
Ты редактор психологических текстов для продукта Cosmirror (астро-психология без эзотерического пафоса).

Задача: подготовить тексты онбординг-воронки после квиза (3 экрана + данные):
1) первый экран разбора: opening + body — короткий психологический ПОРТРЕТ (один экран);
2) переписать influences и cycles (кратко, лично, про поведение, не про знаки);
3) экран product_pitch: обещание разбора (методика, не список выгод);
4) offer + outcomes.cards: «Что ты поймёшь после разбора». outcomes.cards — 4 пункта
   того, что человек поймёт (не «изменения за неделю»).

Правила:
- Язык: русский.
- Тон: спокойный, взрослый; без прогнозов, гарантий и медицинских диагнозов.
- Обращение на «ты». Имя в opening/body НЕ пиши — его покажут отдельно.
- Грамматический род: quiz.gender female → женский; male → мужской; иначе нейтрально, без мужского по умолчанию.
- Натальные данные (Солнце/Луна/Асцендент) — только внутренний контекст для тебя.
  ЗАПРЕЩЕНО в body, product_pitch, opening.insight, outcomes, offer.text: конструкции
  «Солнце в …», «Луна в …», «Асцендент в …», перечисления знаков и «карта говорит».
  Пиши про наблюдаемые паттерны поведения, энергии, выбора и отношений.
- НЕ пиши про «наблюдения через неделю», «метрики за неделю», подписку-сервис как продукт.
  Мы продаём подробный персональный разбор-отчёт (информацию для опоры).

Первый экран (opening + body) — короткий портрет на ОДИН экран телефона:
- opening.bridge: выбери РОВНО одну фразу из списка (дословно):
{json.dumps(OPENING_BRIDGES, ensure_ascii=False)}
- opening.insight: прямой ответ на вопрос/намерение пользователя (intent из квиза) —
  мягкое наблюдение или фокус внимания. Бери смысл из title первого influence
  (переформулируй как клаузу, без заглавной буквы).
  Если bridge заканчивается на «что» — клауза после «что».
  Если bridge «сейчас важно» — клауза сразу после (без «что»).
  Пример: title «Тяга выйти из тесной роли» → insight «пора выйти из тесной роли».
  До 80 символов. Читается как: «Имя, {{bridge}} {{insight}}».
- body: РОВНО 2–3 коротких предложения, до ~280 символов.
  Один сфокусированный паттерн + мягкий вывод. Без «литературного романа».
  ЗАПРЕЩЕНО: 4+ предложений; списки ответов квиза; дословные focus_labels / intent_label;
  «сейчас: …», «в фокусе — …», «цель: …»; дублировать opening.insight.

Остальное:
- influences/cycles: key НЕ МЕНЯЙ; title до 60 символов; text до ~200 символов.
  Title/text — про паттерн и опыт, не «Солнце в X».
- product_pitch: методика разбора (не второй инсайт и не список выгод).
  title ТОЧНО: «Стань ближе к своему истинному я через подробный разбор»
  (фраза «истинному я» будет выделена курсивом на фронте).
  text — РОВНО 2 предложения через \\n, смысл держи:
  «Разберём твой космопортрет: влияние планет, сильные конфигурации, напряжённые аспекты и слепые зоны.\\nСоединим с активными циклами, расскажем об их значениях и как с ними работать.»
  ЗАПРЕЩЕНО: NASA, JPL, «через неделю», список выгод.
- outcomes: title ТОЧНО «Что ты поймёшь после разбора».
  cards — РОВНО 4 пункта того, что человек поймёт после разбора.
  key ТОЧНО по списку: natal, cycles, tension, focus.
  label/hint можно чуть подстроить под фокус, но смысл блоков не меняй:
  1) natal — «Твоя натальная карта»: сильные стороны, потребности, противоречия, сценарии и связь с планетами;
  2) cycles — «Твои текущие периоды»: транзиты на первом плане и как с ними работать;
  3) tension — «Напряжение и ресурс»: компенсация напряжённых аспектов положительными, окна возможностей;
  4) focus — «Разбор твоего запроса»: связь с темой квиза, рекомендации и вопросы для самостоятельной работы.
  before/after — служебные проценты; after > before.
- offer: title ТОЧНО «Стань ближе к своему истинному я через подробный разбор»;
  text — пустая строка или 1 короткая (до 80 символов); детали на фронте списком блоков.
  cta ТОЧНО «Получить за 777»; price ТОЧНО «777 ₽».

Верни ТОЛЬКО JSON:
{{
  "opening": {{"bridge": "ты можешь замечать, что", "insight": "пора выйти из тесной роли"}},
  "body": "Два-три коротких предложения портрета.",
  "influences": [{{"key": "...", "title": "...", "text": "..."}}],
  "cycles": [{{"key": "...", "title": "...", "text": "..."}}],
  "product_pitch": {{
    "title": "Стань ближе к своему истинному я через подробный разбор",
    "text": "Разберём твой космопортрет: влияние планет, сильные конфигурации, напряжённые аспекты и слепые зоны.\\nСоединим с активными циклами, расскажем об их значениях и как с ними работать."
  }},
  "outcomes": {{
    "title": "Что ты поймёшь после разбора",
    "cards": [
      {{"key": "natal", "label": "Твоя натальная карта", "before": "32%", "after": "81%", "hint": "сильные стороны, потребности, противоречия, повторяющиеся сценарии и связь с положениями планет"}},
      {{"key": "cycles", "label": "Твои текущие периоды", "before": "24%", "after": "76%", "hint": "значение и длительность транзитов, которые выходят на первый план, и как с ними работать"}}
    ]
  }},
  "offer": {{
    "title": "Стань ближе к своему истинному я через подробный разбор",
    "text": "",
    "cta": "Получить за 777",
    "price": "777 ₽"
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
    if not str(offer.get("title") or "").strip():
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
    Первый успешный LLM-проход считается финалом (editorial_passed).
    """
    if not _has_funnel_structure(insight):
        return False
    if int((insight or {}).get("funnel_version") or 1) < 4:
        return False
    source = str((insight or {}).get("source") or "")
    if source in ("", "templates"):
        if llm_client.is_configured():
            return False
        return True
    return True


def insight_is_ready(insight: Optional[dict[str, Any]]) -> bool:
    """Можно отдавать на экран: персонализирован, шаблоны без LLM, или уже пробовали."""
    if is_personalized(insight):
        return True
    if not llm_client.is_configured():
        return True
    return bool(isinstance(insight, dict) and insight.get("personalize_attempted"))


def should_schedule_personalization(insight: Optional[dict[str, Any]]) -> bool:
    if not llm_client.is_configured():
        return False
    if is_personalized(insight):
        return False
    if isinstance(insight, dict) and insight.get("personalize_attempted"):
        return False
    return True


def personalize_insight(
    *,
    insight: dict[str, Any],
    natal: dict[str, Any],
    quiz: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Вернуть инсайт с offer.
    Если уже personalized — вернуть как есть.
    Если LLM недоступен / медленный — шаблоны + default offer.
    Второй LLM-проход (editorial) не блокирует выдачу: первый промпт уже содержит правила.
    """
    if is_personalized(insight):
        return insight

    quiz = quiz or {}
    base_insight = copy.deepcopy(insight) if insight else {}
    offer = default_offer(quiz)
    templates = _with_templates(base_insight, offer, quiz, natal)

    # Старый кэш: LLM уже писал тексты, ждали editorial. Не гоняем второй вызов.
    if _has_funnel_structure(base_insight) and not base_insight.get("editorial_passed"):
        source = str(base_insight.get("source") or "")
        if source and source != "templates":
            base_insight["editorial_passed"] = True
            return base_insight

    if not llm_client.is_configured():
        return templates

    import concurrent.futures

    def _llm_path() -> dict[str, Any]:
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
        merged["editorial_passed"] = True
        return merged

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_llm_path)
        # Один вызов Polza обычно 8–25с; не держим HTTP дольше этого.
        return future.result(timeout=45)
    except concurrent.futures.TimeoutError:
        logger.warning("Insight personalization timed out; using templates")
        return templates
    except Exception:
        logger.warning("Insight personalization failed; using templates", exc_info=False)
        return templates
    finally:
        # Не ждём зависший LLM-поток — иначе timeout бесполезен.
        pool.shutdown(wait=False, cancel_futures=True)


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
    return {
        "title": "Стань ближе к своему истинному я через подробный разбор",
        "text": "",
        "cta": "Получить за 777",
        "price": "777 ₽",
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
        "эмоциональная нагрузка цикла": "беречь эмоциональные границы",
        "что может отзываться сейчас": "замедлиться и прислушаться к себе",
        "размытие и чувствительность": "легко потерять ясность — стоит чаще сверяться с собой",
        "глубинная перестройка": "назрела внутренняя перестройка",
        "где жизнь просит шире": "уже тесно в привычном масштабе",
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


def _fit_clause_to_bridge(bridge: str, clause: str) -> str:
    """Не дублировать хвост связки: «сейчас важно важно беречь…»."""
    tail = bridge.strip().lower().split()[-1] if bridge.strip() else ""
    words = clause.strip().split()
    if tail and words and words[0].lower().rstrip(".,!") == tail:
        return " ".join(words[1:]).strip() or clause.strip()
    return clause.strip()


def default_opening(quiz: dict[str, Any], influences: list[dict[str, Any]]) -> dict[str, str]:
    seed = abs(hash(str(quiz.get("name") or "") + str(quiz.get("intent") or "")))
    bridge = OPENING_BRIDGES[seed % len(OPENING_BRIDGES)]
    primary = influences[0] if influences else {}
    title = str(primary.get("title") or "").strip()
    return {
        "bridge": bridge,
        "insight": _fit_clause_to_bridge(bridge, _title_to_insight_clause(title)),
    }


def default_body(quiz: dict[str, Any], influences: list[dict[str, Any]]) -> str:
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    primary = focus_keys[0] if focus_keys else "path"
    focus_label = FOCUS_LABELS.get(primary, FOCUS_LABELS["path"])
    intent_label = INTENT_LABELS.get(str(quiz.get("intent") or ""), INTENT_LABELS["other"])

    primary_inf = influences[0] if influences else {}
    inf_text = str(primary_inf.get("text") or "").strip()
    if inf_text:
        short = inf_text.split(".")[0].strip()
        return f"{short}. Чтобы {intent_label}, важно сначала назвать, что уже не даёт опоры в теме «{focus_label}»."[:320]
    return (
        f"Сейчас особенно заметно, где привычная роль стала тесной в теме «{focus_label}». "
        f"Чтобы {intent_label}, полезно честно увидеть, что больше не работает."
    )[:320]


def default_outcomes(quiz: dict[str, Any]) -> dict[str, Any]:
    """Что человек поймёт после разбора: 4 фиксированных блока + тема квиза."""
    focus = quiz.get("focus") or []
    if isinstance(focus, str):
        focus = [focus]
    focus_keys = [str(f) for f in focus if f]
    focus_label = FOCUS_LABELS.get(focus_keys[0], "жизни") if focus_keys else "жизни"
    return {
        "title": "Что ты поймёшь после разбора",
        "cards": [
            {
                "key": "natal",
                "label": "Твоя натальная карта",
                "before": "32%",
                "after": "81%",
                "hint": "Сильные стороны, потребности, противоречия, повторяющиеся сценарии и как это связано с положениями планет.",
            },
            {
                "key": "cycles",
                "label": "Твои текущие периоды",
                "before": "24%",
                "after": "76%",
                "hint": "Значение и длительность транзитов, которые выходят на первый план, и как с ними работать.",
            },
            {
                "key": "tension",
                "label": "Напряжение и ресурс",
                "before": "38%",
                "after": "84%",
                "hint": "Поймёшь, как компенсировать напряжённые аспекты положительными, увидишь открытые окна возможностей по циклам.",
            },
            {
                "key": "focus",
                "label": "Разбор твоего запроса",
                "before": "29%",
                "after": "79%",
                "hint": f"Связь с твоим запросом «{focus_label}»: рекомендации и вопросы для самостоятельной работы.",
            },
        ],
    }


def default_product_pitch(
    cycles: list[dict[str, Any]],
    quiz: dict[str, Any],
    natal: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    title = "Стань ближе к своему истинному я через подробный разбор"
    text = (
        "Разберём твой космопортрет: влияние планет, сильные конфигурации, "
        "напряжённые аспекты и слепые зоны.\n"
        "Соединим с активными циклами, расскажем об их значениях и как с ними работать."
    )
    return {"title": title[:90], "text": text[:520]}


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
    out["funnel_version"] = 5
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
        "Экран 1: opening + body. Экран 2: product_pitch (методика разбора). "
        "Экран 3: outcomes.cards (что поймёшь после разбора).\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return llm_client.chat_json(
        system=SYSTEM_PROMPT,
        user=user,
        prompt_id="onboarding_insight",
    )


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
            out["opening"] = {
                "bridge": bridge,
                "insight": _fit_clause_to_bridge(bridge, clause)[:120],
            }
    if not out.get("opening"):
        if require_llm_fields:
            missing.append("opening")
        else:
            out["opening"] = default_opening(quiz, influences)

    body = str(rewritten.get("body") or "").strip()
    if len(body) >= 60:
        out["body"] = body[:320]
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
            # Короткий pitch: не пускаем методологические простыни
            out["product_pitch"] = {"title": p_title[:90], "text": p_text[:520]}
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
                            "hint": hint[:180],
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
        price = str(offer.get("price") or offer_fallback.get("price") or "777 ₽").strip()
        fixed_title = "Стань ближе к своему истинному я через подробный разбор"
        fixed_cta = "Получить за 777"
        # text может быть пустым — блоки оффера рисует фронт
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

    if missing:
        raise ValueError(f"LLM response missing required fields: {', '.join(missing)}")

    out["tone"] = "pattern_psych_llm"
    out["funnel_version"] = 5
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


_inflight_guard = threading.Lock()
_inflight_tokens: set[str] = set()


def quiz_from_session(session) -> dict[str, Any]:
    """Собрать ответы квиза со всех content-шагов (не waitlist)."""
    from core.models import OnboardingStep

    quiz: dict[str, Any] = {}
    answers = (
        session.answers.select_related("step")
        .exclude(step__step_type=OnboardingStep.StepType.WAITLIST)
        .order_by("step__order", "-updated_at")
    )
    seen_slugs: set[str] = set()
    for answer in answers:
        slug = answer.step.slug
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        if not isinstance(answer.payload, dict):
            continue
        for key, value in answer.payload.items():
            if value in (None, "", [], {}):
                continue
            quiz[key] = value
    return quiz


def schedule_session_personalization(session_id: int, chart_id: int, token: str) -> None:
    """Запустить LLM-разбор в фоне. Повторные вызовы с тем же token игнорируются."""
    if not token or not llm_client.is_configured():
        return
    with _inflight_guard:
        if token in _inflight_tokens:
            return
        _inflight_tokens.add(token)
    thread = threading.Thread(
        target=_run_session_personalization,
        args=(session_id, chart_id, token),
        daemon=True,
        name=f"insight-{token[:8]}",
    )
    thread.start()


def _run_session_personalization(session_id: int, chart_id: int, token: str) -> None:
    from django.db import close_old_connections

    from core.models import NatalChart, OnboardingSession

    close_old_connections()
    try:
        session = OnboardingSession.objects.filter(pk=session_id).first()
        chart = NatalChart.objects.filter(pk=chart_id).first()
        if not session or not chart or not isinstance(chart.chart_data, dict):
            return
        data = dict(chart.chart_data)
        insight = data.get("insight") if isinstance(data.get("insight"), dict) else {}
        if not should_schedule_personalization(insight):
            return
        natal = {
            "planets": data.get("planets"),
            "ascendant": data.get("ascendant"),
            "midheaven": data.get("midheaven"),
            "houses": data.get("houses"),
            "notes": data.get("notes") or [],
            "location": data.get("location"),
            "timezone": data.get("timezone"),
            "engine": data.get("engine"),
            "has_birth_time": bool(data.get("has_birth_time")),
        }
        personalized = personalize_insight(
            insight=insight,
            natal=natal,
            quiz=quiz_from_session(session),
        )
        if not is_personalized(personalized):
            personalized = copy.deepcopy(personalized)
            personalized["personalize_attempted"] = True
        data["insight"] = personalized
        chart.chart_data = data
        chart.save(update_fields=["chart_data", "updated_at"])
    except Exception:
        logger.warning("Background insight personalization failed", exc_info=True)
    finally:
        with _inflight_guard:
            _inflight_tokens.discard(token)
        close_old_connections()
