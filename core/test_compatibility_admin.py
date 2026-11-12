"""Админка показывает анонимный ввод пары, текст интерпретации и не даёт его править."""

from __future__ import annotations

from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import CompatibilityReport


def _person(person_id: str, **overrides) -> dict:
    person = {
        "person_id": person_id,
        "display_name": "Алина" if person_id == "A" else "Марк",
        "birth_date": "1991-04-17" if person_id == "A" else "1993-11-05",
        "birth_time": "14:30:00" if person_id == "A" else None,
        "birth_time_status": "known" if person_id == "A" else "unknown",
        "place_name": "Гдыня" if person_id == "A" else "Москва",
        "latitude": 54.5181 if person_id == "A" else 55.7558,
        "longitude": 18.5305 if person_id == "A" else 37.6173,
        "timezone_id": "Europe/Warsaw" if person_id == "A" else "Europe/Moscow",
    }
    person.update(overrides)
    return person


class CompatibilityAdminTests(TestCase):
    def setUp(self):
        self.report = CompatibilityReport.objects.create(
            input_hash="ab" * 32,
            relationship_type="romantic",
            reference_date=date(2026, 10, 29),
            private_input={
                "relationship_type": "romantic",
                "reference_date": "2026-10-29",
                "persons": [_person("A"), _person("B")],
            },
            private_natals={"A": {}, "B": {}},
            public_document={"status": "ready"},
        )
        User.objects.create_superuser("compat-admin", "admin@example.com", "password")
        self.client.force_login(User.objects.get(username="compat-admin"))

    def test_changelist_shows_what_people_typed(self):
        response = self.client.get("/admin/core/compatibilityreport/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Алина · 17.04.1991 · 14:30 · Гдыня")
        self.assertContains(response, "Марк · 05.11.1993 · время неизвестно · Москва")
        self.assertNotContains(response, "/admin/core/compatibilityreport/add/")

    def test_search_finds_a_city_from_the_private_input(self):
        found = self.client.get("/admin/core/compatibilityreport/", {"q": "гдыня"})
        self.assertContains(found, "Алина")
        missing = self.client.get("/admin/core/compatibilityreport/", {"q": "Новосибирск"})
        self.assertNotContains(missing, "Алина")

    def test_change_page_shows_the_pair_and_does_not_save(self):
        url = f"/admin/core/compatibilityreport/{self.report.id}/change/"
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Europe/Warsaw")
        self.assertContains(page, "54.5181, 18.5305")
        self.assertContains(page, "Текст интерпретации не записан.")
        self.assertNotContains(page, 'name="_save"')
        denied = self.client.post(url, {"relationship_type": "friendship"})
        self.assertEqual(denied.status_code, 403)
        self.report.refresh_from_db()
        self.assertEqual(self.report.relationship_type, "romantic")

    def test_change_page_shows_the_current_reading(self):
        report = CompatibilityReport.objects.create(
            input_hash="cd" * 32,
            relationship_type="romantic",
            reference_date=date(2026, 11, 12),
            private_input={"persons": [_person("A"), _person("B")]},
            private_natals={"A": {}, "B": {}},
            public_document={
                "relationship_context": {"user_question": "Куда это идёт?"},
                "persons": [
                    {"id": "A", "display_name": "Алина"},
                    {"id": "B", "display_name": "Марк"},
                ],
                "insight": {
                    "title": "Между вами держится свой темп",
                    "body": "Близость здесь появляется через разный ритм.",
                    "basis": "Венера Алины в тригоне к Марсу Марка.",
                },
                "scoring": {
                    "harmony": {"value": 72, "status": "ready", "summary": "Поддержка заметна в мягких аспектах."},
                },
                "deep_dive": {
                    "sections": [
                        {
                            "section_title": "Что вас сближает и притягивает",
                            "headline": "Тепло не отменяет разницу реакций",
                            "body": "Один ищет отклик сразу, другой сверяется дольше.",
                            "analysis": "внутренний план, его не показывают",
                        }
                    ],
                    "conclusion": {
                        "headline": "Связь можно различать без прогноза",
                        "body": "Карта не обещает, чем закончится контакт.",
                    },
                },
                "active_cycles": {
                    "persons": {
                        "A": {
                            "status": "ready",
                            "interpretation": {
                                "headline": "Сейчас нагрузка может становиться заметнее",
                                "body": "У Алины отдельный фон периода.",
                                "astrological_basis_ru": "Сатурн в квадрате к Венере — Алина.",
                            },
                        },
                        "B": {"status": "unavailable", "interpretation": None},
                    }
                },
                "pair_card": {
                    "status": "ready",
                    "card": {"name": "Влюблённые"},
                    "love": {
                        "name": "Влюблённые",
                        "upright": "Выбор близости остаётся за обоими.",
                        "reversed": "Тень карты — решать за другого.",
                    },
                },
                "bond": {
                    "insights": [
                        {"title": "Старый текст связки", "summary": "Этот абзац на текущей странице не показывают."}
                    ]
                },
            },
        )
        page = self.client.get(f"/admin/core/compatibilityreport/{report.id}/change/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Куда это идёт?")
        self.assertContains(page, "Между вами держится свой темп")
        self.assertContains(page, "Близость здесь появляется через разный ритм.")
        self.assertContains(page, "Венера Алины в тригоне к Марсу Марка.")
        self.assertContains(page, "72%")
        self.assertContains(page, "Поддержка заметна в мягких аспектах.")
        self.assertContains(page, "Тепло не отменяет разницу реакций")
        self.assertContains(page, "Один ищет отклик сразу, другой сверяется дольше.")
        self.assertContains(page, "Карта не обещает, чем закончится контакт.")
        self.assertContains(page, "Цикл · Алина")
        self.assertContains(page, "У Алины отдельный фон периода.")
        self.assertContains(page, "Сейчас нет отдельного значимого цикла по выбранным критериям.")
        self.assertContains(page, "Главная тема отношений")
        self.assertContains(page, "Выбор близости остаётся за обоими.")
        self.assertContains(page, "Теневая сторона")
        self.assertNotContains(page, "внутренний план, его не показывают")
        self.assertNotContains(page, "Этот абзац на текущей странице не показывают.")

    def test_change_page_shows_the_older_reading(self):
        report = CompatibilityReport.objects.create(
            input_hash="ef" * 32,
            relationship_type="romantic",
            reference_date=date(2026, 10, 24),
            private_input={"persons": [_person("A"), _person("B")]},
            private_natals={"A": {}, "B": {}},
            public_document={
                "schema_version": "compatibility-v1",
                "bond": {
                    "insights": [
                        {
                            "category": "attraction",
                            "title": "Интерес и ответное движение",
                            "summary": "Между вами Венера и Марс образуют тригон.",
                            "deep_read": "Это можно проверить на вашем опыте.",
                        }
                    ]
                },
                "signs": {
                    "comparisons": [
                        {
                            "point": "sun",
                            "meaning": "Твоё Солнце в Овне, Солнце другого человека в Весах.",
                            "difference": "Одинаковый знак не означает одинаковый опыт.",
                        }
                    ]
                },
            },
        )
        page = self.client.get(f"/admin/core/compatibilityreport/{report.id}/change/")
        self.assertContains(page, "Между вами Венера и Марс образуют тригон.")
        self.assertContains(page, "Это можно проверить на вашем опыте.")
        self.assertContains(page, "Знаки · Солнце")
        self.assertContains(page, "Твоё Солнце в Овне, Солнце другого человека в Весах.")
