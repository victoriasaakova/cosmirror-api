"""Личный аркан и аркан пары. Формула Cosmirror, не правило Таро и не LLM.

Номер 22 — Шут, файл ar00.jpg. Номера 1–21 — ar01.jpg–ar21.jpg.
Названия на английском берутся из major.json (sixseeds/tarot-api),
картинки лежат локально в cosmirror-web/public/images/tarot/.

Тексты отношений копируются из love-tarot.json (Love Oracle, CC BY 4.0):
только 22 Старших аркана, поле love.ru. Номер датасета 0 — это Шут.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

FORMULA_ID = "cosmirror-digit-sum-v1"
FORMULA_NOTE = "Это выбранная формула Cosmirror, а не универсальное правило Таро."
ATTRIBUTION = {
    "text": "Tarot data from Love Oracle — https://www.loveoracle.app",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_url": "https://www.loveoracle.app",
}

_DATA_PATH = Path(__file__).resolve().parent / "data" / "major.json"
_LOVE_PATH = Path(__file__).resolve().parent / "data" / "love-tarot.json"
_IMAGE_ROOT = "/images/tarot"

# Индекс в major.json: 0 — Шут. Русское имя показывается в интерфейсе.
_RU_BY_INDEX = (
    "Шут",
    "Маг",
    "Верховная Жрица",
    "Императрица",
    "Император",
    "Иерофант",
    "Влюблённые",
    "Колесница",
    "Сила",
    "Отшельник",
    "Колесо Фортуны",
    "Справедливость",
    "Повешенный",
    "Смерть",
    "Умеренность",
    "Дьявол",
    "Башня",
    "Звезда",
    "Луна",
    "Солнце",
    "Суд",
    "Мир",
)


def reduce_arcana(total: int) -> int:
    """Сводит положительную сумму к 1–22. 22 остаётся 22: вычитаем, только пока сумма больше 22."""
    if total < 1:
        raise ValueError("arcana sum must be positive")
    value = total
    while value > 22:
        value -= 22
    return value


def digit_sum(birth_date: date) -> int:
    """Сумма цифр даты в виде ДД.ММ.ГГГГ. Ведущий ноль на сумму не влияет."""
    text = f"{birth_date.day:02d}{birth_date.month:02d}{birth_date.year:04d}"
    return sum(int(char) for char in text)


def personal_arcana(birth_date: date) -> int:
    return reduce_arcana(digit_sum(birth_date))


def couple_arcana(first: int, second: int) -> int:
    for number in (first, second):
        if not isinstance(number, int) or number < 1 or number > 22:
            raise ValueError("personal arcana is out of range")
    return reduce_arcana(first + second)


def _load_catalog() -> dict[int, dict[str, Any]]:
    rows = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 22 or len(_RU_BY_INDEX) != 22:
        raise RuntimeError("major arcana catalog must contain 22 cards")
    catalog: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError("major arcana row is not an object")
        filename = f"ar{index:02d}.jpg"
        source = str(row.get("image") or "")
        if not source.endswith("/" + filename):
            raise RuntimeError("major arcana image does not match ar00–ar21")
        number = 22 if index == 0 else index
        catalog[number] = {
            "number": number,
            "name": _RU_BY_INDEX[index],
            "name_en": str(row.get("name") or ""),
            "image": f"{_IMAGE_ROOT}/{filename}",
        }
    if set(catalog) != set(range(1, 23)):
        raise RuntimeError("major arcana numbers must be 1–22")
    return catalog


# Номер аркана → название → локальный путь к изображению.
ARCANA: dict[int, dict[str, Any]] = _load_catalog()


def public_arcana(number: int) -> dict[str, Any]:
    row = ARCANA[number]
    return {"number": number, "name": row["name"], "image": row["image"]}


def love_reading(number: int) -> dict[str, str]:
    row = LOVE_RU[number]
    return {"name": row["name"], "upright": row["upright"], "reversed": row["reversed"]}


def pair_card_section(person_a: Any, person_b: Any) -> dict[str, Any]:
    persons = [
        _person_arcana(person_a.person_id, person_a.birth_date),
        _person_arcana(person_b.person_id, person_b.birth_date),
    ]
    couple = couple_arcana(persons[0]["number"], persons[1]["number"])
    return {
        "status": "ready",
        "formula": FORMULA_ID,
        "formula_note": FORMULA_NOTE,
        "persons": persons,
        "card": public_arcana(couple),
        "love": love_reading(couple),
        "attribution": dict(ATTRIBUTION),
    }


def pair_card_current(section: Any) -> bool:
    if not isinstance(section, dict) or section.get("formula") != FORMULA_ID:
        return False
    if section.get("formula_note") != FORMULA_NOTE or section.get("status") != "ready":
        return False
    card = section.get("card")
    if not isinstance(card, dict) or not isinstance(card.get("number"), int):
        return False
    expected = public_arcana(card["number"])
    return card == expected and section.get("love") == love_reading(card["number"]) and section.get("attribution") == ATTRIBUTION


def pair_card_from_private(private: Any) -> dict[str, Any]:
    rows = private.get("persons") if isinstance(private, dict) else None
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError("pair card input is incomplete")
    parsed: list[tuple[str, date]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("pair card input is incomplete")
        person_id = row.get("person_id")
        raw_date = row.get("birth_date")
        if person_id not in {"A", "B"} or not isinstance(raw_date, str):
            raise ValueError("pair card input is incomplete")
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError("pair card input is incomplete") from None
        parsed.append((person_id, parsed_date))
    parsed.sort(key=lambda item: item[0])
    if [item[0] for item in parsed] != ["A", "B"]:
        raise ValueError("pair card input is incomplete")
    return pair_card_section(_Dated(*parsed[0]), _Dated(*parsed[1]))


class _Dated:
    def __init__(self, person_id: str, birth_date: date):
        self.person_id = person_id
        self.birth_date = birth_date


def _load_love_ru() -> dict[int, dict[str, str]]:
    payload = json.loads(_LOVE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards, list):
        raise RuntimeError("love-tarot.json has no cards")
    by_dataset_number: dict[int, dict[str, str]] = {}
    for card in cards:
        if not isinstance(card, dict) or card.get("arcana") != "major":
            continue
        number = card.get("number")
        love = card.get("love") if isinstance(card.get("love"), dict) else None
        ru = love.get("ru") if isinstance(love, dict) else None
        if not isinstance(number, int) or not isinstance(ru, dict):
            raise RuntimeError("major arcana love text is incomplete")
        name = ru.get("name")
        upright = ru.get("upright")
        reversed_text = ru.get("reversed")
        if not all(isinstance(value, str) and value.strip() for value in (name, upright, reversed_text)):
            raise RuntimeError("major arcana love text is incomplete")
        by_dataset_number[number] = {
            "name": name.strip(),
            "upright": upright.strip(),
            "reversed": reversed_text.strip(),
        }
    if set(by_dataset_number) != set(range(22)):
        raise RuntimeError("love-tarot.json must contain major arcana 0–21")
    return {22 if number == 0 else number: row for number, row in by_dataset_number.items()}


# Номер формулы 1–22 → love.ru. 22 читает карту датасета с номером 0.
LOVE_RU: dict[int, dict[str, str]] = _load_love_ru()


def _person_arcana(person_id: str, birth_date: date) -> dict[str, Any]:
    number = personal_arcana(birth_date)
    payload = public_arcana(number)
    return {"id": person_id, **payload}
