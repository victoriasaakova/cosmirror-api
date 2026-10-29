"""Админка показывает анонимный ввод пары и не даёт его править."""

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
        self.assertNotContains(page, 'name="_save"')
        denied = self.client.post(url, {"relationship_type": "friendship"})
        self.assertEqual(denied.status_code, 403)
        self.report.refresh_from_db()
        self.assertEqual(self.report.relationship_type, "romantic")
