"""Golden tests for Skill 01 natal calculation (Swiss Ephemeris)."""

from __future__ import annotations

from datetime import date, time

from django.test import TestCase

from core.services.natal_common import NatalCalcError, angular_distance, normalize_longitude
from core.services.swiss_engine import calculate_natal

GDYNIA = dict(
    birth_date=date(1995, 5, 26),
    birth_time=time(19, 25),
    latitude=54.516498,
    longitude=18.540274,
    timezone_name="Europe/Warsaw",
    place="Gdynia",
)


def _body(natal: dict, key: str) -> dict:
    return next(row for row in natal["bodies"] if row["id"] == key)


class NatalChartSkillTests(TestCase):
    def test_gdynia_golden_fixture_matches_pattern_reference(self):
        natal = calculate_natal(**GDYNIA)
        self.assertEqual(natal["schema_version"], "natal-chart-v1")
        self.assertEqual(natal["calculation"]["zodiac"], "tropical")
        self.assertEqual(natal["calculation"]["house_system"], "Placidus")
        self.assertEqual(natal["calculation"]["node_type"], "true")
        self.assertEqual(natal["birth"]["utc_offset"], "+02:00")
        self.assertTrue(natal["birth"]["utc_datetime"].startswith("1995-05-26T17:25:00"))

        self.assertEqual(natal["ascendant"]["sign"], "scorpio")
        self.assertAlmostEqual(natal["ascendant"]["longitude"], 229.58, delta=0.08)
        self.assertEqual(natal["midheaven"]["sign"], "virgo")
        self.assertAlmostEqual(natal["midheaven"]["longitude"], 162.22, delta=0.08)

        sun = _body(natal, "sun")
        moon = _body(natal, "moon")
        venus = _body(natal, "venus")
        mercury = _body(natal, "mercury")
        jupiter = _body(natal, "jupiter")
        node = _body(natal, "north_node")

        self.assertEqual(sun["sign"], "gemini")
        self.assertAlmostEqual(sun["longitude"], 65.00, delta=0.05)
        self.assertEqual(moon["sign"], "taurus")
        self.assertAlmostEqual(moon["longitude"], 35.84, delta=0.05)
        self.assertEqual(venus["sign"], "taurus")
        self.assertAlmostEqual(venus["longitude"], 41.83, delta=0.05)
        self.assertEqual(mercury["sign"], "gemini")
        self.assertAlmostEqual(mercury["longitude"], 78.15, delta=0.05)
        self.assertTrue(mercury["retrograde"])
        self.assertEqual(jupiter["sign"], "sagittarius")
        self.assertAlmostEqual(jupiter["longitude"], 251.25, delta=0.05)
        self.assertEqual(node["sign"], "scorpio")
        self.assertAlmostEqual(node["longitude"], 215.47, delta=0.05)

        self.assertAlmostEqual(_body(natal, "south_node")["longitude"], (node["longitude"] + 180) % 360, delta=0.001)
        self.assertIn("chiron", {row["id"] for row in natal["bodies"]})
        self.assertIn("vesta", {row["id"] for row in natal["bodies"]})
        self.assertIsNotNone(natal["vertex"])
        self.assertEqual(len(natal["houses"]), 12)
        self.assertEqual(natal["houses"][0]["house"], 1)
        self.assertTrue(natal["aspects"])
        self.assertIn("applying", natal["aspects"][0])
        self.assertFalse(any("theme" in row for row in natal["aspects"]))

        from core.services.report_facts import chart_wheel, natal_aspects
        from core.services.report_types import PLANET_ORDER

        wheel = chart_wheel(natal, natal_aspects(natal))
        self.assertTrue(wheel["aspects"])
        self.assertTrue(all(row["aspect"] != "conjunction" for row in wheel["aspects"]))
        self.assertTrue(all(row["a"] in PLANET_ORDER and row["b"] in PLANET_ORDER for row in wheel["aspects"]))

    def test_unknown_birth_time_omits_angles_and_houses(self):
        natal = calculate_natal(
            birth_date=date(1995, 5, 26),
            birth_time=None,
            latitude=54.516498,
            longitude=18.540274,
            timezone_name="Europe/Warsaw",
            place="Gdynia",
        )
        self.assertFalse(natal["has_birth_time"])
        self.assertIsNone(natal["ascendant"])
        self.assertIsNone(natal["midheaven"])
        self.assertIsNone(natal["houses"])
        self.assertIsNone(_body(natal, "sun")["house"])
        self.assertTrue(natal["validation"]["warnings"])

    def test_winter_offset_without_dst(self):
        natal = calculate_natal(
            birth_date=date(1995, 1, 15),
            birth_time=time(19, 25),
            latitude=54.516498,
            longitude=18.540274,
            timezone_name="Europe/Warsaw",
            place="Gdynia",
        )
        self.assertEqual(natal["birth"]["utc_offset"], "+01:00")

    def test_unknown_timezone_fails_loudly(self):
        with self.assertRaises(NatalCalcError):
            calculate_natal(
                birth_date=date(1995, 5, 26),
                birth_time=time(19, 25),
                latitude=54.5,
                longitude=18.5,
                timezone_name="Not/AZone",
                place="X",
            )

    def test_aspect_wraps_zero_longitude(self):
        self.assertAlmostEqual(angular_distance(359.0, 1.0), 2.0, places=4)
        self.assertEqual(normalize_longitude(-10), 350.0)

    def test_helsinki_latitude_returns_twelve_cusps(self):
        natal = calculate_natal(
            birth_date=date(1995, 5, 26),
            birth_time=time(12, 0),
            latitude=60.1699,
            longitude=24.9384,
            timezone_name="Europe/Helsinki",
            place="Helsinki",
        )
        self.assertEqual(len(natal["houses"]), 12)
        self.assertTrue(natal["has_birth_time"])

    def test_high_latitude_placidus_fails_loudly(self):
        with self.assertRaises(NatalCalcError):
            calculate_natal(
                birth_date=date(1995, 5, 26),
                birth_time=time(12, 0),
                latitude=69.6492,
                longitude=18.9553,
                timezone_name="Europe/Oslo",
                place="Tromso",
            )

    def test_onboarding_insight_always_has_cycle_hits(self):
        from core.services.insight import build_insight
        from core.services.swiss_engine import calculate_sky_now

        natal = calculate_natal(
            birth_date=date(1993, 8, 21),
            birth_time=time(9, 45),
            latitude=55.7558,
            longitude=37.6173,
            timezone_name="Europe/Moscow",
            place="Москва",
        )
        insight = build_insight(natal, calculate_sky_now())
        keys = [item["key"] for item in insight["influences"]]
        self.assertTrue(keys)
        self.assertNotIn("general_watch", keys)
        self.assertIn("saturn_on_moon", keys)

    def test_public_natal_error_hides_engine_internals(self):
        from core.services.natal_common import CHART_CALC_USER_ERROR, public_natal_error

        self.assertEqual(
            public_natal_error(NatalCalcError("Unexpected Swiss Ephemeris mode retflag=260")),
            CHART_CALC_USER_ERROR,
        )
        self.assertEqual(
            public_natal_error(NatalCalcError("Неизвестная таймзона: Not/AZone")),
            "Неизвестная таймзона: Not/AZone",
        )

    def test_truncated_ephemeris_files_are_replaced(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from core.services import swiss_engine

        source = Path(__file__).resolve().parent / "services" / "ephemeris" / "swiss"
        swiss_engine.reset_ephemeris_state()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp)
                for name in swiss_engine._NEEDED_FILES:
                    (dest / name).write_bytes(b"not-a-real-ephemeris")

                def fake_download(directory: Path, name: str) -> None:
                    (directory / name).write_bytes((source / name).read_bytes())

                with patch.dict(os.environ, {"SWISSEPH_PATH": str(dest)}), patch.object(
                    swiss_engine, "_download_ephe_file", side_effect=fake_download
                ):
                    natal = calculate_natal(**GDYNIA)
            self.assertEqual(natal["ascendant"]["sign"], "scorpio")
        finally:
            swiss_engine.reset_ephemeris_state()


class OnboardingBirthErrorTests(TestCase):
    def test_birth_step_hides_swiss_retflag_from_user(self):
        from unittest.mock import patch

        from core.models import OnboardingStep, OnboardingSession
        from core.services.natal_common import CHART_CALC_USER_ERROR

        OnboardingStep.objects.create(
            slug="birth",
            title="Данные рождения",
            step_type=OnboardingStep.StepType.BIRTH_DATA,
            order=1,
            is_active=True,
        )
        session = OnboardingSession.objects.create()
        with patch(
            "core.services.onboarding_astro.calculate_and_store_chart",
            side_effect=NatalCalcError("Unexpected Swiss Ephemeris mode retflag=260"),
        ):
            response = self.client.put(
                f"/api/onboarding/sessions/{session.token}/steps/birth/",
                {
                    "payload": {
                        "birth_date": "1995-05-26",
                        "birth_place": "Гдыня, Польша",
                        "birth_time": "19:25",
                    },
                    "completed": True,
                },
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["payload"]["astro"], [CHART_CALC_USER_ERROR])


class LandingChartApiTests(TestCase):
    def test_post_returns_wheel_without_completing_birth_step(self):
        from core.models import NatalChart, OnboardingSession, OnboardingStep

        OnboardingStep.objects.create(
            slug="name",
            title="Имя",
            step_type=OnboardingStep.StepType.CONTENT,
            order=10,
            is_active=True,
        )
        OnboardingStep.objects.create(
            slug="birth",
            title="Данные рождения",
            step_type=OnboardingStep.StepType.BIRTH_DATA,
            order=20,
            is_active=True,
        )
        response = self.client.post(
            "/api/landing/chart/",
            {
                "birth_date": "1995-05-26",
                "birth_time": "19:25",
                "birth_place": "Gdynia",
                "birth_lat": 54.516498,
                "birth_lng": 18.540274,
                "timezone": "Europe/Warsaw",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertTrue(data["has_birth_time"])
        self.assertEqual(data["birth"]["birth_time"], "19:25")
        self.assertTrue(data["wheel"]["planets"])
        self.assertEqual(len(data["wheel"]["houses"]), 12)
        self.assertEqual(data["birth"]["birth_date"], "1995-05-26")
        self.assertEqual(data["birth"]["birth_place"], "Gdynia")
        session = OnboardingSession.objects.get(token=data["token"])
        self.assertEqual(str(session.birth_time)[:5], "19:25")
        self.assertFalse(session.answers.filter(completed=True).exists())
        chart = NatalChart.objects.get(session=session)
        self.assertEqual(chart.status, NatalChart.Status.READY)
        self.assertNotIn("insight", chart.chart_data)

        restored = self.client.get(f"/api/landing/chart/{data['token']}/")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["token"], data["token"])
        self.assertEqual(
            restored.json()["wheel"]["ascendant_longitude"],
            data["wheel"]["ascendant_longitude"],
        )

        again = self.client.post(
            "/api/landing/chart/",
            {
                "token": data["token"],
                "birth_date": "1993-08-21",
                "birth_place": "Gdynia",
                "birth_lat": 54.516498,
                "birth_lng": 18.540274,
                "timezone": "Europe/Warsaw",
            },
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["birth"]["birth_date"], "1995-05-26")
