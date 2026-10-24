"""Сравнение положений. Новый аспект из похожести знаков не создаётся."""

from __future__ import annotations

from typing import Any

from core.services.natal_common import SIGNS_RU

from .policy import ASPECT_RU, SIGN_FUNCTION_RU, SIGN_POINTS
from .synastry import body_label


def build_signs(
    points_a: list[dict[str, Any]],
    points_b: list[dict[str, Any]],
    aspects: list[dict[str, Any]],
    *,
    include_moon: bool,
    include_asc: bool,
) -> dict[str, Any]:
    wanted = [point for point in SIGN_POINTS if point != "moon" or include_moon]
    if include_asc:
        wanted.append("asc")
    by_a = {point["body"]: point for point in points_a}
    by_b = {point["body"]: point for point in points_b}
    comparisons = []
    for body in wanted:
        left = by_a.get(body)
        right = by_b.get(body)
        if left is None or right is None:
            continue
        if not left.get("sign") or not right.get("sign"):
            continue
        cross_ids = sorted(
            row["id"]
            for row in aspects
            if row["person_a_point"] == body and row["person_b_point"] == body
        )
        comparisons.append(_comparison(body, left, right, cross_ids))
    return {"status": "ready", "comparisons": comparisons}


def _comparison(
    body: str,
    left: dict[str, Any],
    right: dict[str, Any],
    cross_ids: list[str],
) -> dict[str, Any]:
    label = body_label(body)
    sign_a = _sign_prep(left["sign"])
    sign_b = _sign_prep(right["sign"])
    function = SIGN_FUNCTION_RU.get(body, "эту функцию")
    aspect_sentence = _aspect_sentence(cross_ids)
    meaning = (
        f"{_owned(body)} в {sign_a}, {label} другого человека в {sign_b}. "
        f"{label} описывает {function}. {aspect_sentence}"
    ).strip()
    if left["sign"] == right["sign"]:
        common = f"Оба положения в одном знаке: тема {function} совпадает по знаку."
        difference = "Одинаковый знак не означает одинаковый опыт между вами."
    else:
        common = f"Общая здесь функция, {function}, а не одинаковый способ её проявлять."
        difference = f"Один способ связан со знаком {sign_a}, другой со знаком {sign_b}."
    return {
        "id": f"signs-{body}",
        "point": body,
        "pair_placements": {
            "A": _placement(left),
            "B": _placement(right),
        },
        "cross_aspect_ids": cross_ids,
        "meaning": meaning,
        "common_ground": common,
        "difference": difference,
        "evidence_ids": [f"signs-{body}"],
    }


def _placement(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "sign": point.get("sign"),
        "degree": point.get("degree"),
        "longitude": round(float(point["longitude"]), 4),
    }


def _aspect_sentence(cross_ids: list[str]) -> str:
    if not cross_ids:
        return "Между этими положениями нет мажорного аспекта в пределах орба."
    aspect = cross_ids[0].rsplit("-", 1)[-1]
    name = ASPECT_RU.get(aspect, aspect)
    return f"Между этими положениями есть {name}."


_OWNED = {
    "sun": "Твоё Солнце",
    "moon": "Твоя Луна",
    "mercury": "Твой Меркурий",
    "venus": "Твоя Венера",
    "mars": "Твой Марс",
    "asc": "Твой Асцендент",
}

_SIGN_PREP = {
    "aries": "Овне",
    "taurus": "Тельце",
    "gemini": "Близнецах",
    "cancer": "Раке",
    "leo": "Льве",
    "virgo": "Деве",
    "libra": "Весах",
    "scorpio": "Скорпионе",
    "sagittarius": "Стрельце",
    "capricorn": "Козероге",
    "aquarius": "Водолее",
    "pisces": "Рыбах",
}


def _owned(body: str) -> str:
    return _OWNED.get(body, body_label(body))


def _sign_prep(sign: str) -> str:
    return _SIGN_PREP.get(sign, SIGNS_RU.get(sign, sign))
