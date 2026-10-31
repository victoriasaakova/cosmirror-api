"""Слот первого инсайта. Тему выбирает blueprint-скоринг, не модель.

Модель может заменить только title и body. Evidence, basis и theme_id остаются от кода.
Пока серверных падежей нет, имена в basis стоят отдельными подлежащими.
"""

from __future__ import annotations

from typing import Any, Optional

from .insight_select import insight_copy, select_opening
from .policy import BODY_RU

_DATIVE = {
    "sun": "Солнцу",
    "moon": "Луне",
    "mercury": "Меркурию",
    "venus": "Венере",
    "mars": "Марсу",
    "jupiter": "Юпитеру",
    "saturn": "Сатурну",
    "uranus": "Урану",
    "neptune": "Нептуну",
    "pluto": "Плутону",
    "north_node": "Северному узлу",
    "south_node": "Южному узлу",
    "chiron": "Хирону",
    "asc": "Асценденту",
    "mc": "середине неба",
}

_INSTRUMENTAL = {
    "sun": "Солнцем",
    "moon": "Луной",
    "mercury": "Меркурием",
    "venus": "Венерой",
    "mars": "Марсом",
    "jupiter": "Юпитером",
    "saturn": "Сатурном",
    "uranus": "Ураном",
    "neptune": "Нептуном",
    "pluto": "Плутоном",
    "north_node": "Северным узлом",
    "south_node": "Южным узлом",
    "chiron": "Хироном",
    "asc": "Асцендентом",
    "mc": "серединой неба",
}

_ASPECT_PHRASE = {
    "conjunction": "в соединении с {other}",
    "sextile": "в секстиле к {other}",
    "square": "в квадрате к {other}",
    "trine": "в тригоне к {other}",
    "opposition": "в оппозиции к {other}",
}


def build_insight_slot(document: dict[str, Any]) -> dict[str, Any]:
    opening = select_opening(document)
    if opening is None:
        return {
            "status": "unavailable",
            "temporal_frame": "base",
            "theme_id": None,
            "polarity": None,
            "evidence_ids": [],
            "basis": "",
            "title": "",
            "headline": "",
            "body": "",
            "source": "fallback",
            "interpretation_depth": "limited",
        }
    name_a, name_b = _names(document)
    aspects = opening["aspects"]
    context = document.get("relationship_context") if isinstance(document.get("relationship_context"), dict) else {}
    relationship = str(document.get("relationship_type") or context.get("type") or "romantic")
    status = str(context.get("status") or "") or None
    title, body = insight_copy(
        opening["theme_id"],
        opening["polarity"],
        relationship,
        name_a,
        name_b,
        status,
    )
    return {
        "status": "ready",
        "temporal_frame": "base",
        "theme_id": opening["theme_id"],
        "polarity": opening["polarity"],
        "scoring_version": opening["scoring_version"],
        "evidence_ids": [aspect.get("id") for aspect in aspects],
        "basis": ". ".join(
            basis_line(
                str(aspect.get("person_a_point") or ""),
                name_a,
                str(aspect.get("aspect") or ""),
                str(aspect.get("person_b_point") or ""),
                name_b,
            )
            for aspect in aspects
        ),
        "title": title,
        "headline": title,
        "body": body,
        "source": "fallback",
        "interpretation_depth": "limited",
    }


def ensure_insight(document: dict[str, Any]) -> None:
    current = document.get("insight")
    if isinstance(current, dict) and current.get("status") in {"ready", "unavailable"} and "evidence_ids" in current:
        return
    document["insight"] = build_insight_slot(document)


def _aspect_parts(point_a: str, aspect: str, point_b: str) -> Optional[tuple[str, str]]:
    left = _nominative(point_a)
    if aspect == "conjunction":
        other = _INSTRUMENTAL.get(point_b, _nominative(point_b))
    else:
        other = _DATIVE.get(point_b, _nominative(point_b))
    phrase = _ASPECT_PHRASE.get(aspect) or "в аспекте к {other}"
    if not left or not other:
        return None
    return left, phrase.format(other=other)


def aspect_ru(point_a: str, aspect: str, point_b: str) -> Optional[str]:
    parts = _aspect_parts(point_a, aspect, point_b)
    if parts is None:
        return None
    return f"{parts[0]} {parts[1]}"


def basis_line(point_a: str, name_a: str, aspect: str, point_b: str, name_b: str) -> str:
    parts = _aspect_parts(point_a, aspect, point_b)
    if parts is None:
        return f"{_nominative(point_a)} у {_genitive_name(name_a)}"
    left, phrase = parts
    return f"{left} у {_genitive_name(name_a)} {phrase} у {_genitive_name(name_b)}"


def _names(document: dict[str, Any]) -> tuple[str, str]:
    persons = {
        row.get("id"): row
        for row in document.get("persons") or []
        if isinstance(row, dict)
    }
    person_a = persons.get("A") if isinstance(persons.get("A"), dict) else {}
    person_b = persons.get("B") if isinstance(persons.get("B"), dict) else {}
    return (
        str(person_a.get("display_name") or "").strip() or "Ты",
        str(person_b.get("display_name") or "").strip() or "Другой человек",
    )


def decline_name(name: str) -> dict[str, Optional[str]]:
    """Шесть падежей для ясного русского имени. Неоднозначное имя не склоняется.

    Род по имени не назначается: здесь только формы, которые однозначно читаются по окончанию.
    """
    word = name.strip()
    empty = {
        "nominative": word or None,
        "genitive": None,
        "dative": None,
        "accusative": None,
        "instrumental": None,
        "prepositional": None,
    }
    if word.casefold() == "ты":
        return {
            "nominative": "ты",
            "genitive": "тебя",
            "dative": "тебе",
            "accusative": "тебя",
            "instrumental": "тобой",
            "prepositional": "тебе",
        }
    if not word or any(mark in word for mark in " -") or not word.isalpha():
        return empty
    lower = word.casefold()
    if lower[-1] in "еёиоуыэюь":
        return empty
    if lower.endswith("ия"):
        stem = word[:-2]
        return _forms(word, stem + "ии", stem + "ии", stem + "ию", stem + "ией", stem + "ии")
    if lower.endswith(("ша", "ча", "жа", "ща")):
        stem = word[:-1]
        return _forms(word, stem + "и", stem + "е", stem + "у", stem + "ей", stem + "е")
    if lower.endswith("а"):
        stem = word[:-1]
        return _forms(word, stem + "ы", stem + "е", stem + "у", stem + "ой", stem + "е")
    if lower.endswith("я"):
        stem = word[:-1]
        return _forms(word, stem + "и", stem + "е", stem + "ю", stem + "ей", stem + "е")
    if lower.endswith("й"):
        stem = word[:-1]
        return _forms(word, stem + "я", stem + "ю", stem + "я", stem + "ем", stem + "е")
    if lower[-1] in "бвгджзклмнпрстфхцчшщ":
        return _forms(word, word + "а", word + "у", word + "а", word + "ом", word + "е")
    return empty


def _forms(
    nominative: str,
    genitive: str,
    dative: str,
    accusative: str,
    instrumental: str,
    prepositional: str,
) -> dict[str, Optional[str]]:
    return {
        "nominative": nominative,
        "genitive": genitive,
        "dative": dative,
        "accusative": accusative,
        "instrumental": instrumental,
        "prepositional": prepositional,
    }


_HINTS: dict[tuple[frozenset[str], str], str] = {
    (frozenset({"mars", "pluto"}), "soft"): "начатое может удерживаться дольше первого импульса и не отпускаться на полпути",
    (frozenset({"mars", "pluto"}), "hard"): "действие может застревать в борьбе за то, кто задаёт направление",
    (frozenset({"mars", "pluto"}), "conjunction"): "желание действовать и необходимость дойти до конца могут включаться вместе",
    (frozenset({"mars", "uranus"}), "soft"): "начатое легче сменить, чем долго держаться одного плана",
    (frozenset({"mars", "uranus"}), "hard"): "резкий шаг может опережать договорённость о способе",
    (frozenset({"mercury", "saturn"}), "soft"): "формулировка чаще проверяет рамку и следствие, чем ускоряет ответ",
    (frozenset({"mercury", "saturn"}), "hard"): "точность и скорость объяснения могут спорить",
    (frozenset({"sun", "mars"}), "conjunction"): "направление и действие включаются почти одновременно",
    (frozenset({"sun", "mars"}), "soft"): "намерение легко переходит в шаг",
    (frozenset({"sun", "mars"}), "hard"): "желание действовать и выбранное направление могут тянуть в разные стороны",
    (frozenset({"sun", "jupiter"}), "soft"): "замысел легко раздвигается шире исходной задачи",
    (frozenset({"sun", "jupiter"}), "conjunction"): "направление сразу обещает больше, чем ближайший шаг",
    (frozenset({"sun", "jupiter"}), "hard"): "размах и реальная задача могут не совпадать",
    (frozenset({"mars", "jupiter"}), "soft"): "действие легко обещает больше, чем ближайший шаг",
    (frozenset({"mars", "jupiter"}), "conjunction"): "действие и расширение начинаются вместе, ещё до проверки, хватит ли на это сил",
    (frozenset({"mars", "jupiter"}), "hard"): "темп действия и то, насколько большим получилось обещание, могут спорить",
    (frozenset({"venus", "jupiter"}), "soft"): "тепло легко становится щедрым и широким",
    (frozenset({"venus", "jupiter"}), "hard"): "близость может просить определённости там, где рост просит простора",
    (frozenset({"venus", "jupiter"}), "conjunction"): "тепло и размах включаются вместе",
    (frozenset({"mercury", "jupiter"}), "soft"): "мысль легко ищет более широкий смысл, чем сама задача",
    (frozenset({"mercury", "jupiter"}), "conjunction"): "формулировка сразу раздвигает исходный вопрос",
    (frozenset({"moon", "jupiter"}), "soft"): "отклик легко становится щедрее, чем сама ситуация",
    (frozenset({"moon", "jupiter"}), "hard"): "нужда в отклике и желание расширить ситуацию могут спорить",
    (frozenset({"sun", "uranus"}), "soft"): "направление может смениться, не дожидаясь общего плана",
    (frozenset({"sun", "uranus"}), "hard"): "свой курс и внезапный поворот могут не умещаться в один план",
    (frozenset({"sun", "neptune"}), "hard"): "ясный образ и фактический шаг могут расходиться",
    (frozenset({"sun", "neptune"}), "soft"): "образ будущего может быть ярче ближайшего шага",
    (frozenset({"moon", "saturn"}), "soft"): "отклик чаще идёт через надёжность, чем через мгновенную открытость",
    (frozenset({"moon", "saturn"}), "hard"): "нужда в отклике и требование выдержки могут столкнуться",
    (frozenset({"moon", "venus"}), "soft"): "тепло и отклик могут включаться как одна реакция",
    (frozenset({"moon", "venus"}), "conjunction"): "тепло и отклик могут включаться как одна реакция",
    (frozenset({"moon", "venus"}), "hard"): "забота и личная нужда могут приходить не одновременно",
    (frozenset({"venus", "saturn"}), "soft"): "близость может расти через постоянство, а не через скорость",
    (frozenset({"venus", "saturn"}), "hard"): "желание сблизиться и потребность в границе могут звучать одновременно",
    (frozenset({"sun", "saturn"}), "soft"): "направление чаще держится на выдержке, чем на вспышке",
    (frozenset({"sun", "saturn"}), "hard"): "требование к себе может опережать право на признание",
    (frozenset({"mars", "saturn"}), "soft"): "действие чаще ждёт рамки, чем первого импульса",
    (frozenset({"mars", "saturn"}), "hard"): "порыв и внутренний тормоз могут включаться вместе",
    (frozenset({"mercury", "pluto"}), "soft"): "формулировка может идти до сути и не останавливаться на удобном ответе",
    (frozenset({"mercury", "pluto"}), "hard"): "разговор может становиться слишком точным и трудно отпускаемым",
    (frozenset({"mercury", "pluto"}), "conjunction"): "формулировка может держаться за суть и не отпускать её на полпути",
    (frozenset({"venus", "mars"}), "soft"): "интерес и готовность действовать могут включаться вместе",
    (frozenset({"venus", "mars"}), "hard"): "желание сблизиться и темп действия могут не совпадать",
    (frozenset({"venus", "uranus"}), "soft"): "интерес может вспыхивать и тут же просить воздуха",
    (frozenset({"venus", "uranus"}), "hard"): "яркость контакта и потребность действовать по-своему могут спорить",
    (frozenset({"moon", "mars"}), "soft"): "отклик легко переходит в действие",
    (frozenset({"moon", "mars"}), "hard"): "отклик и действие могут включаться слишком быстро, чтобы их согласовать",
    (frozenset({"sun", "moon"}), "soft"): "направление и отклик могут поддерживать друг друга",
    (frozenset({"sun", "moon"}), "hard"): "то, что человек показывает, и то, что его задевает, могут расходиться",
    (frozenset({"mercury", "venus"}), "soft"): "мысль и тепло могут говорить одним тоном",
    (frozenset({"mercury", "venus"}), "hard"): "ясность и желание понравиться могут тянуть фразу в разные стороны",
    (frozenset({"mercury", "moon"}), "hard"): "объяснение и отклик могут приходить в разные моменты",
    (frozenset({"mercury", "moon"}), "soft"): "мысль и отклик могут успевать друг за другом",
    (frozenset({"mercury", "uranus"}), "soft"): "формулировка может меняться быстрее плана",
    (frozenset({"mercury", "uranus"}), "hard"): "мысль может свернуть раньше, чем успеет сложиться договорённость",
}


def _aspect_class(aspect: str) -> str:
    if aspect in {"trine", "sextile"}:
        return "soft"
    if aspect in {"square", "opposition"}:
        return "hard"
    if aspect == "conjunction":
        return "conjunction"
    return ""


def _anchor_hint(point_a: str, point_b: str, aspect: str) -> Optional[str]:
    pair = frozenset((point_a, point_b))
    kind = _aspect_class(aspect)
    if not kind:
        return None
    return _HINTS.get((pair, kind)) or _HINTS.get((pair, aspect))


def relevant_anchors(document: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    raw = document.get("natal_anchors") if isinstance(document.get("natal_anchors"), dict) else {}
    return {
        "A": _pick_anchors(raw.get("A"), {str(row.get("person_a_point") or "") for row in evidence}),
        "B": _pick_anchors(raw.get("B"), {str(row.get("person_b_point") or "") for row in evidence}),
    }


def _pick_anchors(rows: Any, points: set[str]) -> list[dict[str, Any]]:
    points.discard("")
    if not points or not isinstance(rows, list):
        return []
    matched = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        left = str(row.get("a") or "")
        right = str(row.get("b") or "")
        if not {left, right} & points:
            continue
        hint = _anchor_hint(left, right, str(row.get("aspect") or ""))
        description = hint or aspect_ru(left, str(row.get("aspect") or ""), right)
        if not description:
            continue
        orb = row.get("orb")
        orb_value = float(orb) if isinstance(orb, (int, float)) else 99.0
        matched.append((0 if hint else 1, orb_value, str(row.get("id") or ""), row, description))
    matched.sort()
    picked = []
    for _hinted, orb_value, _evidence_id, row, description in matched[:2]:
        picked.append(
            {
                "id": row.get("id"),
                "a": row.get("a"),
                "b": row.get("b"),
                "aspect": row.get("aspect"),
                "orb_deg": None if orb_value == 99.0 else orb_value,
                "description_ru": description,
                "quality_hint_ru": description,
            }
        )
    return picked


def _genitive_name(name: str) -> str:
    forms = decline_name(name)
    return forms["genitive"] or forms["nominative"] or name.strip()


def _nominative(point: str) -> str:
    if point == "mc":
        return "Середина неба"
    return BODY_RU.get(point, point)
