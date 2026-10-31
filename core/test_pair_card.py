"""Формула аркана пары. Без натала, без случайного выбора и без LLM."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from core.services.compatibility.tarot import (
    ARCANA,
    ATTRIBUTION,
    FORMULA_NOTE,
    LOVE_RU,
    couple_arcana,
    love_reading,
    pair_card_current,
    pair_card_section,
    personal_arcana,
    public_arcana,
    reduce_arcana,
)


class _Person:
    def __init__(self, person_id: str, birth_date: date):
        self.person_id = person_id
        self.birth_date = birth_date


class PairCardFormulaTests(SimpleTestCase):
    def test_documented_example_is_the_star(self):
        self.assertEqual(personal_arcana(date(1991, 2, 14)), 5)
        self.assertEqual(personal_arcana(date(1989, 11, 23)), 12)
        self.assertEqual(couple_arcana(5, 12), 17)
        self.assertEqual(couple_arcana(12, 5), 17)
        self.assertEqual(
            public_arcana(17),
            {"number": 17, "name": "Звезда", "image": "/images/tarot/ar17.jpg"},
        )

    def test_twenty_two_stays_the_fool_and_does_not_become_zero(self):
        self.assertEqual(reduce_arcana(22), 22)
        self.assertEqual(reduce_arcana(23), 1)
        self.assertEqual(reduce_arcana(44), 22)
        self.assertEqual(reduce_arcana(45), 1)
        self.assertEqual(personal_arcana(date(1991, 1, 1)), 22)
        self.assertEqual(personal_arcana(date(1991, 1, 2)), 1)
        self.assertEqual(couple_arcana(11, 11), 22)
        self.assertEqual(couple_arcana(22, 22), 22)
        self.assertEqual(couple_arcana(22, 1), 1)
        fool = public_arcana(22)
        self.assertEqual(fool["name"], "Шут")
        self.assertEqual(fool["image"], "/images/tarot/ar00.jpg")
        self.assertEqual(public_arcana(1)["image"], "/images/tarot/ar01.jpg")
        self.assertEqual(public_arcana(21)["image"], "/images/tarot/ar21.jpg")

    def test_same_dates_twice_return_the_same_card(self):
        first = personal_arcana(date(1994, 4, 12))
        second = personal_arcana(date(1991, 11, 3))
        self.assertEqual(couple_arcana(first, second), couple_arcana(second, first))
        self.assertEqual(first, 8)
        self.assertEqual(second, 3)
        self.assertEqual(couple_arcana(first, second), 11)

    def test_catalog_follows_major_json_and_local_files(self):
        source = json.loads(
            Path(__file__).resolve().parent.joinpath(
                "services/compatibility/data/major.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(source), 22)
        self.assertEqual(set(ARCANA), set(range(1, 23)))
        root = Path(__file__).resolve().parents[2] / "cosmirror-web" / "public" / "images" / "tarot"
        for index, row in enumerate(source):
            number = 22 if index == 0 else index
            card = ARCANA[number]
            self.assertEqual(card["name_en"], row["name"])
            self.assertTrue(card["image"].endswith(f"/ar{index:02d}.jpg"))
            path = root / f"ar{index:02d}.jpg"
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 20_000)
            self.assertEqual(path.read_bytes()[:2], b"\xff\xd8")

    def test_public_section_hides_the_birth_date(self):
        section = pair_card_section(
            _Person("A", date(1991, 2, 14)),
            _Person("B", date(1989, 11, 23)),
        )
        raw = json.dumps(section, ensure_ascii=False)
        self.assertNotIn("1991", raw)
        self.assertNotIn("1989", raw)
        self.assertNotIn("02-14", raw)
        self.assertEqual(section["formula_note"], FORMULA_NOTE)
        self.assertEqual(section["card"]["name"], "Звезда")
        self.assertEqual(section["card"]["image"], "/images/tarot/ar17.jpg")
        self.assertEqual(section["love"], love_reading(17))
        self.assertEqual(section["love"]["name"], "Звезда")
        self.assertEqual(section["attribution"], ATTRIBUTION)
        self.assertTrue(pair_card_current(section))
        stale = dict(section)
        stale.pop("love")
        self.assertFalse(pair_card_current(stale))
        swapped = pair_card_section(
            _Person("B", date(1991, 2, 14)),
            _Person("A", date(1989, 11, 23)),
        )
        self.assertEqual(swapped["card"], section["card"])
        self.assertEqual(swapped["love"], section["love"])
        self.assertEqual(swapped["persons"][0]["id"], "B")

    def test_love_text_is_copied_from_major_arcana_only(self):
        payload = json.loads(
            Path(__file__).resolve().parent.joinpath(
                "services/compatibility/data/love-tarot.json"
            ).read_text(encoding="utf-8")
        )
        majors = [card for card in payload["cards"] if card["arcana"] == "major"]
        self.assertEqual(len(majors), 22)
        self.assertEqual(set(LOVE_RU), set(range(1, 23)))
        fool = next(card for card in majors if card["number"] == 0)
        star = next(card for card in majors if card["number"] == 17)
        self.assertEqual(love_reading(22), _ru(fool))
        self.assertEqual(love_reading(17), _ru(star))
        self.assertEqual(public_arcana(22)["image"], "/images/tarot/ar00.jpg")
        self.assertNotIn("loveoracle.app/deck", public_arcana(17)["image"])


def _ru(card: dict) -> dict[str, str]:
    row = card["love"]["ru"]
    return {"name": row["name"], "upright": row["upright"], "reversed": row["reversed"]}
