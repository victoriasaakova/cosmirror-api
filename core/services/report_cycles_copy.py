"""
Degraded fallback вкладки «Циклы».

Это не упрощённый Skill 03. Здесь только факты расчёта и короткая
энциклопедическая семантика пары transit → natal. Психологические поля
Skill 03 (защита, слепая зона, ACT, coaching) не заполняются.
"""

from __future__ import annotations

from typing import Any

from core.services.report_lexicon import (
    ASPECT_THEME,
    HOUSE_ARENA,
    PLANET_THEME,
    as_sentence,
    duration_span_sentence,
)
from core.services.report_types import PLANET_RU, POLARITY_PRESSURE, POLARITY_RESOURCE

EMPTY_SKILL_FIELDS = {
    "deep_read": "",
    "personalization": "",
    "possible_manifestations": [],
    "protective_function": "",
    "tension_or_blind_spot": "",
    "resource": "",
    "how_to_work": "",
}

TRANSIT_LENS = {
    "sun": "текущий акцент на самовыражении и направлении",
    "moon": "текущий акцент на опоре и эмоциональном фоне",
    "mercury": "текущий акцент на мысли, речи и обмене",
    "venus": "текущий акцент на ценности, притяжении и близости",
    "mars": "текущий акцент на действии, инициативе и отстаивании позиции",
    "jupiter": "текущий акцент на расширении поля и смысле",
    "saturn": "текущий акцент на структуре, пределах и опоре",
    "uranus": "текущий акцент на обновлении слишком тесной формы",
    "neptune": "текущий акцент на идеале, атмосфере и размытии границ",
    "pluto": "текущий акцент на глубинной перестройке и контроле",
}

NATAL_LENS = {
    "sun": "натальным способом держать направление и ощущение «это я»",
    "moon": "натальным способом искать опору и безопасность",
    "mercury": "натальным способом понимать, формулировать и обмениваться",
    "venus": "натальным способом беречь ценность и близость",
    "mars": "натальным способом действовать и отстаивать позицию",
    "jupiter": "натальным способом расти и искать смысл",
    "saturn": "натальным способом выстраивать пределы и выдерживать форму",
    "uranus": "натальным способом выходить из слишком тесной роли",
    "neptune": "натальным способом держать идеал и проницаемость",
    "pluto": "натальным способом выдерживать интенсивность и контроль",
    "ascendant": "натальным способом входить в контакт",
    "midheaven": "натальной внешней ролью и видимым вкладом",
}

PHASE_RU = {
    "applying": "сходится",
    "exact": "точный контакт",
    "separating": "расходится",
}


def category_for_polarity(polarity: str) -> str:
    if polarity == POLARITY_PRESSURE:
        return "tension"
    if polarity == POLARITY_RESOURCE:
        return "support"
    return "mixed"


def human_theme_for(transit: str, natal: str, aspect: str, t_name: str, n_name: str) -> str:
    transit_lens = TRANSIT_LENS.get(transit)
    natal_lens = NATAL_LENS.get(natal)
    if transit_lens and natal_lens:
        pair = f"{transit_lens} соприкасается с {natal_lens}"
    else:
        pair = f"текущий акцент {t_name} соприкасается с натальной темой {n_name}"
    if aspect in {"square", "opposition"}:
        return pair[0].upper() + pair[1:] + " — через трение"
    if aspect in {"trine", "sextile"}:
        return pair[0].upper() + pair[1:] + " — через более доступный канал"
    if aspect == "conjunction":
        return pair[0].upper() + pair[1:] + " и звучит почти как одна тема"
    return pair[0].upper() + pair[1:]


def observation_question(transit: str, natal: str, aspect: str, t_name: str, n_name: str) -> str:
    pair = (transit, natal)
    specific = {
        ("sun", "mars"): (
            "Где сейчас особенно заметно желание действовать, ускоряться "
            "или сильнее отстаивать позицию?"
        ),
        ("mars", "sun"): (
            "Где сейчас особенно заметно желание действовать, ускоряться "
            "или сильнее отстаивать позицию?"
        ),
        ("uranus", "sun"): (
            "Где сейчас заметнее расхождение между привычной ролью и тем, что уже тесно?"
        ),
        ("jupiter", "venus"): (
            "Где сейчас заметнее желание расширить поле близости, ценности или удовольствия?"
        ),
        ("pluto", "moon"): (
            "Где сейчас привычные способы искать опору ощущаются иначе, чем обычно?"
        ),
        ("saturn", "sun"): (
            "Где сейчас направление или видимость требуют более ясного контура?"
        ),
    }
    if pair in specific:
        return specific[pair]
    if aspect in {"square", "opposition"}:
        return (
            f"Где сейчас заметнее трение между текущей темой {t_name.lower()} "
            f"и {n_name.lower()}?"
        )
    if aspect in {"trine", "sextile"}:
        return (
            f"Где сейчас связь {t_name.lower()} и {n_name.lower()} "
            f"уже проявляется как более доступный канал?"
        )
    return (
        f"Где сейчас особенно заметно взаимодействие {t_name.lower()} "
        f"и {n_name.lower()} — в действии, отношениях, работе или ощущении себя?"
    )


def timing_text_for(hit: dict[str, Any]) -> str:
    window = hit.get("window") if isinstance(hit.get("window"), dict) else {}
    parts: list[str] = []
    span = duration_span_sentence(str(window.get("span_note") or ""))
    if span:
        parts.append(span)
    peak = window.get("peak_estimate")
    if peak:
        parts.append(f"Оценка пика по орбу: {peak}.")
    phase = PHASE_RU.get(str(hit.get("motion") or ""), "")
    if phase:
        parts.append(as_sentence(f"Фаза: {phase}"))
    return " ".join(parts).strip()


def compose_fallback_cycle_summary(hit: dict[str, Any]) -> str:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    t_name = str(hit.get("transit_name") or PLANET_RU.get(transit, transit))
    n_name = str(hit.get("natal_name") or PLANET_RU.get(natal, natal))
    aspect_ru = str(hit.get("aspect_ru") or aspect)
    aspect_clause = ASPECT_THEME.get(aspect, "две темы вступают в контакт")
    t_theme = PLANET_THEME.get(transit, "")
    n_theme = PLANET_THEME.get(natal, "")
    sentences = [
        f"{t_name} {aspect_ru} {n_name} — текущий транзит к уже посчитанной карте, "
        f"не черта характера и не натальный аспект."
    ]
    sentences.append(f"В астрологической рамке {aspect_clause}.")
    if t_theme and n_theme:
        sentences.append(
            f"Транзитный {t_name.lower()} связан с {t_theme}; "
            f"натальный {n_name.lower()} — с {n_theme}."
        )
    elif n_theme:
        sentences.append(f"Натальный {n_name.lower()} связан с {n_theme}.")
    elif t_theme:
        sentences.append(f"Транзитный {t_name.lower()} связан с {t_theme}.")
    house = hit.get("natal_house")
    if isinstance(house, int) and house in HOUSE_ARENA:
        sentences.append(f"Тема может быть заметнее {HOUSE_ARENA[house]}.")
    sentences.append(
        "Это полезнее воспринимать как временную тему для наблюдения, "
        "а не как описание большого жизненного периода."
    )
    return " ".join(sentences)


def compose_fallback_cycle(hit: dict[str, Any]) -> dict[str, Any]:
    transit = str(hit.get("transit") or "")
    natal = str(hit.get("natal") or "")
    aspect = str(hit.get("aspect") or "")
    polarity = str(hit.get("polarity") or "mixed")
    category = category_for_polarity(polarity)
    t_name = str(hit.get("transit_name") or PLANET_RU.get(transit, transit))
    n_name = str(hit.get("natal_name") or PLANET_RU.get(natal, natal))
    aspect_ru = str(hit.get("aspect_ru") or aspect)
    theme = human_theme_for(transit, natal, aspect, t_name, n_name)
    explanation = compose_fallback_cycle_summary(hit)
    question = observation_question(transit, natal, aspect, t_name, n_name)
    fact = str(hit.get("fact") or "").strip()
    return {
        "source": "fallback",
        "cycle_id": str(hit.get("id") or ""),
        "category": category,
        "technical_title": f"{t_name} {aspect_ru} {n_name}".strip(),
        "headline": theme,
        "human_theme": theme,
        "short_explanation": explanation,
        "timing": {
            "orb_deg": hit.get("orb"),
            "phase": str(hit.get("motion") or ""),
            "active_window_text": timing_text_for(hit),
            "exact_passes_text": "",
        },
        "astrology_explanation": fact,
        "summary": explanation,
        **EMPTY_SKILL_FIELDS,
        "reflection_question": question,
        "reflection_questions": [question],
        "transit": transit,
        "natal": natal,
        "aspect": aspect,
        "aspect_ru": aspect_ru,
        "transit_name": t_name,
        "natal_name": n_name,
        "priority_score": float(hit.get("weight_hint") or 0),
    }


def compose_card(hit: dict[str, Any]) -> dict[str, Any]:
    """Совместимое имя: fallback-карточка, не имитация Skill 03."""
    return compose_fallback_cycle(hit)


def fallback_period_overview(cards: list[dict[str, Any]]) -> dict[str, str]:
    if not cards:
        return {
            "headline": "Значимых персональных транзитов в текущем орбе нет",
            "summary": (
                "Это расчётный слой внешнего неба к уже посчитанной карте. "
                "Подробная интерпретация периода появится после генерации."
            ),
            "main_tension": "",
            "main_support": "",
        }
    grouping = ""
    counts: dict[str, int] = {}
    for card in cards:
        key = str(card.get("natal_name") or card.get("natal") or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    repeated = [name for name, count in counts.items() if count >= 2]
    if repeated:
        grouping = f" Несколько активных циклов затрагивают {repeated[0]}."
    count = len(cards)
    if count == 1:
        noun = "персональный транзит"
    elif count < 5:
        noun = "персональных транзита"
    else:
        noun = "персональных транзитов"
    return {
        "headline": "Что сейчас рассчитано во внешнем небе",
        "summary": (
            f"В текущем орбе {count} {noun} к твоей карте. "
            "Это факты периода, не психологический разбор и не прогноз событий."
            f"{grouping} Подробный слой появится, когда соберётся интерпретация."
        ),
        "main_tension": "",
        "main_support": "",
    }


def fallback_cross_cycle_synthesis(cards: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for card in cards:
        key = str(card.get("natal_name") or card.get("natal") or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    repeated = [name for name, count in counts.items() if count >= 2]
    if not repeated:
        return {}
    return {
        "headline": "Какие точки карты затронуты несколько раз",
        "narrative": (
            f"Несколько активных циклов затрагивают {', '.join(repeated)}. "
            "Это группировка по расчёту, не вывод о главном внутреннем конфликте периода."
        ),
        "what_to_watch": [],
        "available_support": [],
        "reflection_questions": [],
    }
