"""Маршруты пары и синастрия synastry_orbs_v1. Эфемериды здесь не вызываются."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from core.models import CompatibilityReport, NatalChart, OnboardingSession
from core.services.compatibility.bond import build_bond
from core.services.compatibility.policy import SCHEMA_VERSION
from core.services.compatibility.synastry import allowed_orb, aspect_between, cross_aspects
from core.services.natal_common import sign_of


def _point(person: str, body: str, longitude: float, *, eligible: bool = True) -> dict:
    signed = sign_of(longitude)
    return {
        "person_id": person,
        "body": body,
        "longitude": signed["longitude"],
        "sign": signed["sign"],
        "degree": signed["degree"],
        "bond_eligible": eligible,
        "overlay_eligible": eligible,
    }


class SynastryOrbTests(SimpleTestCase):
    def test_personal_sextile_orb_4_is_rejected(self):
        self.assertIsNone(aspect_between(0.0, 64.0, "sun", "moon"))
        self.assertEqual(allowed_orb("sextile", "sun", "moon"), 3.0)

    def test_personal_sextile_on_the_orb_is_accepted(self):
        hit = aspect_between(0.0, 63.0, "sun", "moon")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["aspect"], "sextile")
        self.assertEqual(hit["orb_deg"], 3.0)

    def test_conjunction_boundary(self):
        self.assertEqual(aspect_between(0.0, 5.0, "sun", "mars")["aspect"], "conjunction")
        self.assertIsNone(aspect_between(0.0, 5.1, "sun", "mars"))

    def test_angle_orb_is_capped_at_3(self):
        self.assertIsNone(aspect_between(0.0, 4.0, "sun", "asc"))
        self.assertEqual(aspect_between(0.0, 2.0, "sun", "asc")["allowed_orb_deg"], 3.0)

    def test_conjunction_wraps_across_zero(self):
        hit = aspect_between(359.0, 1.0, "venus", "mars")
        self.assertEqual(hit["aspect"], "conjunction")
        self.assertEqual(hit["orb_deg"], 2.0)

    def test_venus_mars_is_not_mars_venus(self):
        aspects = cross_aspects(
            [_point("A", "venus", 10.0), _point("A", "mars", 80.0)],
            [_point("B", "mars", 130.0), _point("B", "venus", 200.0)],
        )
        ids = {row["id"] for row in aspects}
        self.assertIn("cross-A-venus-B-mars-trine", ids)
        self.assertIn("cross-A-mars-B-venus-trine", ids)
        self.assertIn("cross-B-mars-A-venus-trine", ids)

    def test_unknown_moon_stays_out_of_bond(self):
        aspects = cross_aspects(
            [_point("A", "moon", 0.0, eligible=False)],
            [_point("B", "sun", 0.0)],
        )
        self.assertTrue(aspects)
        bond = build_bond(aspects)
        self.assertEqual(bond["insights"], [])
        self.assertIsNone(bond["overall_bond_label"])

    def test_outer_pair_is_not_a_bond_insight(self):
        aspects = cross_aspects(
            [_point("A", "uranus", 0.0)],
            [_point("B", "neptune", 0.0)],
        )
        self.assertTrue(aspects)
        self.assertEqual(build_bond(aspects)["insights"], [])

    def test_venus_mars_trine_is_one_attraction_insight(self):
        aspects = cross_aspects(
            [_point("A", "venus", 10.0)],
            [_point("B", "mars", 130.0)],
        )
        bond = build_bond(aspects)
        self.assertEqual(len(bond["insights"]), 1)
        insight = bond["insights"][0]
        self.assertEqual(insight["category"], "attraction")
        self.assertEqual(insight["perspective"], "mutual")
        self.assertCountEqual(
            insight["evidence_ids"],
            ["cross-A-venus-B-mars-trine", "cross-B-mars-A-venus-trine"],
        )
        self.assertIn("между вами", insight["summary"].lower())
        self.assertNotIn("%", insight["summary"])


def _body(body: str, longitude: float, house: int = 1) -> dict:
    signed = sign_of(longitude)
    return {
        "id": body,
        "longitude": signed["longitude"],
        "sign": signed["sign"],
        "degree": signed["degree"],
        "house": house,
    }


def _natal(longitudes: dict[str, float], *, with_angles: bool = True) -> dict:
    bodies = [_body(body, longitude) for body, longitude in longitudes.items()]
    if with_angles:
        angles = {
            "asc": _body("asc", 210.0),
            "mc": _body("mc", 120.0),
            "dsc": None,
            "ic": None,
            "vertex": None,
            "antivertex": None,
        }
        houses = [{"house": index + 1, "cusp_longitude": float(index * 30)} for index in range(12)]
    else:
        angles = {key: None for key in ("asc", "dsc", "mc", "ic", "vertex", "antivertex")}
        houses = None
    return {
        "calculation": {"engine_version": "test-swe"},
        "bodies": bodies,
        "angles": angles,
        "houses": houses,
    }


_PLANETS_A = {
    "sun": 0.0,
    "moon": 15.0,
    "mercury": 20.0,
    "venus": 10.0,
    "mars": 40.0,
}


def _person(
    person_id: str,
    *,
    latitude: float,
    status: str = "known",
    birth_date: str = "1991-04-17",
) -> dict:
    payload = {
        "person_id": person_id,
        "display_name": "Алина" if person_id == "A" else "Марк",
        "birth_date": birth_date,
        "birth_time_status": status,
        "place_name": "Gdynia",
        "latitude": latitude,
        "longitude": 21.012345,
        "timezone_id": "Europe/Warsaw",
    }
    if status == "unknown":
        payload["birth_time"] = None
    else:
        payload["birth_time"] = "19:25"
    return payload


class CompatibilityApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.planets_b = {
            "sun": 4.0,
            "moon": 15.0,
            "mercury": 20.0,
            "venus": 155.0,
            "mars": 130.0,
        }
        self._writers = patch(
            "core.services.compatibility.service.enrich_document",
            side_effect=lambda document: document,
        )
        self._writers.start()
        self.addCleanup(self._writers.stop)
        self._sky = patch(
            "core.services.natal.calculate_sky_now",
            side_effect=RuntimeError("sky"),
        )
        self._sky.start()
        self.addCleanup(self._sky.stop)

    def _fake_natal(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["latitude"] < 54:
            return _natal(_PLANETS_A)
        return _natal(self.planets_b)

    def _payload(self, **overrides):
        payload = {
            "relationship_type": "romantic",
            "persons": [
                _person("A", latitude=52.231111),
                _person("B", latitude=55.751234),
            ],
        }
        payload.update(overrides)
        return payload

    def test_create_and_read_pair_report(self):
        self.calls = []
        charts = NatalChart.objects.count()
        sessions = OnboardingSession.objects.count()
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post("/api/compatibility/v1/reports", self._payload(), format="json")
            self.assertEqual(created.status_code, 202, created.content)
            body = created.json()
            self.assertEqual(body["schema_version"], SCHEMA_VERSION)
            self.assertEqual(body["status"], "partial")
            self.assertEqual(body["sections"]["bond"], "ready")
            self.assertEqual(body["sections"]["signs"], "ready")
            self.assertEqual(body["sections"]["chart"], "ready")
            self.assertEqual(body["sections"]["transits"], "pending")
            report_id = body["report_id"]
            read = self.client.get(f"/api/compatibility/v1/reports/{report_id}")
        self.assertEqual(read.status_code, 200, read.content)
        document = read.json()
        raw = read.content.decode()
        self.assertNotIn("1991-04-17", raw)
        self.assertNotIn("52.231111", raw)
        self.assertNotIn("Gdynia", raw)
        self.assertNotIn("Europe/Warsaw", raw)
        self.assertNotIn("%", raw)
        self.assertEqual(document["persons"][0]["display_name"], "Алина")
        self.assertEqual(document["persons"][1]["display_name"], "Марк")
        self.assertIn(document["insight"]["status"], {"ready", "unavailable"})
        self.assertEqual(document["insight"]["temporal_frame"], "base")
        if document["insight"]["status"] == "ready":
            self.assertIn("Алины", document["insight"]["basis"])
            self.assertNotIn(" A ", f" {document['insight']['basis']} ")
            self.assertNotIn("прямо сейчас", document["insight"]["body"])
        self.assertIsNone(document["bond"]["overall_bond_label"])
        self.assertEqual(document["meta"]["synastry_policy_version"], "synastry-orbs-v1")
        self.assertEqual(document["meta"]["data_quality"], "full")
        self.assertEqual(document["transits"]["status"], "pending")
        self.assertEqual(document["meta"]["scoring_policy_version"], "compatibility-scoring-v2-draft")
        scoring = document["scoring"]
        self.assertEqual(
            set(scoring),
            {
                "scoring_policy_version",
                "source",
                "not_probability",
                "omitted_factors",
                "harmony",
                "karmic_patterns",
                "current_tension",
                "transformation",
            },
        )
        self.assertEqual(scoring["source"], "calculated")
        self.assertIs(scoring["not_probability"], True)
        self.assertIsNone(scoring["current_tension"]["value"])
        self.assertEqual(scoring["current_tension"]["status"], "pending")
        self.assertEqual(scoring["current_tension"]["reason_code"], "TRANSIT_SNAPSHOT_FAILED")
        self.assertEqual(
            [row["id"] for row in document["deep_dive"]["sections"]],
            ["common_ground", "differences", "values_needs", "mutual_expression"],
        )
        self.assertEqual(document["deep_dive"]["schema_version"], "compatibility-deep-dive-v2")
        self.assertIn("A", document["active_cycles"]["persons"])
        self.assertIn("B", document["active_cycles"]["persons"])
        self.assertEqual(document["active_cycles"]["persons"]["A"]["reason_code"], "TRANSIT_SNAPSHOT_FAILED")
        aspect_ids = {row["id"] for row in document["chart"]["cross_aspects"]}
        for key in ("harmony", "karmic_patterns", "transformation"):
            row = scoring[key]
            self.assertIn(row["status"], {"ready", "limited", "unavailable"})
            self.assertTrue(row["value"] is None or isinstance(row["value"], int))
            self.assertNotIn("%", row["summary"])
            self.assertNotIn("вероятност", row["summary"].lower())
            if row["status"] in {"ready", "limited"} and row["value"]:
                self.assertTrue(row["top_factors"])
                self.assertIn(row["top_factors"][0]["evidence_id"], aspect_ids)
        ids = {row["id"] for row in document["chart"]["cross_aspects"]}
        self.assertIn("cross-A-venus-B-mars-trine", ids)
        attraction = [row for row in document["bond"]["insights"] if row["category"] == "attraction"]
        self.assertEqual(len(attraction), 1)
        self.assertIn("cross-A-venus-B-mars-trine", attraction[0]["evidence_ids"])
        for insight in document["bond"]["insights"]:
            for evidence_id in insight["evidence_ids"]:
                self.assertIn(evidence_id, ids)
        sun = next(row for row in document["signs"]["comparisons"] if row["point"] == "sun")
        self.assertIn("Твоё Солнце", sun["meaning"])
        self.assertTrue(sun["cross_aspect_ids"])
        self.assertEqual(NatalChart.objects.count(), charts)
        self.assertEqual(OnboardingSession.objects.count(), sessions)
        self.assertEqual(len(self.calls), 2)

    def test_same_input_returns_the_same_report(self):
        self.calls = []
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            first = self.client.post("/api/compatibility/v1/reports/", self._payload(), format="json")
            second = self.client.post("/api/compatibility/v1/reports/", self._payload(), format="json")
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(second.json()["report_id"], first.json()["report_id"])
        self.assertEqual(CompatibilityReport.objects.count(), 1)
        self.assertEqual(len(self.calls), 2)

    def test_unknown_time_drops_angles_houses_and_moon_texts(self):
        self.calls = []
        payload = self._payload()
        payload["persons"][1] = _person(
            "B",
            latitude=55.751234,
            status="unknown",
            birth_date="1993-11-05",
        )
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post("/api/compatibility/v1/reports", payload, format="json")
            report_id = created.json()["report_id"]
            document = self.client.get(f"/api/compatibility/v1/reports/{report_id}/").json()
            raw = self.client.get(f"/api/compatibility/v1/reports/{report_id}").content.decode()
        self.assertEqual(document["meta"]["data_quality"], "partial")
        self.assertTrue(any("Время рождения B неизвестно" in row for row in document["meta"]["warnings"]))
        ids = " ".join(row["id"] for row in document["chart"]["cross_aspects"])
        self.assertNotIn("B-asc", ids)
        self.assertNotIn("B-mc", ids)
        self.assertEqual(document["chart"]["overlays"]["A_in_B"], [])
        points = {row["point"] for row in document["signs"]["comparisons"]}
        self.assertNotIn("moon", points)
        self.assertNotIn("asc", points)
        b_moon = [
            evidence_id
            for insight in document["bond"]["insights"]
            for evidence_id in insight["evidence_ids"]
            if evidence_id.startswith("cross-B-moon") or "-B-moon-" in evidence_id
        ]
        self.assertEqual(b_moon, [])
        b_call = next(call for call in self.calls if call["latitude"] > 54)
        self.assertIsNone(b_call["birth_time"])
        self.assertNotIn("1993-11-05", raw)

    def test_friendship_is_accepted_and_a_mismatched_status_is_rejected(self):
        self.calls = []
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post(
                "/api/compatibility/v1/reports",
                self._payload(relationship_type="friendship", relationship_status="close"),
                format="json",
            )
            self.assertEqual(created.status_code, 202, created.content)
            document = self.client.get(f"/api/compatibility/v1/reports/{created.json()['report_id']}").json()
        self.assertEqual(document["relationship_type"], "friendship")
        self.assertEqual(document["deep_dive"]["conclusion"]["variant"], "growth")
        self.assertNotIn("сексу", json.dumps(document["deep_dive"], ensure_ascii=False).lower())
        mismatch = self.client.post(
            "/api/compatibility/v1/reports",
            self._payload(relationship_type="friendship", relationship_status="together"),
            format="json",
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch.json()["detail"], "Статус связи не подходит к этому типу.")

    def test_unknown_timezone_and_missing_pair_are_400(self):
        payload = self._payload()
        payload["persons"][0]["timezone_id"] = "Not/AZone"
        response = self.client.post("/api/compatibility/v1/reports", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Неизвестная таймзона.")

        missing = self.client.post(
            "/api/compatibility/v1/reports",
            {"relationship_type": "romantic", "persons": [payload["persons"][0]]},
            format="json",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(CompatibilityReport.objects.count(), 0)

    def test_expired_session_does_not_ask_for_login(self):
        response = self.client.post(
            "/api/compatibility/v1/reports",
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Нужны два профиля, A и B.")
        missing = self.client.get(
            "/api/compatibility/v1/reports/00000000-0000-4000-8000-000000000000",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        self.assertEqual(missing.status_code, 404)

    def test_transits_path_validates_horizon_and_stays_pending(self):
        self.calls = []
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post("/api/compatibility/v1/reports", self._payload(), format="json")
        report_id = created.json()["report_id"]
        today = datetime.now(timezone.utc).date()
        current = self.client.get(
            f"/api/compatibility/v1/reports/{report_id}/transits?date={today.isoformat()}"
        )
        self.assertEqual(current.status_code, 200, current.content)
        self.assertEqual(current.json()["status"], "pending")
        self.assertEqual(current.json()["reference_date"], today.isoformat())
        self.assertEqual(current.json()["relationship"], [])

        yesterday = (today - timedelta(days=1)).isoformat()
        too_early = self.client.get(
            f"/api/compatibility/v1/reports/{report_id}/transits/?date={yesterday}"
        )
        self.assertEqual(too_early.status_code, 400)
        self.assertEqual(too_early.json()["detail"], "Дата вне горизонта транзитов.")
        far = self.client.get(f"/api/compatibility/v1/reports/{report_id}/transits?date=2099-01-01")
        self.assertEqual(far.status_code, 400)

    def test_missing_report_is_404(self):
        missing = uuid.uuid4()
        response = self.client.get(f"/api/compatibility/v1/reports/{missing}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Отчёт не найден.")
        transits = self.client.get(f"/api/compatibility/v1/reports/{missing}/transits")
        self.assertEqual(transits.status_code, 404)

    def test_pair_card_follows_digit_sum_and_stays_when_partners_swap(self):
        self.calls = []
        first = self._payload()
        first["persons"][0] = _person("A", latitude=52.231111, birth_date="1991-02-14")
        first["persons"][1] = _person("B", latitude=55.751234, birth_date="1989-11-23")
        second = self._payload()
        second["persons"][0] = _person("A", latitude=52.231111, birth_date="1989-11-23")
        second["persons"][1] = _person("B", latitude=55.751234, birth_date="1991-02-14")
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post("/api/compatibility/v1/reports", first, format="json")
            self.assertEqual(created.status_code, 202, created.content)
            self.assertEqual(created.json()["schema_version"], SCHEMA_VERSION)
            self.assertEqual(set(created.json()["sections"]), {"bond", "transits", "signs", "chart"})
            report_id = created.json()["report_id"]
            read = self.client.get(f"/api/compatibility/v1/reports/{report_id}")
            swapped = self.client.post("/api/compatibility/v1/reports", second, format="json")
            swapped_read = self.client.get(
                f"/api/compatibility/v1/reports/{swapped.json()['report_id']}"
            )
        self.assertEqual(read.status_code, 200, read.content)
        self.assertNotEqual(swapped.json()["report_id"], report_id)
        raw = read.content.decode()
        self.assertNotIn("1991-02-14", raw)
        self.assertNotIn("1989-11-23", raw)
        document = read.json()
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["meta"]["synastry_policy_version"], "synastry-orbs-v1")
        self.assertIn(
            "cross-A-venus-B-mars-trine",
            {row["id"] for row in document["chart"]["cross_aspects"]},
        )
        card = document["pair_card"]
        self.assertEqual(card["formula"], "cosmirror-digit-sum-v1")
        self.assertEqual(
            card["formula_note"],
            "Это выбранная формула Cosmirror, а не универсальное правило Таро.",
        )
        self.assertEqual(
            card["card"],
            {"number": 17, "name": "Звезда", "image": "/images/tarot/ar17.jpg"},
        )
        self.assertEqual(card["persons"][0]["number"], 5)
        self.assertEqual(card["persons"][0]["name"], "Иерофант")
        self.assertEqual(card["persons"][1]["number"], 12)
        self.assertEqual(card["persons"][1]["name"], "Повешенный")
        other = swapped_read.json()["pair_card"]
        self.assertEqual(other["card"]["number"], 17)
        self.assertEqual(other["card"]["image"], "/images/tarot/ar17.jpg")
        self.assertEqual(other["persons"][0]["number"], 12)
        self.assertEqual(other["persons"][1]["number"], 5)
        self.assertEqual(len(self.calls), 4)

    def test_saved_report_receives_pair_card_without_another_natal(self):
        self.calls = []
        with patch("core.services.compatibility.service.calculate_natal", side_effect=self._fake_natal):
            created = self.client.post("/api/compatibility/v1/reports", self._payload(), format="json")
            report_id = created.json()["report_id"]
            report = CompatibilityReport.objects.get(id=report_id)
            stored = dict(report.public_document)
            stored.pop("pair_card", None)
            report.public_document = stored
            report.save(update_fields=["public_document", "updated_at"])
            self.calls.clear()
            read = self.client.get(f"/api/compatibility/v1/reports/{report_id}")
        self.assertEqual(self.calls, [])
        body = read.json()
        self.assertEqual(body["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            body["pair_card"]["card"],
            {"number": 20, "name": "Суд", "image": "/images/tarot/ar20.jpg"},
        )
        self.assertIn(
            "cross-A-venus-B-mars-trine",
            {row["id"] for row in body["chart"]["cross_aspects"]},
        )
        self.assertEqual(len(self.calls), 0)


def _cross(
    aspect_id: str,
    point_a: str,
    point_b: str,
    aspect: str,
    orb: float,
    allowed: float,
    *,
    direction: str = "A_to_B",
    quality: str | None = None,
) -> dict:
    if quality is None:
        quality = "tension" if aspect in {"square", "opposition"} else "harmonizing" if aspect in {"trine", "sextile"} else "mixed"
    return {
        "id": aspect_id,
        "person_a_point": point_a,
        "person_b_point": point_b,
        "aspect": aspect,
        "orb_deg": orb,
        "allowed_orb_deg": allowed,
        "quality": quality,
        "direction": direction,
    }


def _insight_copy() -> dict:
    return {
        "headline": "Сближение здесь может опережать готовность действовать",
        "body": (
            "Алина может предлагать тепло раньше, чем Марк переходит к действию. "
            "То, что выглядит как пауза, может быть другим темпом, а не отказом. "
            "Это базовая связка карт, и её можно проверить на вашем опыте."
        ),
    }


def _writer_document() -> dict:
    return {
        "relationship_type": "romantic",
        "persons": [
            {"id": "A", "display_name": "Алина", "birth_time_status": "known"},
            {"id": "B", "display_name": "Марк", "birth_time_status": "known"},
        ],
        "bond": {
            "status": "ready",
            "insights": [
                {
                    "id": "insight-attraction-0",
                    "category": "attraction",
                    "evidence_ids": ["cross-A-venus-B-mars-trine", "cross-B-mars-A-venus-trine"],
                    "eyebrow": "Венера A тригон Марс B",
                    "title": "Интерес и ответное движение",
                    "snapshot": "Шаблон снимка, который должен остаться при ошибке модели.",
                    "summary": "Между вами Венера A и Марс B образуют тригон.",
                    "deep_read": "Шаблон подробного чтения, который не склеивается с ответом модели.",
                    "perspective": "mutual",
                    "share_text": "Между вами есть эта связка.",
                }
            ],
        },
        "signs": {
            "status": "ready",
            "comparisons": [
                {
                    "id": "signs-sun",
                    "point": "sun",
                    "pair_placements": {
                        "A": {"sign": "gemini", "degree": 5},
                        "B": {"sign": "aquarius", "degree": 25},
                    },
                    "cross_aspect_ids": [],
                    "meaning": "Твоё Солнце в Близнецах, Солнце другого человека в Водолее.",
                    "common_ground": "Общая функция остаётся в шаблоне.",
                    "difference": "Разный знак остаётся в шаблоне.",
                    "evidence_ids": ["signs-sun"],
                }
            ],
        },
        "chart": {
            "cross_aspects": [
                {
                    "id": "cross-A-venus-B-mars-trine",
                    "person_a_point": "venus",
                    "person_b_point": "mars",
                    "aspect": "trine",
                    "orb_deg": 1.2,
                    "allowed_orb_deg": 4.0,
                    "sign_a": "taurus",
                    "sign_b": "cancer",
                    "quality": "harmonizing",
                    "direction": "A_to_B",
                },
                {
                    "id": "cross-A-mercury-B-moon-square",
                    "person_a_point": "mercury",
                    "person_b_point": "moon",
                    "aspect": "square",
                    "orb_deg": 1.0,
                    "allowed_orb_deg": 4.0,
                    "quality": "tension",
                    "direction": "A_to_B",
                },
            ]
        },
        "meta": {},
    }


class CompatibilityWriterTests(SimpleTestCase):
    def test_deep_dive_is_one_story_per_card(self):
        from core.services.compatibility.deep_dive_select import select_deep_dive
        from core.services.compatibility.writers import _deep_section_text

        selected = select_deep_dive(
            [
                _cross("venus-mars", "venus", "mars", "trine", 0.4, 4),
                _cross("mercury-moon", "mercury", "moon", "square", 0.5, 4),
                _cross("moon-saturn", "moon", "saturn", "sextile", 0.6, 3),
                _cross("sun-mars", "sun", "mars", "opposition", 0.7, 5),
            ],
            relationship_type="romantic",
            relationship_status="together",
            persons=[
                {"id": "A", "display_name": "Виктория"},
                {"id": "B", "display_name": "Марк"},
            ],
            natal_anchors={
                "A": [{"id": "natal-A-venus", "a": "venus", "b": "mars", "aspect": "trine"}],
                "B": [{"id": "natal-B-moon", "a": "moon", "b": "saturn", "aspect": "square"}],
            },
        )
        ready = [row for row in selected["sections"] if row["status"] == "ready"]
        self.assertGreaterEqual(len(ready), 3)
        primaries = [row["primary_evidence_id"] for row in ready]
        self.assertEqual(len(primaries), len(set(primaries)))
        headlines = [row["headline"] for row in ready]
        self.assertEqual(len(headlines), len(set(headlines)))
        for row in ready:
            self.assertTrue(row["section_title"])
            self.assertNotIn("perspectives", row)
            self.assertNotIn("takeaway", row)
            self.assertNotIn("person_a", row)
            self.assertIn("\n\n", row["body"])
            self.assertNotRegex(row["body"], r"(?m)^(Ты|Другой человек|Между вами|Инсайт)\s*[:.—]")
            self.assertNotIn("с Марк", row["body"])
            self.assertNotIn("у Марк ", row["body"])
            self.assertEqual(len(row["evidence_ids"]), 1)
            plan = row["analysis"]["story_plan"]
            self.assertEqual(plan["section_id"], row["id"])
            self.assertTrue(plan["central_claim"])
            self.assertTrue(plan["unique_mechanism"])
            self.assertNotIn("story_plan", row["headline"])
            self.assertGreaterEqual(len(row["body"]), 280)
            self.assertLessEqual(len(row["headline"]), 90)
        from core.services.compatibility.story_plan import audit_stories

        self.assertTrue(audit_stories(selected["sections"])["passed"])
        mechanisms = [row["analysis"]["mechanism_id"] for row in ready]
        self.assertEqual(
            mechanisms[:3],
            ["desire_meets_taste", "words_before_feeling", "feeling_needs_contour"],
        )
        self.assertTrue(mechanisms[3].startswith("open-mutual_expression"))
        document = {
            "persons": [
                {"id": "A", "display_name": "Виктория"},
                {"id": "B", "display_name": "Марк"},
            ],
            "relationship_context": {"type": "romantic", "status": "together"},
        }
        rejected = _deep_section_text(
            {
                "headline": "Ясность и пауза сталкиваются раньше спора.",
                "preview": "Это отдельное предложение для закрытой карточки.",
                "body": (
                    "Ты: объяснение появляется раньше, чем успевает сложиться отклик, и разговор уже ищет вывод.\n\n"
                    "Между вами: пауза читается как отказ, хотя это ещё только другой ритм реакции на тот же момент."
                ),
                "perspectives": {"self": "скрыто"},
            },
            document,
        )
        self.assertIsNone(rejected)

    def test_story_plans_keep_four_mechanisms_apart(self):
        from core.services.compatibility.deep_dive_select import select_deep_dive
        from core.services.compatibility.story_plan import audit_stories
        from core.services.compatibility.writers import _deep_section_text

        unknown_moon = _cross("mercury-moon", "mercury", "moon", "opposition", 1.39, 5)
        unknown_moon["bond_eligible"] = False
        selected = select_deep_dive(
            [
                _cross("jupiter-mars", "jupiter", "mars", "conjunction", 0.04, 5),
                _cross("mars-mercury", "mars", "mercury", "trine", 0.34, 4),
                _cross("neptune-venus", "neptune", "venus", "trine", 0.67, 4),
                _cross("venus-mars", "venus", "mars", "opposition", 1.05, 5),
                unknown_moon,
                _cross("venus-sun", "venus", "sun", "opposition", 2.60, 5),
                _cross("saturn-sun", "saturn", "sun", "trine", 1.97, 4),
            ],
            relationship_type="romantic",
            relationship_status="together",
            persons=[
                {"id": "A", "display_name": "Виктория"},
                {"id": "B", "display_name": "Марк"},
            ],
            natal_anchors={
                "A": [
                    {"id": "natal-A-mars-pluto", "a": "mars", "b": "pluto", "aspect": "trine"},
                    {"id": "natal-A-venus-jupiter", "a": "venus", "b": "jupiter", "aspect": "opposition"},
                    {"id": "natal-A-moon-saturn", "a": "moon", "b": "saturn", "aspect": "sextile"},
                    {"id": "natal-A-jupiter-mc", "a": "jupiter", "b": "mc", "aspect": "opposition"},
                ],
                "B": [
                    {"id": "natal-B-mercury-saturn", "a": "mercury", "b": "saturn", "aspect": "sextile"},
                    {"id": "natal-B-mars-uranus", "a": "mars", "b": "uranus", "aspect": "sextile"},
                    {"id": "natal-B-sun-mars", "a": "sun", "b": "mars", "aspect": "conjunction"},
                    {"id": "natal-B-mars-jupiter", "a": "mars", "b": "jupiter", "aspect": "sextile"},
                ],
            },
        )
        by_id = {row["id"]: row for row in selected["sections"]}
        self.assertEqual(
            [by_id[key]["analysis"]["mechanism_id"] for key in (
                "common_ground",
                "differences",
                "values_needs",
                "mutual_expression",
            )],
            [
                "impulse_into_words",
                "affection_meets_will",
                "reliability_meets_direction",
                "horizon_on_drive",
            ],
        )
        self.assertEqual(by_id["common_ground"]["primary_evidence_id"], "mars-mercury")
        self.assertEqual(by_id["differences"]["primary_evidence_id"], "venus-mars")
        self.assertEqual(by_id["values_needs"]["primary_evidence_id"], "saturn-sun")
        self.assertEqual(by_id["mutual_expression"]["primary_evidence_id"], "jupiter-mars")
        self.assertNotIn("neptune-venus", [row["primary_evidence_id"] for row in selected["sections"]])
        self.assertNotIn("venus-sun", [row["primary_evidence_id"] for row in selected["sections"]])
        audit = audit_stories(selected["sections"])
        self.assertTrue(audit["passed"], audit)
        from core.services.compatibility.quality import editorial_issue

        for row in selected["sections"]:
            issue = editorial_issue(f"{row['headline']}\n{row['body']}")
            self.assertIsNone(issue, row["body"])
            blob = f"{row['headline']} {row['body']} {row['analysis']['story_plan']['unique_mechanism']}".casefold()
            for phrase in ("крупнее", "контур", "маленьк", "ставку", "есть вес", "собственный ход", "тепло встречает"):
                self.assertNotIn(phrase, blob, row["id"])
        for row in selected["sections"]:
            plan = row["analysis"]["story_plan"]
            self.assertTrue(plan["person_a_quality"])
            self.assertTrue(plan["person_b_quality"])
            self.assertTrue(plan["must_not_repeat"])
            self.assertGreaterEqual(len(row["body"]), 280)
            self.assertLessEqual(len(row["body"]), 1200)
            self.assertLessEqual(len(row["headline"]), 90)
        banned = _deep_section_text(
            {
                "headline": "Вам важно понимать друг друга в этой связи.",
                "preview": "Это отдельное предложение для закрытой карточки, без повтора.",
                "body": (
                    "Вам важно понимать друг друга, даже когда реакции расходятся и каждый ждёт своего темпа. "
                    "Один проявляет инициативу, другой реагирует, и из этого возникает особое ощущение контакта.\n\n"
                    "Нужно оставлять пространство для каждого, потому что ваши потребности могут различаться и вы можете вдохновлять друг друга."
                ),
            },
            {
                "persons": [
                    {"id": "A", "display_name": "Виктория"},
                    {"id": "B", "display_name": "Марк"},
                ],
                "relationship_context": {"type": "romantic", "status": "together"},
            },
        )
        self.assertIsNone(banned)

    def test_editorial_issue_rejects_empty_metaphor_and_keeps_plain_russian(self):
        from core.services.compatibility.quality import editorial_issue, rejection_reason

        bad = (
            "Рядом с тобой ход Марка становится крупнее.",
            "Твоему теплу тесно в маленьком знаке.",
            "Тебе легче доверять, когда у опоры есть контур.",
            "Форма и собственный ход доказывают близость.",
            "Шаг превращается в ставку.",
            "Движение получает вес.",
        )
        good = (
            "Рядом с тобой Марк может решительнее проявлять инициативу. А ты — легче откликаться на его предложения.",
            "Ты можешь ждать нежного отклика на проявление симпатии, а он — отвечать более резко и прямо.",
            "Тебе может быть важно не только слышать обещания, но и видеть, что человек последовательно их выполняет.",
            "Тебе может быть тесно в роли, которая не оставляет места для более широкой задачи.",
            "Это стало ясно по ходу разговора, а не до него.",
        )
        for text in bad:
            self.assertIsNotNone(editorial_issue(text), text)
            self.assertIn("метафор", rejection_reason(text, kind="deep_dive") or "")
        for text in good:
            self.assertIsNone(editorial_issue(text), text)

    def test_prompts_resolve_before_http(self):
        from core.services.llm_prompts import load_prompt, resolve_model

        self.assertEqual(resolve_model("compatibility_bond"), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model("compatibility_signs"), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model("compatibility_insight"), "openai/gpt-5.6-luna-pro")
        bond = load_prompt("compatibility_bond").body
        signs = load_prompt("compatibility_signs").body
        editorial = load_prompt("compatibility_editorial").body
        blueprint = load_prompt("compatibility_insight_blueprint").body
        self.assertIn("между вами", bond)
        self.assertIn("«вы», «вам», «вас»", bond)
        self.assertNotIn("никого не называй", bond)
        self.assertNotIn("именительном падеже", bond)
        self.assertIn("name_forms", bond)
        self.assertIn("«вы», «вам», «вас»", signs)
        self.assertNotIn("Не используй «вы»/«вам»", signs)
        self.assertNotIn("именительном падеже", signs)
        self.assertIn("name_forms", signs)
        self.assertIn("COMPATIBILITY EDITORIAL", editorial)
        self.assertIn("name_forms", editorial)
        self.assertIn("PERSONAL COMPATIBILITY INSIGHT BLUEPRINT", blueprint)

    def test_writer_facts_omit_birth_data(self):
        import json

        from core.services.compatibility.writers import bond_facts, signs_facts

        raw = json.dumps({"bond": bond_facts(_writer_document()), "signs": signs_facts(_writer_document())}, ensure_ascii=False)
        self.assertNotIn("birth_date", raw)
        self.assertNotIn("latitude", raw)
        self.assertNotIn("timezone", raw)
        self.assertIn("Алина", raw)
        self.assertIn("cross-A-venus-B-mars-trine", raw)

    def test_insight_slot_keeps_one_aspect_and_base_frame(self):
        from core.services.compatibility.insight import basis_line, build_insight_slot
        from core.services.compatibility.writers import insight_facts

        slot = build_insight_slot(_writer_document())
        self.assertEqual(slot["status"], "ready")
        self.assertEqual(slot["temporal_frame"], "base")
        self.assertEqual(slot["theme_id"], "communication_vs_feelings")
        self.assertEqual(slot["evidence_ids"], ["cross-A-mercury-B-moon-square"])
        self.assertEqual(slot["basis"], "Меркурий у Алины в квадрате к Луне у Марка")
        self.assertNotIn("прямо сейчас", slot["body"])
        self.assertNotIn("cross-A-venus-B-mars-trine", slot["evidence_ids"])
        self.assertLessEqual(len(slot["title"]), 90)
        self.assertEqual(
            basis_line("moon", "Алина", "conjunction", "venus", "Марк"),
            "Луна у Алины в соединении с Венерой у Марка",
        )
        facts = json.dumps(insight_facts(_writer_document()), ensure_ascii=False)
        self.assertNotIn("birth_date", facts)
        self.assertIn("nominative", facts)
        self.assertIn("communication_vs_feelings", facts)
        self.assertIn('"current_modifier": null', facts)

    def test_insight_without_evidence_stays_unavailable(self):
        from core.services.compatibility.insight import build_insight_slot

        document = _writer_document()
        document["chart"]["cross_aspects"] = []
        document["bond"]["insights"][0]["evidence_ids"] = []
        slot = build_insight_slot(document)
        self.assertEqual(slot["status"], "unavailable")
        self.assertEqual(slot["title"], "")
        self.assertEqual(slot["evidence_ids"], [])

    def test_blueprint_counts_two_pairs_and_ignores_the_mirror(self):
        from core.services.compatibility.insight_select import aspect_signal, select_opening

        self.assertAlmostEqual(
            aspect_signal(
                {
                    "person_a_point": "mercury",
                    "person_b_point": "moon",
                    "orb_deg": 1,
                    "allowed_orb_deg": 4,
                }
            ),
            1.1375,
            places=4,
        )
        document = _writer_document()
        document["chart"]["cross_aspects"] = [
            _cross("cross-A-mercury-B-moon-square", "mercury", "moon", "square", 1, 4),
            _cross("cross-B-moon-A-mercury-square", "mercury", "moon", "square", 1, 4, direction="B_to_A"),
            _cross("cross-A-moon-B-mercury-square", "moon", "mercury", "square", 2, 4),
        ]
        opening = select_opening(document)
        self.assertEqual(opening["theme_id"], "communication_vs_feelings")
        self.assertAlmostEqual(opening["astro_score"], 1.57625, places=4)
        self.assertEqual(
            [row["id"] for row in opening["aspects"]],
            ["cross-A-mercury-B-moon-square", "cross-A-moon-B-mercury-square"],
        )

    def test_strong_harmony_beats_a_weaker_tension(self):
        from core.services.compatibility.insight_select import select_opening

        document = _writer_document()
        document["chart"]["cross_aspects"] = [
            _cross("cross-A-mercury-B-mercury-trine", "mercury", "mercury", "trine", 0.8, 4, quality="harmonizing"),
            _cross("cross-A-sun-B-mercury-trine", "sun", "mercury", "trine", 1, 4, quality="harmonizing"),
            _cross("cross-A-mars-B-mercury-square", "mars", "mercury", "square", 3.6, 4),
        ]
        opening = select_opening(document)
        self.assertEqual(opening["theme_id"], "shared_language")
        self.assertEqual(opening["polarity"], "supportive")
        self.assertEqual(opening["aspects"][0]["id"], "cross-A-mercury-B-mercury-trine")
        self.assertNotIn("cross-A-mars-B-mercury-square", [row["id"] for row in opening["aspects"]])

    def test_unknown_time_drops_the_other_persons_moon(self):
        from core.services.compatibility.insight_select import select_opening

        document = _writer_document()
        document["persons"][1]["birth_time_status"] = "unknown"
        document["chart"]["cross_aspects"] = [
            _cross("cross-A-mercury-B-moon-square", "mercury", "moon", "square", 1, 4),
        ]
        self.assertIsNone(select_opening(document))

    def test_same_aspect_reads_differently_for_family(self):
        from core.services.compatibility.insight import build_insight_slot

        romantic = build_insight_slot(_writer_document())
        family = _writer_document()
        family["relationship_type"] = "family"
        family_slot = build_insight_slot(family)
        self.assertEqual(romantic["theme_id"], family_slot["theme_id"])
        self.assertNotEqual(romantic["body"], family_slot["body"])
        lowered = family_slot["body"].casefold()
        self.assertNotIn("сексу", lowered)
        self.assertNotIn("поцел", lowered)

    def test_opening_fallbacks_stay_short_and_complete(self):
        from core.services.compatibility.insight_select import _TEXTS, insight_copy

        for (theme, polarity, relationship), (headline, body) in _TEXTS.items():
            title, text = insight_copy(theme, polarity, relationship, "Алина", "Марк")
            self.assertEqual(title, headline)
            self.assertLessEqual(len(title), 90, title)
            self.assertGreaterEqual(len(text), 120, text)
            self.assertLessEqual(len(text), 420, text)
            self.assertNotIn("прямо сейчас", text.casefold())
            self.assertNotIn("{a}", text)
            self.assertNotIn("{b}", text)

    def test_current_claim_keeps_fallback_insight(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()
        fallback = None

        def fake_chat(**kwargs):
            nonlocal fallback
            if kwargs["prompt_id"] == "compatibility_insight":
                fallback = document["insight"]["title"]
                copy = _insight_copy()
                copy["body"] = copy["body"].replace("Это базовая", "Прямо сейчас это базовая")
                return copy
            if kwargs["prompt_id"] == "compatibility_bond":
                return {"insights": []}
            return {"comparisons": []}

        with (
            patch("core.services.compatibility.writers.llm_client.active_provider", return_value="polza"),
            patch("core.services.compatibility.writers.llm_client.chat_json", side_effect=fake_chat),
        ):
            enrich_document(document)

        self.assertEqual(document["insight"]["title"], fallback)
        self.assertNotIn("Прямо сейчас", document["insight"]["body"])
        self.assertEqual(document["meta"]["writers"]["insight"], "fallback")

    def test_polza_replaces_texts_and_keeps_facts(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()
        seen = []

        def fake_chat(**kwargs):
            seen.append(kwargs["prompt_id"])
            self.assertNotIn("birth_date", kwargs["user"])
            if kwargs["prompt_id"] == "compatibility_bond":
                self.assertIn("GOLD STANDARD", kwargs["system"])
                self.assertNotIn("INSIGHT BLUEPRINT", kwargs["system"])
                self.assertNotIn("COMPATIBILITY EDITORIAL", kwargs["system"])
                self.assertNotIn("Имя B оставляй", kwargs["system"])
                return {
                    "insights": [
                        {
                            "id": "insight-attraction-0",
                            "category": "trials",
                            "evidence_ids": ["invented"],
                            "title": "Разговор держит интерес",
                            "snapshot": "Интерес можно назвать вслух, не решая за другого человека, чего он хочет.",
                            "summary": "Твой темп сближения и темп Марк могут встречаться в одном разговоре, и это можно проверить между вами.",
                            "deep_read": "Если разговор ускоряется, пауза не отменяет интерес. Это гипотеза про ритм, а не про чувства Марк.",
                            "share_text": "Между вами интерес можно назвать вслух.",
                        }
                    ]
                }
            if kwargs["prompt_id"] == "compatibility_insight":
                self.assertIn("GOLD STANDARD", kwargs["system"])
                self.assertNotIn("INSIGHT BLUEPRINT", kwargs["system"])
                self.assertIn("communication_vs_feelings", kwargs["user"])
                return _insight_copy()
            return {
                "comparisons": [
                    {
                        "id": "signs-sun",
                        "meaning": "Ты быстрее переходишь к ясной формулировке, а Марк может держать тему шире. Это гипотеза, не факт о его мыслях.",
                        "common_ground": "Оба способа ищут, как проявиться.",
                        "difference": "Один способ уже называет мысль, другой оставляет ей больше воздуха.",
                    }
                ]
            }

        with (
            patch("core.services.compatibility.writers.llm_client.active_provider", return_value="polza"),
            patch("core.services.compatibility.writers.llm_client.chat_json", side_effect=fake_chat),
        ):
            enrich_document(document)

        insight = document["bond"]["insights"][0]
        self.assertEqual(sorted(seen), ["compatibility_bond", "compatibility_insight", "compatibility_signs"])
        self.assertEqual(insight["title"], "Разговор держит интерес")
        self.assertEqual(insight["category"], "attraction")
        self.assertEqual(insight["evidence_ids"][0], "cross-A-venus-B-mars-trine")
        self.assertEqual(insight["eyebrow"], "Венера A тригон Марс B")
        comparison = document["signs"]["comparisons"][0]
        self.assertIn("Ты быстрее", comparison["meaning"])
        self.assertEqual(comparison["pair_placements"]["A"]["sign"], "gemini")
        self.assertEqual(comparison["evidence_ids"], ["signs-sun"])
        personal = document["insight"]
        self.assertEqual(personal["title"], _insight_copy()["headline"])
        self.assertEqual(personal["evidence_ids"], ["cross-A-mercury-B-moon-square"])
        self.assertEqual(personal["basis"], "Меркурий у Алины в квадрате к Луне у Марка")
        self.assertEqual(
            document["meta"]["writers"],
            {"bond": "llm", "signs": "llm", "insight": "llm", "provider": "polza"},
        )

    def test_groq_is_not_called(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()
        with (
            patch("core.services.compatibility.writers.llm_client.active_provider", return_value="groq"),
            patch("core.services.compatibility.writers.llm_client.chat_json") as chat,
        ):
            enrich_document(document)
        chat.assert_not_called()
        self.assertIn("Между вами", document["bond"]["insights"][0]["summary"])
        self.assertEqual(document["meta"]["writers"]["provider"], "groq")
        self.assertEqual(document["meta"]["writers"]["bond"], "fallback")
        self.assertEqual(document["meta"]["writers"]["insight"], "fallback")
        self.assertIn("Алины", document["insight"]["basis"])

    def test_invalid_bond_does_not_erase_signs(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()

        def fake_chat(**kwargs):
            if kwargs["prompt_id"] == "compatibility_bond":
                return {"insights": [{"id": "insight-attraction-0", "title": "коротко"}]}
            return {
                "comparisons": [
                    {
                        "id": "signs-sun",
                        "meaning": "Ты быстрее переходишь к ясной формулировке, а Марк может держать тему шире. Это гипотеза, не факт о его мыслях.",
                        "common_ground": "Оба способа ищут, как проявиться.",
                        "difference": "Один способ уже называет мысль, другой оставляет ей больше воздуха.",
                    }
                ]
            }

        with (
            patch("core.services.compatibility.writers.llm_client.active_provider", return_value="polza"),
            patch("core.services.compatibility.writers.llm_client.chat_json", side_effect=fake_chat),
        ):
            enrich_document(document)

        self.assertIn("Между вами", document["bond"]["insights"][0]["summary"])
        self.assertEqual(document["bond"]["insights"][0]["title"], "Интерес и ответное движение")
        self.assertIn("Ты быстрее", document["signs"]["comparisons"][0]["meaning"])
        self.assertEqual(document["meta"]["writers"]["bond"], "fallback")
        self.assertEqual(document["meta"]["writers"]["signs"], "llm")
        self.assertEqual(document["meta"]["writers"]["insight"], "fallback")

    def test_banned_phrase_keeps_the_whole_section(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()

        def fake_chat(**kwargs):
            if kwargs["prompt_id"] == "compatibility_bond":
                return {
                    "insights": [
                        {
                            "id": "insight-attraction-0",
                            "title": "Вам это суждено навсегда",
                            "snapshot": "Интерес можно назвать вслух, не решая за другого человека, чего он хочет.",
                            "summary": "Твой темп сближения и темп Марк могут встречаться в одном разговоре, и это можно проверить между вами.",
                            "deep_read": "Если разговор ускоряется, пауза не отменяет интерес. Это гипотеза про ритм, а не про чувства Марк.",
                            "share_text": "Между вами интерес можно назвать вслух.",
                        }
                    ]
                }
            return {"comparisons": []}

        with (
            patch("core.services.compatibility.writers.llm_client.active_provider", return_value="polza"),
            patch("core.services.compatibility.writers.llm_client.chat_json", side_effect=fake_chat),
        ):
            enrich_document(document)

        self.assertEqual(document["bond"]["insights"][0]["title"], "Интерес и ответное движение")
        self.assertIn("Твоё Солнце", document["signs"]["comparisons"][0]["meaning"])
        self.assertEqual(document["meta"]["writers"]["bond"], "fallback")
        self.assertEqual(document["meta"]["writers"]["signs"], "fallback")
        self.assertEqual(document["meta"]["writers"]["insight"], "fallback")


class ScoringPolicyTests(SimpleTestCase):
    def test_documented_formulas(self):
        from core.services.compatibility.scoring import harmony_percent, motif_percent

        self.assertEqual(harmony_percent(4.8, 2.6), 60)
        self.assertIsNone(harmony_percent(0, 0))
        self.assertEqual(motif_percent(1.8, 1.6), 68)
        self.assertEqual(motif_percent(0, 1.6), 0)

    def test_mirror_does_not_change_indices_but_reciprocal_pairs_do(self):
        base = [_score_aspect("venus-mars", "venus", "mars", "trine", 0.4, 4)]
        mirror = base + [{**base[0], "id": "mirror", "direction": "B_to_A"}]
        reciprocal = base + [_score_aspect("mars-venus", "mars", "venus", "trine", 0.4, 4)]
        self.assertEqual(_score(base), _score(mirror))
        self.assertGreater(_score(reciprocal)["harmony"]["value"], _score(base)["harmony"]["value"])

    def test_node_axis_counts_once_and_a_different_contact_still_counts(self):
        north = _score_aspect("north-sun", "north_node", "sun", "conjunction", 0, 3)
        south = _score_aspect("south-sun", "south_node", "sun", "opposition", 0, 3)
        square = _score_aspect("north-mars", "north_node", "mars", "square", 0, 3)
        one = _score([north])["karmic_patterns"]["value"]
        same_axis = _score([north, south])["karmic_patterns"]
        extra = _score([north, square])["karmic_patterns"]["value"]
        self.assertEqual(same_axis["value"], one)
        self.assertEqual(len(same_axis["top_factors"]), 1)
        self.assertGreater(extra, one)

    def test_orb_boundary_is_included_and_tighter_orb_raises_harmony(self):
        inside = _score([_score_aspect("edge", "sun", "moon", "trine", 4, 4)])
        outside = _score([_score_aspect("past", "sun", "moon", "trine", 4.01, 4)])
        wide = _score([_score_aspect("wide", "sun", "moon", "trine", 3, 4)])
        tight = _score([_score_aspect("tight", "sun", "moon", "trine", 0.2, 4)])
        self.assertIsNotNone(inside["harmony"]["value"])
        self.assertIsNone(outside["harmony"]["value"])
        self.assertEqual(outside["karmic_patterns"]["value"], 0)
        self.assertGreater(tight["harmony"]["value"], wide["harmony"]["value"])

    def test_unspecified_conjunction_is_mixed_and_not_extreme(self):
        row = _score([_score_aspect("sun-mercury", "sun", "mercury", "conjunction", 0, 5)])
        value = row["harmony"]["value"]
        self.assertGreater(value, 0)
        self.assertLess(value, 100)
        self.assertEqual(row["harmony"]["top_factors"][0]["contribution_type"], "mixed")

    def test_same_input_is_stable_and_question_text_is_ignored(self):
        first = [_score_aspect("venus-mars", "venus", "mars", "trine", 1, 4)]
        second = [{**first[0], "user_question": "почему он меня не выбрал?", "relationship_status": "ended"}]
        self.assertEqual(_score(first), _score(list(reversed(second))))

    def test_relationship_type_changes_only_harmony(self):
        aspects = [
            _score_aspect("venus-mars", "venus", "mars", "trine", 0, 4),
            _score_aspect("saturn-sun", "saturn", "sun", "square", 0.5, 4),
        ]
        scored = {kind: _score(aspects, relationship_type=kind) for kind in ("romantic", "friendship", "family")}
        harmonies = {kind: row["harmony"]["value"] for kind, row in scored.items()}
        self.assertEqual(len(set(harmonies.values())), 3)
        self.assertEqual(
            scored["romantic"]["karmic_patterns"]["value"],
            scored["friendship"]["karmic_patterns"]["value"],
        )
        self.assertEqual(
            scored["friendship"]["karmic_patterns"]["value"],
            scored["family"]["karmic_patterns"]["value"],
        )
        self.assertEqual(
            scored["romantic"]["transformation"]["value"],
            scored["family"]["transformation"]["value"],
        )
        family = json.dumps(scored["family"], ensure_ascii=False).lower()
        for word in ("сексу", "поцел", "влюб", "романт", "вероятност", "%"):
            self.assertNotIn(word, family)
        self.assertIn("виктории", family)
        self.assertNotIn("солнце виктории", family)

    def test_unknown_time_omits_moon_and_angles_without_a_penalty(self):
        base = [_score_aspect("sun-venus", "sun", "venus", "trine", 0.4, 4)]
        moon = _score_aspect("b-moon", "saturn", "moon", "square", 0.2, 4)
        angle = _score_aspect("b-asc", "sun", "asc", "conjunction", 0.1, 3)
        known = _score(base, persons=_people("known", "known"))
        unknown = _score(base + [moon, angle], persons=_people("known", "unknown"))
        both = _score(base, persons=_people("unknown", "unknown"))
        self.assertEqual(unknown["harmony"]["value"], known["harmony"]["value"])
        self.assertEqual(both["harmony"]["value"], known["harmony"]["value"])
        self.assertEqual(unknown["harmony"]["status"], "limited")
        self.assertEqual(unknown["harmony"]["confidence"], "medium")
        self.assertEqual(both["harmony"]["confidence"], "low")
        evidence = {row["evidence_id"] for row in unknown["harmony"]["top_factors"]}
        self.assertNotIn("b-moon", evidence)
        self.assertNotIn("b-asc", evidence)
        self.assertTrue(unknown["omitted_factors"])

    def test_slow_pair_alone_does_not_raise_transformation(self):
        row = _score([_score_aspect("uranus-neptune", "uranus", "neptune", "trine", 0, 4)])
        self.assertEqual(row["transformation"]["value"], 0)
        self.assertEqual(row["transformation"]["status"], "ready")
        self.assertIsNone(row["harmony"]["value"])
        self.assertEqual(row["harmony"]["status"], "unavailable")

    def test_top_four_motifs_cap_the_karmic_sum(self):
        bodies = ("sun", "moon", "mercury", "venus", "mars")
        aspects = [_score_aspect(f"pluto-{body}", "pluto", body, "square", 0, 4) for body in bodies]
        three = _score(aspects[:3])["karmic_patterns"]["value"]
        four = _score(aspects[:4])["karmic_patterns"]["value"]
        five = _score(aspects)["karmic_patterns"]
        self.assertLess(three, four)
        self.assertEqual(four, five["value"])
        self.assertEqual(len(five["top_factors"]), 4)

    def test_tension_scan_and_conclusion_route(self):
        from core.services.compatibility.active_cycles_select import select_active_cycles
        from core.services.compatibility.conclusion_select import variant_for
        from core.services.compatibility.scoring import score_current_tension

        empty = score_current_tension([], [], [], reference_instant_utc="2026-10-31T12:00:00Z")
        self.assertEqual(empty["value"], 0)
        self.assertEqual(empty["status"], "ready")
        hit = {"transit": "saturn", "natal": "sun", "aspect": "square", "orb": 0.4}
        found = score_current_tension([hit], [], [], reference_instant_utc="2026-10-31T12:00:00Z")
        self.assertGreater(found["value"], 0)
        self.assertNotIn("%", found["summary"])
        self.assertEqual(variant_for("romantic", "ended"), "reflection")
        self.assertEqual(variant_for("family", "active"), "growth")
        self.assertEqual(variant_for("family", "no_contact"), "reflection")
        self.assertIsNone(variant_for("romantic", None))
        cycles = select_active_cycles(
            {
                "A": [
                    {
                        "transit": "jupiter",
                        "natal": "sun",
                        "aspect": "trine",
                        "orb": 0.5,
                        "motion": "applying",
                        "polarity": "support",
                    }
                ],
                "B": [],
            },
            as_of_utc="2026-10-31T12:00:00Z",
            birth_time_status={"A": "known", "B": "unknown"},
            names={"A": "Алина", "B": "Марк"},
            relationship_type="family",
            relationship_status="no_contact",
        )
        self.assertEqual(cycles["persons"]["A"]["status"], "ready")
        self.assertIn("jupiter", cycles["persons"]["A"]["cycle_id"])
        self.assertIn("не повод", cycles["persons"]["A"]["interpretation"]["relationship_lens"])
        self.assertEqual(cycles["persons"]["B"]["reason_code"], "no_significant_active_cycle")
        self.assertIsNone(cycles["persons"]["B"]["interpretation"])
        from core.services.compatibility.service import redact_premium

        hidden = redact_premium(
            {
                "deep_dive": {
                    "sections": [
                        {
                            "headline": "скрытая мысль",
                            "body": "скрытый текст",
                            "preview": "тизер",
                            "access": "full",
                        }
                    ],
                    "conclusion": {"headline": "итог", "summary": "текст", "potential_or_meaning": "ещё"},
                },
                "active_cycles": {"persons": {"A": {"interpretation": {"headline": "цикл"}}}},
            }
        )
        self.assertIsNone(hidden["deep_dive"]["sections"][0]["headline"])
        self.assertIsNone(hidden["deep_dive"]["sections"][0]["body"])
        self.assertEqual(hidden["deep_dive"]["sections"][0]["preview"], "тизер")
        self.assertNotIn("perspectives", hidden["deep_dive"]["sections"][0])
        self.assertIsNone(hidden["deep_dive"]["conclusion"]["summary"])
        self.assertIsNone(hidden["active_cycles"]["persons"]["A"]["interpretation"])

    def test_pending_tension_and_empty_scan(self):
        empty = _score([])
        missing = _score(None)
        self.assertEqual(empty["karmic_patterns"]["value"], 0)
        self.assertEqual(empty["karmic_patterns"]["status"], "ready")
        self.assertIn("не выражен", empty["karmic_patterns"]["summary"])
        self.assertEqual(empty["transformation"]["value"], 0)
        self.assertIsNone(empty["harmony"]["value"])
        self.assertIsNone(missing["karmic_patterns"]["value"])
        self.assertEqual(missing["karmic_patterns"]["status"], "unavailable")
        for row in (empty, missing):
            self.assertIsNone(row["current_tension"]["value"])
            self.assertEqual(row["current_tension"]["status"], "pending")
            self.assertCountEqual(
                ("harmony", "karmic_patterns", "current_tension", "transformation"),
                (key for key in row if key in {"harmony", "karmic_patterns", "current_tension", "transformation"}),
            )

    def test_nonzero_factor_uses_a_real_evidence_id(self):
        aspect = _score_aspect("saturn-sun", "saturn", "sun", "square", 0.8, 4)
        row = _score([aspect])
        factor = row["karmic_patterns"]["top_factors"][0]
        self.assertEqual(factor["evidence_id"], "saturn-sun")
        self.assertGreater(row["karmic_patterns"]["value"], 0)
        self.assertGreater(row["transformation"]["value"], 0)
        self.assertIn("Виктории", factor["aspect_ru"])
        self.assertIn("квадрате", factor["aspect_ru"])
        self.assertNotIn(" — ", factor["aspect_ru"])
        self.assertNotIn("Пропущенные", row["harmony"]["summary"])
        limited = _score([aspect], persons=_people("known", "unknown"))
        self.assertNotIn("Пропущенные", limited["harmony"]["summary"])
        from core.services.compatibility.writers import _has_repeat

        self.assertTrue(_has_repeat(["Общий ход появляется там, где разговор встречает действие."] * 2))
        self.assertFalse(
            _has_repeat(
                [
                    "Общий ход появляется там, где разговор встречает действие.",
                    "Это видно, когда разговор не зависает без ответа.",
                ]
            )
        )

    def test_index_summaries_name_the_aspect_and_skip_role_glue(self):
        from core.services.compatibility.quality import rejection_reason
        from core.services.compatibility.scoring import score_current_tension

        aspect = _score_aspect("venus-mars", "venus", "mars", "opposition", 0.4, 5)
        row = _score([aspect])
        harmony = row["harmony"]["summary"]
        karmic = row["karmic_patterns"]["summary"]
        shift = row["transformation"]["summary"]
        self.assertIn("Венер", harmony)
        self.assertIn("Марс", harmony)
        self.assertNotIn("в контакте больше опоры", harmony.casefold())
        self.assertIn("ограничено по глубине", harmony.casefold())
        self.assertNotIn("повторяющаяся тема собрана", karmic.casefold())
        self.assertNotIn("привычный ход сдвигают", shift.casefold())
        self.assertIsNone(rejection_reason(harmony, kind="deep_dive"))
        zero = score_current_tension(
            [],
            [],
            [],
            reference_instant_utc="2026-10-31T12:00:00Z",
            persons=_people("known", "unknown"),
        )
        self.assertEqual(zero["value"], 0)
        self.assertIn("не найдено", zero["summary"])
        self.assertIn("Марка", zero["summary"])
        self.assertNotIn("не снижают", zero["summary"])
        self.assertIsNotNone(
            rejection_reason(
                "Разговор помогает вашей инициативе становиться делом.",
                kind="insight",
            )
        )
        self.assertIsNotNone(
            rejection_reason(
                "Повторяющаяся тема собрана так: глубина перемен и разговор и границы.",
                kind="index",
                factors=[{"aspect_ru": "Плутон у Виктории в соединении с Меркурием у Марка"}],
                value=29,
            )
        )
        self.assertIsNotNone(
            rejection_reason(
                "С некоторыми людьми не нужно постоянно подбирать слова. Это про вас.",
                kind="insight",
            )
        )

    def test_insight_facts_carry_natal_anchors_for_the_chosen_points(self):
        from core.services.compatibility.writers import insight_facts

        document = _writer_document()
        document["natal_anchors"] = {
            "A": [
                {"id": "natal-A-mercury-saturn", "a": "mercury", "b": "saturn", "aspect": "square"},
                {"id": "natal-A-venus-jupiter", "a": "venus", "b": "jupiter", "aspect": "trine"},
            ],
            "B": [
                {"id": "natal-B-moon-mars", "a": "moon", "b": "mars", "aspect": "square"},
            ],
        }
        facts = insight_facts(document)
        self.assertEqual(facts["natal_anchors"]["A"][0]["id"], "natal-A-mercury-saturn")
        self.assertEqual(facts["natal_anchors"]["B"][0]["a"], "moon")
        self.assertNotIn("natal-A-venus-jupiter", [row["id"] for row in facts["natal_anchors"]["A"]])
        self.assertEqual(facts["relationship_context"]["type"], "romantic")


def _score(aspects, *, relationship_type="romantic", persons=None):
    from core.services.compatibility.scoring import score_compatibility

    return score_compatibility(
        aspects,
        relationship_type=relationship_type,
        persons=persons if persons is not None else _people("known", "known"),
    )


def _people(status_a: str, status_b: str) -> list[dict]:
    return [
        {"id": "A", "display_name": "Виктория", "birth_time_status": status_a},
        {"id": "B", "display_name": "Марк", "birth_time_status": status_b},
    ]


def _score_aspect(evidence_id: str, point_a: str, point_b: str, aspect: str, orb: float, allowed: float) -> dict:
    row = _cross(evidence_id, point_a, point_b, aspect, orb, allowed)
    row["bond_eligible"] = True
    return row

