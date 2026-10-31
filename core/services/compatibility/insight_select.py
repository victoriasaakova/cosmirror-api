"""Выбор одной темы первого инсайта до модели.

Веса — insight-selection-v2-draft из blueprint: эвристика отбора, не оценка отношений.
Зеркальный B_to_A того же контакта в счёт не идёт. Натальные качества без своих аспектов не выводятся.
"""

from __future__ import annotations

from typing import Any, Optional

from .policy import ANGLES, NODES, PERSONAL, SLOW, SOCIAL

SCORING_VERSION = "insight-selection-v2-draft"
EDITORIAL_VERSION = "2.2"

SOFT_THEMES = frozenset({"emotional_support", "mutual_inspiration", "shared_language"})

_DISCOUNT = (1.0, 0.45, 0.20)


# Надбавка за тип связи не может перебить заметно более тесный аспект.
# Статус даёт отдельный небольшой бонус: для близких сюжетов он может сменить победителя.
_FOCUS = {
    "romantic": {
        "desire_and_pace": 0.08,
        "rhythm_of_closeness": 0.08,
        "feelings_and_action": 0.07,
        "closeness_and_boundaries": 0.07,
        "attraction_and_freedom": 0.07,
        "recognition_and_warmth": 0.05,
        "emotional_support": 0.05,
        "communication_vs_feelings": 0.05,
        "initiative_and_friction": 0.03,
        "responsibility_and_recognition": 0.03,
        "mutual_inspiration": 0.03,
        "shared_language": 0.02,
    },
    "friendship": {
        "shared_language": 0.08,
        "communication_vs_feelings": 0.07,
        "initiative_and_friction": 0.07,
        "mutual_inspiration": 0.07,
        "emotional_support": 0.05,
        "responsibility_and_recognition": 0.04,
        "closeness_and_boundaries": 0.04,
        "feelings_and_action": 0.03,
        "rhythm_of_closeness": 0.03,
        "desire_and_pace": 0.02,
        "attraction_and_freedom": 0.02,
        "recognition_and_warmth": 0.02,
    },
    "family": {
        "responsibility_and_recognition": 0.08,
        "closeness_and_boundaries": 0.08,
        "communication_vs_feelings": 0.07,
        "feelings_and_action": 0.06,
        "emotional_support": 0.06,
        "initiative_and_friction": 0.05,
        "rhythm_of_closeness": 0.04,
        "shared_language": 0.04,
        "recognition_and_warmth": 0.03,
        "mutual_inspiration": 0.03,
        "attraction_and_freedom": 0.02,
        "desire_and_pace": 0.0,
    },
}
_STATUS_THEMES = {
    ("romantic", "crush"): {"desire_and_pace", "attraction_and_freedom", "recognition_and_warmth"},
    ("romantic", "dating"): {"communication_vs_feelings", "desire_and_pace", "closeness_and_boundaries"},
    ("romantic", "together"): {"feelings_and_action", "rhythm_of_closeness", "initiative_and_friction", "emotional_support"},
    ("romantic", "uncertain"): {"closeness_and_boundaries", "communication_vs_feelings", "attraction_and_freedom"},
    ("romantic", "ended"): {"attraction_and_freedom", "closeness_and_boundaries"},
    ("friendship", "new"): {"shared_language", "mutual_inspiration", "initiative_and_friction"},
    ("friendship", "close"): {"emotional_support", "shared_language", "feelings_and_action"},
    ("friendship", "distant"): {"closeness_and_boundaries", "communication_vs_feelings"},
    ("friendship", "ended"): {"shared_language", "responsibility_and_recognition"},
    ("family", "active"): {"responsibility_and_recognition", "emotional_support", "closeness_and_boundaries"},
    ("family", "strained"): {"communication_vs_feelings", "feelings_and_action", "closeness_and_boundaries"},
    ("family", "distant"): {"closeness_and_boundaries", "responsibility_and_recognition"},
    ("family", "no_contact"): {"closeness_and_boundaries", "communication_vs_feelings"},
}
_QUESTION_TOKENS = {
    "communication_vs_feelings": ("говор", "поня", "ясн", "объясн"),
    "desire_and_pace": ("притяж", "желан", "сближ"),
    "closeness_and_boundaries": ("границ", "дистанц", "довер"),
    "initiative_and_friction": ("инициатив", "спор"),
    "attraction_and_freedom": ("свобод", "простран"),
    "shared_language": ("шут", "язык"),
    "feelings_and_action": ("поддерж", "исправ"),
    "rhythm_of_closeness": ("ритм", "привыч"),
    "recognition_and_warmth": ("признан", "тепл"),
    "emotional_support": ("забот", "поддерж"),
    "mutual_inspiration": ("вдохнов", "замыс"),
    "responsibility_and_recognition": ("ответствен", "надёж", "надеж"),
}
_STATUS_BONUS = 0.12
_QUESTION_BONUS = 0.08
_DISTINCT_BONUS = 0.05

_ANGLES = {
    "initiative_and_friction": "Согласие о шаге может появиться раньше, чем согласие о смысле этого шага.",
    "desire_and_pace": "Интерес и темп сближения могут совпасть раньше, чем смысл этого интереса.",
    "communication_vs_feelings": "Ясность и отклик могут приходить в разные моменты одного разговора.",
    "feelings_and_action": "Отклик и действие могут включаться так быстро, что между ними не остаётся паузы.",
    "rhythm_of_closeness": "Повтор входа в контакт может быть заметнее, чем любой отдельный разговор.",
    "recognition_and_warmth": "Признание и тепло могут приходить не в той форме, в которой их ждут.",
    "attraction_and_freedom": "Яркость контакта не отвечает на вопрос, сколько воздуха каждому нужно.",
    "closeness_and_boundaries": "Желание приблизиться и потребность в границе могут звучать одновременно.",
    "emotional_support": "Забота может совпадать по способу и всё равно не обещать одинаковых планов.",
    "mutual_inspiration": "Замысел и шаг могут начаться вместе, ещё до проверки, выдерживает ли их масштаб.",
    "shared_language": "Общая формулировка может появиться быстрее, чем общее решение.",
    "responsibility_and_recognition": "Опора может звучать как признание и как проверка в одном разговоре.",
}


def theme_for(point_a: str, point_b: str, aspect: str, relationship: str = "romantic") -> Optional[str]:
    pair = frozenset((point_a, point_b))
    soft = aspect in {"trine", "sextile"}
    hard = aspect in {"square", "opposition"}
    contact = aspect in {"conjunction", "sextile", "square", "trine", "opposition"}
    if not contact:
        return None
    if point_a == point_b == "mercury":
        return "shared_language" if soft else None
    if point_a == point_b == "moon":
        return "rhythm_of_closeness"
    if point_a == point_b == "venus":
        return "recognition_and_warmth"
    if point_a == point_b == "mars":
        return "initiative_and_friction"
    if pair == frozenset(("mercury", "moon")):
        return "communication_vs_feelings"
    if pair == frozenset(("moon", "mars")):
        return "feelings_and_action"
    if pair == frozenset(("sun", "moon")):
        return "rhythm_of_closeness"
    if pair == frozenset(("venus", "mars")):
        # В семье это темп участия, не романтическое желание.
        return "initiative_and_friction" if relationship == "family" else "desire_and_pace"
    if pair == frozenset(("mercury", "venus")):
        return "shared_language" if soft else "communication_vs_feelings"
    if pair == frozenset(("sun", "venus")):
        return "recognition_and_warmth"
    if pair in {frozenset(("sun", "mars")), frozenset(("mars", "mercury")), frozenset(("mars", "uranus"))}:
        return "initiative_and_friction"
    if pair in {
        frozenset(("venus", "uranus")),
        frozenset(("sun", "uranus")),
        frozenset(("mercury", "uranus")),
    }:
        return "attraction_and_freedom"
    if pair == frozenset(("mercury", "sun")) and soft:
        return "shared_language"
    if pair == frozenset(("mercury", "sun")) and hard:
        return "communication_vs_feelings"
    if pair == frozenset(("moon", "venus")) and soft:
        return "emotional_support"
    if "jupiter" in pair and (pair & PERSONAL) and (soft or aspect == "conjunction"):
        return "mutual_inspiration"
    if pair & NODES and pair & {"venus", "moon"}:
        return "closeness_and_boundaries"
    if "saturn" in pair and pair & {"venus", "moon"}:
        return "closeness_and_boundaries"
    if "saturn" in pair and pair & PERSONAL:
        return "responsibility_and_recognition"
    return None


def pair_weight(point_a: str, point_b: str) -> float:
    pair = {point_a, point_b}
    if pair <= PERSONAL:
        return 1.30
    if (point_a in PERSONAL and point_b in SOCIAL) or (point_b in PERSONAL and point_a in SOCIAL):
        return 1.10
    if (point_a in PERSONAL and point_b in SLOW) or (point_b in PERSONAL and point_a in SLOW):
        return 1.00
    if (point_a in PERSONAL and point_b in ANGLES) or (point_b in PERSONAL and point_a in ANGLES):
        return 1.05
    if point_a in NODES or point_b in NODES:
        return 0.90
    if pair <= SOCIAL:
        return 0.70
    if pair <= SLOW:
        return 0.0
    return 0.0


def aspect_signal(aspect: dict[str, Any]) -> Optional[float]:
    orb = aspect.get("orb_deg")
    allowed = aspect.get("allowed_orb_deg")
    if not isinstance(orb, (int, float)) or not isinstance(allowed, (int, float)) or allowed <= 0:
        return None
    closeness = max(0.0, min(1.0, 1.0 - float(orb) / float(allowed)))
    weight = pair_weight(str(aspect.get("person_a_point") or ""), str(aspect.get("person_b_point") or ""))
    if weight <= 0:
        return None
    return (0.5 + 0.5 * closeness) * weight


def astro_score(signals: list[float]) -> float:
    ordered = sorted(signals, reverse=True)[:3]
    return sum(signal * _DISCOUNT[index] for index, signal in enumerate(ordered))


def rank_openings(document: dict[str, Any]) -> list[dict[str, Any]]:
    relationship, status = _relationship(document)
    question = _question(document)
    grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for aspect in _canonical_aspects(document):
        theme = theme_for(
            str(aspect.get("person_a_point") or ""),
            str(aspect.get("person_b_point") or ""),
            str(aspect.get("aspect") or ""),
            relationship,
        )
        signal = aspect_signal(aspect)
        if theme is None or signal is None:
            continue
        grouped.setdefault(theme, []).append((signal, aspect))
    ranked = []
    focus_table = _FOCUS.get(relationship, _FOCUS["romantic"])
    for theme, rows in grouped.items():
        rows = _collapse_node_twins(rows)
        rows.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
        chosen = rows[:3]
        aspects = [item[1] for item in chosen]
        astro = astro_score([item[0] for item in chosen])
        focus = float(focus_table.get(theme, 0.0))
        status_match = _STATUS_BONUS if theme in _STATUS_THEMES.get((relationship, status), ()) else 0.0
        distinct = _distinctiveness(aspects)
        question_match = _question_match(theme, question)
        final = astro + focus + status_match + distinct + question_match
        ranked.append(
            {
                "theme_id": theme,
                "polarity": _polarity(aspects),
                "aspects": aspects,
                "astro_score": round(astro, 6),
                "relationship_focus": round(focus, 6),
                "status_match": round(status_match, 6),
                "distinctiveness": round(distinct, 6),
                "question_match": round(question_match, 6),
                "final_score": round(final, 6),
                "scoring_version": SCORING_VERSION,
            }
        )
    ranked.sort(key=lambda item: (-item["final_score"], -item["astro_score"], -len(item["aspects"]), item["theme_id"]))
    return ranked


def select_opening(document: dict[str, Any]) -> Optional[dict[str, Any]]:
    ranked = rank_openings(document)
    if not ranked:
        return None
    return ranked[0]


def insight_copy(
    theme: str,
    polarity: str,
    relationship: str,
    name_a: str,
    name_b: str,
    status: Optional[str] = None,
) -> tuple[str, str]:
    rel = relationship if relationship in {"romantic", "friendship", "family"} else "romantic"
    key_polarity = _copy_polarity(theme, polarity)
    found = _STATUS_TEXTS.get((theme, key_polarity, rel, status or "")) if status else None
    if found is None:
        found = _TEXTS.get((theme, key_polarity, rel))
    if found is None and rel != "family":
        found = _TEXTS.get((theme, key_polarity, "romantic"))
    if found is None:
        found = _TEXTS[("communication_vs_feelings", "neutral", rel if rel == "family" else "romantic")]
    headline, body = found
    return headline, body.replace("{a}", name_a).replace("{b}", name_b)


def angle_for(theme: str, relationship: str, status: Optional[str]) -> str:
    base = _ANGLES.get(theme, "Одна гипотеза о повторяющемся рисунке контакта.")
    if relationship == "romantic" and status == "crush":
        return base + " Не предполагай взаимность."
    if relationship == "romantic" and status == "dating":
        return base + " Не присваивай статус пары."
    if relationship == "romantic" and status == "uncertain":
        return base + " Не угадывай мотив другого человека."
    if relationship == "romantic" and status == "ended":
        return base + " Не называй причину расставания и не обещай возврат."
    if relationship == "family":
        return base + " Без романтики и сексуального смысла."
    if relationship == "friendship" and theme == "desire_and_pace":
        return "Увлечённость общим делом может обгонять договорённость о темпе. Без сексуального притяжения."
    return base


def claim_lists(theme: str) -> dict[str, list[str]]:
    return {
        "allowed_claims": list(_ALLOWED.get(theme, _ALLOWED["communication_vs_feelings"])),
        "forbidden_claims": [
            "Чужие чувства, мотивы и решения как установленный факт",
            "Астрология как доказанная причина отказа или расставания",
            "Страх близости как объяснение выбора другого человека",
        ],
    }


def _canonical_aspects(document: dict[str, Any]) -> list[dict[str, Any]]:
    chart = document.get("chart") if isinstance(document.get("chart"), dict) else {}
    rows = chart.get("cross_aspects") if isinstance(chart, dict) else []
    status = _time_status(document)
    aspects = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("direction") != "A_to_B":
            continue
        if row.get("bond_eligible") is False:
            continue
        if not _point_reliable(str(row.get("person_a_point") or ""), status.get("A")):
            continue
        if not _point_reliable(str(row.get("person_b_point") or ""), status.get("B")):
            continue
        aspects.append(row)
    return aspects


def _time_status(document: dict[str, Any]) -> dict[str, str]:
    status = {"A": "known", "B": "known"}
    for row in document.get("persons") or []:
        if isinstance(row, dict) and row.get("id") in status:
            status[str(row["id"])] = str(row.get("birth_time_status") or "known")
    return status


def _point_reliable(point: str, status: Optional[str]) -> bool:
    if point in {"asc", "mc"} and status != "known":
        return False
    if point == "moon" and status == "unknown":
        return False
    return True


def _relationship(document: dict[str, Any]) -> tuple[str, str]:
    context = document.get("relationship_context") if isinstance(document.get("relationship_context"), dict) else {}
    relationship = str(document.get("relationship_type") or context.get("type") or "romantic")
    if relationship not in _FOCUS:
        relationship = "romantic"
    return relationship, str(context.get("status") or "")


def _question(document: dict[str, Any]) -> str:
    context = document.get("relationship_context") if isinstance(document.get("relationship_context"), dict) else {}
    return str(context.get("user_question") or "").casefold()


def _question_match(theme: str, question: str) -> float:
    if not question:
        return 0.0
    return _QUESTION_BONUS if any(token in question for token in _QUESTION_TOKENS.get(theme, ())) else 0.0


def _distinctiveness(aspects: list[dict[str, Any]]) -> float:
    pairs = {
        frozenset((str(row.get("person_a_point") or ""), str(row.get("person_b_point") or "")))
        for row in aspects
    }
    if len(aspects) >= 2 and len(pairs) >= 2:
        return _DISTINCT_BONUS
    return 0.0


def _node_signature(aspect: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    point_a = str(aspect.get("person_a_point") or "")
    point_b = str(aspect.get("person_b_point") or "")
    name = str(aspect.get("aspect") or "")
    if point_a in NODES and point_b not in NODES:
        node, other, side = point_a, point_b, "a"
    elif point_b in NODES and point_a not in NODES:
        node, other, side = point_b, point_a, "b"
    else:
        return None
    activation = {
        ("north_node", "sextile"): "soft_north",
        ("south_node", "trine"): "soft_north",
        ("north_node", "trine"): "trine_north",
        ("south_node", "sextile"): "trine_north",
        ("north_node", "conjunction"): "hard_north",
        ("south_node", "opposition"): "hard_north",
        ("north_node", "opposition"): "hard_south",
        ("south_node", "conjunction"): "hard_south",
        ("north_node", "square"): "square",
        ("south_node", "square"): "square",
    }.get((node, name))
    if activation is None:
        return None
    return (side, other, activation)


def _collapse_node_twins(rows: list[tuple[float, dict[str, Any]]]) -> list[tuple[float, dict[str, Any]]]:
    best: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
    plain = []
    for signal, aspect in rows:
        signature = _node_signature(aspect)
        if signature is None:
            plain.append((signal, aspect))
            continue
        current = best.get(signature)
        if current is None or signal > current[0] or (
            signal == current[0] and str(aspect.get("id") or "") < str(current[1].get("id") or "")
        ):
            best[signature] = (signal, aspect)
    return plain + list(best.values())


def _polarity(aspects: list[dict[str, Any]]) -> str:
    qualities = {aspect.get("quality") for aspect in aspects}
    if qualities == {"harmonizing"}:
        return "supportive"
    if qualities == {"tension"}:
        return "challenging"
    if "tension" in qualities and ("harmonizing" in qualities or "mixed" in qualities):
        return "mixed"
    if "harmonizing" in qualities and "mixed" in qualities:
        return "mixed"
    return "neutral"


def _copy_polarity(theme: str, polarity: str) -> str:
    if polarity == "mixed":
        return "neutral"
    # Соединение с Юпитером — встреча масштаба и шага, не автоматически мягкий ресурс.
    if polarity == "neutral" and theme in SOFT_THEMES and theme != "mutual_inspiration":
        return "supportive"
    if polarity in {"supportive", "challenging", "neutral"}:
        return polarity
    return "supportive" if theme in SOFT_THEMES else "neutral"


_ALLOWED = {
    "communication_vs_feelings": ["Ясность и отклик могут приходить в разные моменты одного разговора"],
    "emotional_support": ["Забота может совпадать по способу и не обещать одинаковых планов"],
    "mutual_inspiration": ["Замысел и шаг могут начаться вместе, ещё до проверки масштаба"],
    "closeness_and_boundaries": ["Желание приблизиться и потребность в границе могут звучать одновременно"],
    "initiative_and_friction": ["Согласие о шаге может опережать согласие о его смысле"],
    "attraction_and_freedom": ["Яркость контакта не отвечает, сколько воздуха каждому нужно"],
    "shared_language": ["Общая формулировка может появиться быстрее, чем общее решение"],
    "responsibility_and_recognition": ["Опора может звучать как признание и как проверка"],
    "desire_and_pace": ["Интерес и темп сближения могут совпасть раньше, чем смысл интереса"],
    "feelings_and_action": ["Отклик и действие могут включаться без паузы между ними"],
    "rhythm_of_closeness": ["Повтор входа в контакт может быть заметнее отдельного разговора"],
    "recognition_and_warmth": ["Признание и тепло могут приходить не в ожидаемой форме"],
}

# Полные тексты, не склейка обрывков. {a} и {b} остаются подлежащими.
_TEXTS: dict[tuple[str, str, str], tuple[str, str]] = {}
_STATUS_TEXTS: dict[tuple[str, str, str, str], tuple[str, str]] = {}


def _add(theme: str, polarity: str, relationship: str, headline: str, body: str) -> None:
    _TEXTS[(theme, polarity, relationship)] = (headline, body)


_add(
    "communication_vs_feelings",
    "challenging",
    "romantic",
    "Один разговор может значить для вас разное",
    "{a} может объяснять, пока {b} ещё отвечает на тон сказанного. Слова тогда задевают сильнее, чем была задумана ясность. Это возможная чувствительная точка связи, а не причина чьего-то решения.",
)
_add(
    "communication_vs_feelings",
    "challenging",
    "friendship",
    "Шутка и поддержка могут не совпасть по времени",
    "{a} может свернуть разговор к решению, когда {b} ещё ждёт, что его просто услышат. В дружбе это легко выглядит как лёгкость, за которой не замечают обиду. Это гипотеза о ритме разговора, не о скрытых чувствах.",
)
_add(
    "communication_vs_feelings",
    "challenging",
    "family",
    "Замечание и объяснение могут приходить в разный момент",
    "В семье {a} может сразу прояснять, а {b} сначала реагирует на тон. Один разговор тогда оставляет два разных ощущения. Это привычный рисунок ролей, а не приговор кому-то из вас.",
)
_add(
    "communication_vs_feelings",
    "supportive",
    "romantic",
    "Слова и чувства здесь могут успевать друг за другом",
    "{a} и {b} могут быстрее замечать, когда разговору нужно тепло, а когда ясность. Объяснение не обязано спорить с откликом. Это устойчивая особенность вашей связи, а не событие одного дня.",
)
_add(
    "communication_vs_feelings",
    "supportive",
    "friendship",
    "Вам может быть легко говорить и о деле, и о себе",
    "{a} может назвать мысль, а {b} — услышать, что за ней стоит. В дружбе такой разговор помогает и решать, и поддерживать. Это свойство вашего общения, а не обещание, что обид не будет.",
)
_add(
    "communication_vs_feelings",
    "supportive",
    "family",
    "В семье слова могут доходить вместе с заботой",
    "{a} может объяснять так, что {b} слышит не только довод, но и участие. Разговор о делах тогда не обязан становиться проверкой. Это возможная опора вашей семейной связи.",
)
_add(
    "communication_vs_feelings",
    "neutral",
    "romantic",
    "Разговор между вами может становиться особенно заметным",
    "{a} и {b}: способ объяснять и эмоциональный отклик встречаются в одной теме. Само по себе это не говорит, легко вам или трудно. Это устойчивый рисунок связи, а не событие конкретного дня.",
)
_add(
    "communication_vs_feelings",
    "neutral",
    "friendship",
    "В дружбе разговор может становиться самой заметной темой",
    "{a} и {b} могут часто встречаться именно в том, как сказано, а не только в том, о чём речь. Это не оценка, кто из вас внимательнее. Это устойчивая особенность вашего общения.",
)
_add(
    "communication_vs_feelings",
    "neutral",
    "family",
    "Семейный разговор может держаться на разном темпе ответа",
    "{a} и {b} могут по-разному входить в одну и ту же тему: кто-то через объяснение, кто-то через реакцию. Это не говорит, кто прав. Это привычный рисунок вашей семьи.",
)
_add(
    "emotional_support",
    "supportive",
    "romantic",
    "Тепло между вами может находиться без долгого перевода",
    "{a} и {b} могут похожим образом замечать, когда другому нужна поддержка. Забота здесь способна совпадать с тем, как её принимают. Это сильная сторона связи, а не гарантия одинаковых планов.",
)
_add(
    "emotional_support",
    "supportive",
    "friendship",
    "В дружбе вам может быть естественно поддерживать друг друга",
    "{a} может предлагать участие так, что {b} его узнаёт. Поддержка не обязана превращаться в совет. Это ресурс вашей дружбы, особенно когда одному просто нужно быть услышанным.",
)
_add(
    "emotional_support",
    "supportive",
    "family",
    "В семье забота может быть вашим общим языком",
    "{a} и {b} могут замечать нужду другого и отвечать участием. Тепло здесь не обязано становиться контролем. Это возможная опора родственной связи, если у каждого остаётся свой шаг.",
)
_add(
    "mutual_inspiration",
    "supportive",
    "romantic",
    "Рядом с другим ваши идеи могут становиться смелее",
    "{a} может начинать, а {b} — расширять то, что уже начато. Интерес одного способен разгонять замысел другого. Это сильная сторона связи, а не обещание общего будущего.",
)
_add(
    "mutual_inspiration",
    "supportive",
    "friendship",
    "В дружбе вам может быть интересно разгонять замыслы друг друга",
    "{a} приносит ход, {b} видит, куда его можно развить. Вместе начинать новое может быть легче, чем поодиночке. Это ресурс дружбы, а не обязанность всегда соглашаться.",
)
_add(
    "mutual_inspiration",
    "supportive",
    "family",
    "В семье один замысел может находить продолжение у другого",
    "{a} может предлагать направление, а {b} — видеть в нём больше возможностей. Родственный разговор тогда поддерживает инициативу, а не только проверяет её. Это возможная общая сила вашей семьи.",
)
_add(
    "shared_language",
    "supportive",
    "romantic",
    "Вашим мыслям может становиться просторнее в разговоре",
    "{a} начинает мысль, {b} может быстро подхватить её направление. Общий язык здесь способен быть сильной стороной связи. Это не значит, что вы хотите одного и того же дальше.",
)
_add(
    "shared_language",
    "supportive",
    "friendship",
    "Вам может быть легко подхватывать мысли друг друга",
    "В дружбе {a} может начать фразу, а {b} уже понимает, куда она ведёт. Так удобно придумывать что-то вместе. Интеллектуальное совпадение не отвечает за одинаковые эмоциональные ожидания.",
)
_add(
    "shared_language",
    "supportive",
    "family",
    "В семье вам может быть легче договариваться словами",
    "{a} и {b} могут быстрее находить общую формулировку, чем общий приказ. Разговор помогает прояснять, а не только распределять роли. Это возможная опора вашей родственной связи.",
)
_add(
    "closeness_and_boundaries",
    "challenging",
    "romantic",
    "Желание быть ближе может встречать другой темп",
    "{a} может искать определённость там, где {b} сначала держит границу. Больше усилий не обязано создавать больше встречного движения. Это возможный ритм связи, а не вердикт о чувствах.",
)
_add(
    "closeness_and_boundaries",
    "challenging",
    "friendship",
    "Дружба может быть надёжной и при этом сдержанной",
    "{a} может ждать более открытого участия, а {b} — проявлять его делом или дистанцией. Надёжность здесь не всегда равна теплу. Это гипотеза о темпе дружбы, не о предательстве.",
)
_add(
    "closeness_and_boundaries",
    "challenging",
    "family",
    "Забота в семье может упираться в границу",
    "{a} может приближаться с участием, а {b} — нуждаться в собственном шаге. Даже добрая настойчивость иногда звучит как контроль. Это привычная развилка ролей, а не оценка чьей-то любви.",
)
_add(
    "closeness_and_boundaries",
    "supportive",
    "romantic",
    "Близость здесь может уживаться с уважением к паузе",
    "{a} и {b} способны быть рядом, не требуя одинаковой скорости. Граница одного не отменяет интерес другого. Это возможная устойчивость связи, а не холод.",
)
_add(
    "closeness_and_boundaries",
    "supportive",
    "friendship",
    "В дружбе дистанция не обязана отменять верность",
    "{a} может давать пространство, а {b} — чувствовать, что связь от этого не распадается. Надёжность здесь держится и на паузе. Это ресурс дружбы, если ожидания названы вслух.",
)
_add(
    "closeness_and_boundaries",
    "supportive",
    "family",
    "В семье близость может сохраняться и при отдельных жизнях",
    "{a} и {b} могут оставаться на связи, не занимая весь день друг друга. Граница здесь способна защищать, а не отвергать. Это возможная взрослая форма родственной заботы.",
)
_add(
    "closeness_and_boundaries",
    "neutral",
    "romantic",
    "Между близостью и паузой у вас может быть своя мера",
    "{a} и {b} по-разному решают, когда приблизиться, а когда оставить пространство. Это не говорит, кто теплее. Это устойчивая тема вашей связи, а не событие одного дня.",
)
_add(
    "closeness_and_boundaries",
    "neutral",
    "friendship",
    "В дружбе у каждого может быть свой темп участия",
    "{a} и {b} не обязаны одинаково часто писать и встречаться, чтобы связь оставалась настоящей. Тема здесь — мера близости. Это не вывод о том, кто кому меньше нужен.",
)
_add(
    "closeness_and_boundaries",
    "neutral",
    "family",
    "В семье у заботы и отдельности может быть общий сюжет",
    "{a} и {b} могут по-разному понимать, сколько участия уместно. Это не спор о том, кто любит сильнее. Это устойчивая семейная тема границ.",
)
_add(
    "initiative_and_friction",
    "challenging",
    "romantic",
    "Ваш темп действия может спорить с темпом ответа",
    "{a} может ускорять шаг, а {b} — отвечать так резко или так медленно, что начинается спор о том, кто ведёт. Стимул здесь легко становится соревнованием. Это ритм контакта, а не чей-то злой умысел.",
)
_add(
    "initiative_and_friction",
    "challenging",
    "friendship",
    "Споры в дружбе могут начинаться как игра за последнее слово",
    "{a} предлагает ход, {b} сразу видит, как сделать иначе. Пока это взаимно, дружба заряжается. Если после каждой встречи нужно победить, поддержка отходит на второй план.",
)
_add(
    "initiative_and_friction",
    "challenging",
    "family",
    "Семейное решение может снова становиться спором о темпе",
    "{a} может торопить с действием, а {b} — отвечать сопротивлением или встречным планом. Старое соревнование тогда возвращается за общим столом. Это рисунок ролей, а не доказательство, кто главный.",
)
_add(
    "initiative_and_friction",
    "supportive",
    "romantic",
    "Согласие о шаге может опережать согласие о смысле",
    "{a} и {b} могут перевести намерение в движение быстрее, чем станет ясно, зачем оно вам. Слаженность шага ещё не значит, что вы хотите одного результата. Общий ход здесь легче найти, чем общий смысл.",
)
_add(
    "initiative_and_friction",
    "supportive",
    "friendship",
    "Один запускает идею, другой помогает ей случиться",
    "В дружбе {a} может начинать, а {b} — видеть, как мысль становится делом. Инициатива одного не гасится, а получает продолжение. Это ресурс, когда вам интересно делать что-то вместе.",
)
_add(
    "initiative_and_friction",
    "supportive",
    "family",
    "В семье один предлагает шаг, другой помогает его удержать",
    "{a} может начинать, а {b} — придавать решению понятную форму. Действие тогда не обязано превращаться в спор о власти. Это возможная совместная сила вашей семьи.",
)
_add(
    "initiative_and_friction",
    "neutral",
    "romantic",
    "Действие и ответ между вами могут быть очень заметными",
    "{a} и {b} быстро включают друг друга: один начинает, другой не остаётся в стороне. Это не приговор, легко вам или тесно. Это устойчивый ритм связи.",
)
_add(
    "initiative_and_friction",
    "neutral",
    "friendship",
    "В дружбе вы можете сильно разгонять темп друг друга",
    "{a} и {b} редко оставляют инициативу без ответа. Разговор быстро переходит в действие или в спор о способе. Это заметная черта дружбы, а не оценка характеров.",
)
_add(
    "initiative_and_friction",
    "neutral",
    "family",
    "В семье темп решений может сразу становиться общим делом",
    "{a} и {b} легко включают друг друга, как только кто-то предлагает шаг. Дальше важно, остаётся ли место для двух способов. Это семейный ритм, а не ярлык старшинства.",
)
_add(
    "attraction_and_freedom",
    "challenging",
    "romantic",
    "Интерес здесь может соседствовать с потребностью в воздухе",
    "{a} может хотеть больше ясности, а {b} — больше собственного пространства. Яркость контакта не делает темп одинаковым. Это возможная развилка связи, а не доказательство чужих чувств.",
)
_add(
    "attraction_and_freedom",
    "challenging",
    "friendship",
    "Дружба может вспыхивать и тут же требовать паузы",
    "{a} тянется к частым встречам, {b} может восстанавливаться в одиночестве. Интерес от этого не исчезает, но ожидания легко расходятся. Это гипотеза о ритме, не о скрытой обиде.",
)
_add(
    "attraction_and_freedom",
    "challenging",
    "family",
    "Семейная вовлечённость может спорить с потребностью в своём темпе",
    "{a} может чаще звать к общему, а {b} — беречь отдельное пространство. Это не отказ от родственной связи. Это разница, сколько присутствия каждому нужно.",
)
_add(
    "attraction_and_freedom",
    "supportive",
    "romantic",
    "Интерес может оставаться живым, даже если у каждого есть свой воздух",
    "{a} и {b} способны держаться контакта, не занимая всю свободу другого. Пауза здесь не обязана означать охлаждение. Это возможная форма вашей связи.",
)
_add(
    "attraction_and_freedom",
    "supportive",
    "friendship",
    "Дружба может выдерживать и встречи, и свободные промежутки",
    "{a} и {b} не теряют нить, если кто-то на время занят своей жизнью. Интерес держится без постоянного контроля. Это ресурс дружбы при разном ритме.",
)
_add(
    "attraction_and_freedom",
    "supportive",
    "family",
    "В семье можно быть рядом и не сливать расписания",
    "{a} и {b} могут сохранять участие, оставляя друг другу собственный ход дня. Отдельность здесь не отменяет родство. Это возможная взрослая договорённость.",
)
_add(
    "attraction_and_freedom",
    "neutral",
    "romantic",
    "Между интересом и свободой у вас может быть отдельная тема",
    "{a} и {b} по-разному чувствуют, сколько контакта достаточно. Это не отчёт о чужих намерениях. Это устойчивый рисунок связи, а не событие одной недели.",
)
_add(
    "attraction_and_freedom",
    "neutral",
    "friendship",
    "В дружбе частота общения может быть отдельным вопросом",
    "{a} и {b} не обязаны хотеть одинаковой плотности встреч. Тема здесь — сколько свободы нужно контакту. Это не вывод, кто кому важнее.",
)
_add(
    "attraction_and_freedom",
    "neutral",
    "family",
    "В семье мера участия может быть заметнее самих новостей",
    "{a} и {b} по-разному выбирают, когда быть вместе, а когда жить свой день. Это не оценка привязанности. Это устойчивая семейная тема пространства.",
)
_add(
    "responsibility_and_recognition",
    "challenging",
    "romantic",
    "Забота здесь может звучать как проверка",
    "{a} может приносить план, а {b} — сначала видеть риски и условия. Поддержка тогда ощущается как оценка. Это возможный рисунок связи, а не доказательство, что кого-то не ценят.",
)
_add(
    "responsibility_and_recognition",
    "challenging",
    "friendship",
    "Дружеский совет может превращаться в разбор ошибок",
    "{a} делится решением, {b} отвечает списком поправок. Польза есть, но признание легко теряется. Это гипотеза о форме поддержки, не о скрытом превосходстве.",
)
_add(
    "responsibility_and_recognition",
    "challenging",
    "family",
    "Ты делишься решением, а разговор может стать проверкой",
    "{a} приносит план, {b} может привычно обсуждать риски. Для одного это снова звучит как оценка, для другого — как участие. Один разговор оставляет два разных ощущения заботы.",
)
_add(
    "responsibility_and_recognition",
    "supportive",
    "romantic",
    "Надёжность между вами может быть формой признания",
    "{a} может опираться на то, что {b} держит слово и видит последствия. Серьёзность здесь не обязана быть холодом. Это возможная опора связи.",
)
_add(
    "responsibility_and_recognition",
    "supportive",
    "friendship",
    "В дружбе на вас можно положиться, когда дело становится серьёзным",
    "{a} приносит вопрос, {b} помогает увидеть рамку и следующий шаг. Поддержка здесь конкретная. Это ресурс дружбы, если рядом остаётся и простое признание.",
)
_add(
    "responsibility_and_recognition",
    "supportive",
    "family",
    "В семье опора может звучать как признание, а не только как совет",
    "{a} и {b} способны вместе смотреть на последствия и при этом замечать усилие друг друга. Ответственность тогда не сводится к оценке. Это возможная сила вашей родственной связи.",
)
_add(
    "responsibility_and_recognition",
    "neutral",
    "romantic",
    "Тема долга и признания между вами может быть очень слышной",
    "{a} и {b} часто встречаются там, где один ждёт опоры, а другой смотрит на правила и последствия. Это не говорит, кто заботливее. Это устойчивый сюжет связи.",
)
_add(
    "responsibility_and_recognition",
    "neutral",
    "friendship",
    "В дружбе поддержка может идти через дело и через оценку",
    "{a} и {b} заметно включают ответственность, когда речь о планах. Форма этой поддержки бывает разной. Это черта вашей дружбы, а не диагноз.",
)
_add(
    "responsibility_and_recognition",
    "neutral",
    "family",
    "В семье признание и требования могут идти одной связкой",
    "{a} и {b} часто обсуждают, кто что выдержит и кто что заметит. Это не приговор о любви. Это привычная семейная тема ответственности.",
)


def _add_status(theme: str, polarity: str, relationship: str, status: str, headline: str, body: str) -> None:
    _STATUS_TEXTS[(theme, polarity, relationship, status)] = (headline, body)


_add(
    "desire_and_pace",
    "supportive",
    "romantic",
    "Интерес может совпасть раньше, чем вы его назовёте",
    "{a} и {b} могут включить сближение и движение почти сразу. Ясность, взаимно ли это и куда ведёт, появляется позже. Совпавший темп ещё не отвечает, хотите ли вы одного и того же.",
)
_add(
    "desire_and_pace",
    "challenging",
    "romantic",
    "Пауза здесь легко выглядит как отказ",
    "Интерес между {a} и {b} может быть заметным и всё равно идти в разном темпе. Чем сильнее кто-то подстраивается, тем легче принять чужой шаг за холодность. Больше усилий не обязано создать больше встречного движения.",
)
_add(
    "desire_and_pace",
    "neutral",
    "romantic",
    "Интерес здесь сильнее договорённости о темпе",
    "{a} и {b} могут быстро включаться и при этом не в одну сторону. Сближение и действие здесь заметны раньше, чем их общий смысл. Это ещё не говорит, кто хочет большего.",
)
_add(
    "desire_and_pace",
    "supportive",
    "friendship",
    "Увлечённость может обгонять общий темп",
    "В дружбе {a} и {b} могут загораться общим делом быстрее, чем договариваются, как его вести. Скорость интереса сама по себе не делает ожидания одинаковыми. Это про темп участия, не про характер одного из вас.",
)
_add(
    "desire_and_pace",
    "challenging",
    "friendship",
    "Разная скорость участия может выглядеть как охлаждение",
    "{a} и {b} могут хотеть одного дела и всё равно включаться в разный момент. Пауза тогда легко читается как потеря интереса. Это спор о темпе дружбы, не о тайной обиде.",
)
_add(
    "desire_and_pace",
    "neutral",
    "friendship",
    "Общее дело может зажигаться быстрее договорённости",
    "{a} и {b} заметно разгоняют друг друга, когда появляется идея что-то сделать вместе. Куда именно вести этот разгон, может оставаться неясным. Это черта темпа вашей дружбы.",
)
_add(
    "desire_and_pace",
    "supportive",
    "family",
    "В семье включаться вместе может быть легче, чем договориться о темпе",
    "{a} и {b} могут быстро переходить от разговора к общему делу. Вопрос, всем ли подходит эта скорость, возникает уже по ходу. Совместный ход не отменяет разницу в том, сколько участия каждому нужно.",
)
_add(
    "desire_and_pace",
    "challenging",
    "family",
    "Разная скорость участия легко звучит как холодность",
    "В семье {a} и {b} могут включаться в общий вопрос в разные моменты. Тот, кто ждёт, легко принимает паузу за отказ. Это разница темпа, не оценка чьей-то привязанности.",
)
_add(
    "desire_and_pace",
    "neutral",
    "family",
    "Семейное дело может собирать вас быстрее, чем общий ритм",
    "{a} и {b} заметно реагируют, когда нужно что-то сделать. Насколько этот темп удобен каждому, из самого включения не следует. Это сюжет участия, не ярлык старшинства.",
)
_add(
    "feelings_and_action",
    "supportive",
    "romantic",
    "Отклик и действие у вас могут включаться одной волной",
    "{a} и {b} могут быстро переходить от «меня задело» к конкретному шагу. Помощь тогда приходит сразу, иногда раньше просьбы. Скорость заботы ещё не значит, что вам нужна одна и та же форма поддержки.",
)
_add(
    "feelings_and_action",
    "challenging",
    "romantic",
    "Один ищет, чтобы его услышали, и встречает готовность всё исправить",
    "В трудный момент {a} и {b} могут включать разные ответы: остаться рядом с переживанием или сразу устранять проблему. Искреннее желание помочь тогда становится спором о том, как правильно переживать сложное. Это развилка контакта, не чья-то вина.",
)
_add(
    "feelings_and_action",
    "neutral",
    "romantic",
    "Между чувством и поступком у вас почти нет паузы",
    "{a} и {b} могут отвечать на задетое действием так быстро, что разговор о самом переживании не успевает начаться. Это не говорит, кому из вас тяжелее. Это повторяющийся ритм вашей реакции.",
)
_add(
    "feelings_and_action",
    "supportive",
    "friendship",
    "В дружбе вас может быть легко и поддержать, и сдвинуть с места",
    "{a} и {b} могут заметить, что другому непросто, и сразу предложить шаг. Забота здесь не обязана превращаться в совет. Быстрый отклик ещё не обещает, что вы одинаково понимаете, какая помощь нужна.",
)
_add(
    "feelings_and_action",
    "challenging",
    "friendship",
    "Попытка помочь может обогнать просьбу быть услышанным",
    "{a} и {b} в трудный момент легко переходят к решению, когда другому ещё нужно, чтобы его просто услышали. Действие тогда спорит с откликом. Это разница дружеской поддержки, не скрытая обида.",
)
_add(
    "feelings_and_action",
    "neutral",
    "friendship",
    "В дружбе переживание быстро становится действием",
    "{a} и {b} редко оставляют задетое без хода: разговор почти сразу ищет, что сделать. Иногда это выручает, иногда оставляет чувство невысказанным. Это ваш ритм, не оценка характеров.",
)
_add(
    "feelings_and_action",
    "supportive",
    "family",
    "В семье забота может сразу становиться конкретным шагом",
    "{a} и {b} могут отвечать на трудность делом, не дожидаясь длинного объяснения. Такая помощь бывает точной. Она не заменяет разговор о том, что человеку было важно услышать.",
)
_add(
    "feelings_and_action",
    "challenging",
    "family",
    "Семейная помощь может приходить раньше, чем человека услышали",
    "{a} и {b} в напряжённый момент легко спорят, что нужнее: разобрать проблему или остаться с переживанием. Оба ответа могут быть искренними. Спор начинается о форме, не о том, есть ли участие.",
)
_add(
    "feelings_and_action",
    "neutral",
    "family",
    "В семье чувство и поступок у вас почти не разделяются",
    "{a} и {b} быстро переводят семейное напряжение в действие или в спор о действии. Паузы, чтобы просто назвать переживание, может не остаться. Это привычный рисунок, не приговор о близости.",
)
_add(
    "rhythm_of_closeness",
    "supportive",
    "romantic",
    "Рядом вам может быть понятно, как входить в контакт",
    "{a} и {b} могут повторять один и тот же удобный способ быть рядом, почти не обсуждая его. Эта лёгкость не отвечает, хотите ли вы одинакового будущего. Она говорит только о том, как вы сходитесь.",
)
_add(
    "rhythm_of_closeness",
    "challenging",
    "romantic",
    "Вы можете жить в разных ритмах одного контакта",
    "{a} и {b} могут по-разному входить в близость: одному ближе скорость, другому — повторяемость. Каждому тогда легко решить, что второй рядом «не так». Это разница ритма, не доказательство чужого охлаждения.",
)
_add(
    "rhythm_of_closeness",
    "neutral",
    "romantic",
    "Ваш способ сходиться может повторяться раньше, чем вы его замечаете",
    "{a} и {b} входят в контакт узнаваемым образом: с одного и того же шага, паузы или тона. Насколько этот ритм вам обоим подходит, из самого повтора не следует. Это устойчивый рисунок связи.",
)
_add(
    "rhythm_of_closeness",
    "supportive",
    "friendship",
    "В дружбе вам может быть легко возвращаться в знакомый ритм",
    "{a} и {b} могут возобновлять контакт без долгой раскачки. Привычка сходиться так не обещает одинаковых ожиданий от дружбы. Она только делает встречу узнаваемой.",
)
_add(
    "rhythm_of_closeness",
    "challenging",
    "friendship",
    "Дружба может держаться на ритме, который удобен не обоим",
    "{a} и {b} повторяют один способ общаться, даже когда одному в нём тесно. Знакомый ритм тогда выглядит как сама дружба. На деле это только привычка входа в контакт.",
)
_add(
    "rhythm_of_closeness",
    "neutral",
    "friendship",
    "Ваша дружба может узнаваться по тому, как вы сходитесь",
    "{a} и {b} начинают контакт похожим движением: шуткой, делом или паузой. Этот повтор заметнее отдельных тем. Он не говорит, одинаково ли вам в этой дружбе.",
)
_add(
    "rhythm_of_closeness",
    "supportive",
    "family",
    "В семье вам может быть понятен привычный способ быть рядом",
    "{a} и {b} могут возвращаться к одному тону, даже после паузы. Узнаваемость не отменяет разницу ролей. Она только показывает, как вы обычно входите в контакт.",
)
_add(
    "rhythm_of_closeness",
    "challenging",
    "family",
    "Семейный ритм может быть общим и всё равно тесным",
    "{a} и {b} повторяют один способ сходиться, и кому-то в нём не хватает своего шага. Привычка тогда спорит с дистанцией. Это рисунок семьи, не оценка чьей-то любви.",
)
_add(
    "rhythm_of_closeness",
    "neutral",
    "family",
    "Семейный контакт у вас может начинаться одним и тем же ходом",
    "{a} и {b} узнаваемо входят в разговор: с заботы, с дела или с паузы. Повтор этого входа заметнее содержания. Он не доказывает, всем ли так удобно.",
)
_add(
    "recognition_and_warmth",
    "supportive",
    "romantic",
    "Тепло между вами может приходить без долгого перевода",
    "{a} и {b} могут узнавать внимание друг друга, даже когда оно выражено просто. Эта лёгкость не отвечает, хотите ли вы одного будущего. Она говорит о форме признания, не о решении быть вместе.",
)
_add(
    "recognition_and_warmth",
    "challenging",
    "romantic",
    "Признание может приходить не в той форме, в которой его ждут",
    "{a} и {b} могут проявлять тепло по-разному, и каждый ждёт своего знака. Усилие тогда есть, а ощущение, что его увидели, нет. Это развилка формы заботы, не доказательство равнодушия.",
)
_add(
    "recognition_and_warmth",
    "neutral",
    "romantic",
    "Внимание между вами заметно, но его форма не очевидна",
    "{a} и {b} включают тепло и признание, только не обязательно одним способом. Один жест может быть заботой для одного и нейтральным фактом для другого. Это сюжет формы, не вердикт о чувствах.",
)
_add(
    "recognition_and_warmth",
    "supportive",
    "friendship",
    "В дружбе вам может быть легко замечать вклад друг друга",
    "{a} и {b} могут узнавать внимание без длинных объяснений. Признание здесь не обязано становиться большим разговором о дружбе. Достаточно того, что жест доходит.",
)
_add(
    "recognition_and_warmth",
    "challenging",
    "friendship",
    "Дружеское внимание может не попадать в ожидаемый жест",
    "{a} и {b} могут ценить друг друга и всё равно промахиваться мимо формы. Один ждёт слов, другой показывает это делом. Промах легко принять за отсутствие интереса.",
)
_add(
    "recognition_and_warmth",
    "neutral",
    "friendship",
    "В дружбе признание у вас может идти разными дорогами",
    "{a} и {b} заметно включают внимание, когда другому что-то важно. Совпадает ли форма этого внимания, из самого факта заботы не следует. Это открытый сюжет вашей дружбы.",
)
_add(
    "recognition_and_warmth",
    "supportive",
    "family",
    "В семье внимание может доходить без лишних слов",
    "{a} и {b} могут узнавать заботу в простом жесте. Это не отменяет разницу ролей и не обещает, что каждый жест будет понят. Это возможный тёплый ход вашей семьи.",
)
_add(
    "recognition_and_warmth",
    "challenging",
    "family",
    "Семейная забота может не совпадать с тем, как её ждут",
    "{a} и {b} могут стараться и всё равно попадать мимо нужной формы. Замечание тогда звучит как оценка, а дело — как холодность. Это спор о форме внимания, не о его отсутствии.",
)
_add(
    "recognition_and_warmth",
    "neutral",
    "family",
    "В семье тепло и признание могут идти разными путями",
    "{a} и {b} включают внимание, когда речь о близком человеке. Попадает ли оно в ожидаемый жест, видно только из повтора. Это семейный сюжет формы заботы.",
)
_add(
    "mutual_inspiration",
    "neutral",
    "romantic",
    "Замысел и шаг могут начаться раньше проверки масштаба",
    "{a} и {b} могут раздвинуть идею и сразу перейти к действию. Проверка, выдерживает ли это ваш темп, приходит позже. Совместный разгон ещё не значит, что масштаб вам обоим подходит.",
)
_add(
    "mutual_inspiration",
    "neutral",
    "friendship",
    "В дружбе идея и дело могут стартовать одним движением",
    "{a} и {b} легко расширяют замысел и тут же ищут, с чего начать. Вопрос, не обещали ли вы больше, чем можете удержать, возникает уже в движении. Разгон дружбы не равен её обязательству.",
)
_add(
    "mutual_inspiration",
    "neutral",
    "family",
    "Семейный замысел может сразу становиться общим делом",
    "{a} и {b} могут расширить идею и перейти к шагам, не проверив, всем ли подходит масштаб. Энтузиазм тогда обгоняет распределение сил. Это риск общего разгона, не оценка чьей-то серьёзности.",
)
_add(
    "mutual_inspiration",
    "challenging",
    "romantic",
    "Размер обещания может обогнать ближайший шаг",
    "{a} и {b} могут так быстро увеличить замысел, что проверить его уже некогда. Вдохновение тогда спорит с тем, что реально удержать. Это сюжет масштаба, не чья-то безответственность.",
)
_add(
    "mutual_inspiration",
    "challenging",
    "friendship",
    "Дружеский замысел может обещать больше, чем вы успеваете сделать",
    "{a} и {b} разгоняют идею быстрее, чем появляется ближайший шаг. Потом легко спорить, кто не дотянул. Спор начинается с масштаба, не с отсутствия интереса.",
)
_add(
    "mutual_inspiration",
    "challenging",
    "family",
    "Семейная идея может становиться больше, чем семья может удержать",
    "{a} и {b} легко расширяют план, а проверка сил приходит слишком поздно. Разочарование тогда выглядит как чей-то срыв. На деле масштаб был назначен раньше, чем его выдержали.",
)
_add_status(
    "mutual_inspiration",
    "neutral",
    "romantic",
    "ended",
    "Замысел и шаг могли сходиться раньше проверки масштаба",
    "В этой связи идею и действие могло быть легко запустить вместе, ещё до вопроса о реальном темпе. Яркость разгона не объясняет, почему отношения закончились. Она и не отвечает, что должно было случиться дальше.",
)
_add_status(
    "initiative_and_friction",
    "supportive",
    "romantic",
    "ended",
    "Согласие о шаге могло опережать согласие о смысле",
    "{a} и {b} могли легко переводить намерение в движение и позже обнаруживать, что смысл шага был разным. Этот ритм не причина расставания. Он только показывает, как у вас включалось общее действие.",
)
_add_status(
    "desire_and_pace",
    "challenging",
    "romantic",
    "ended",
    "Разный темп интереса не объясняет конец",
    "Сближение и действие в этой связи могли не попадать в один момент. Пауза легко читалась как отказ, хотя это мог быть только другой темп. Яркость или сбой ритма не называют причину расставания и не говорят, что было дальше.",
)
_add_status(
    "attraction_and_freedom",
    "challenging",
    "romantic",
    "ended",
    "Самые яркие моменты не всегда были самыми устойчивыми",
    "Интерес здесь мог чередоваться с потребностью в дистанции. Легко помнить вспышки близости и не замечать, как мало определённости было между ними. Яркость пережитого не объясняет, почему отношения должны были продолжаться.",
)
_add_status(
    "desire_and_pace",
    "supportive",
    "romantic",
    "crush",
    "Интерес может быть заметным и всё ещё односторонним",
    "{a} и {b} могут совпасть в темпе внимания раньше, чем станет ясно, взаимно ли оно. С вашей стороны интерес не доказывает такой же интерес другого человека. Это гипотеза о возможном ритме, не о чужом выборе.",
)
