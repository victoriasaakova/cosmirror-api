"""Маршруты пары и синастрия synastry_orbs_v1. Эфемериды здесь не вызываются."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from core.models import CompatibilityReport, NatalChart, OnboardingSession
from core.services.compatibility.bond import build_bond
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
            self.assertEqual(body["schema_version"], "compatibility-v1")
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
        self.assertIsNone(document["bond"]["overall_bond_label"])
        self.assertEqual(document["meta"]["synastry_policy_version"], "synastry-orbs-v1")
        self.assertEqual(document["meta"]["data_quality"], "full")
        self.assertEqual(document["transits"]["status"], "pending")
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

    def test_other_relationship_is_rejected(self):
        charts = NatalChart.objects.count()
        response = self.client.post(
            "/api/compatibility/v1/reports",
            self._payload(relationship_type="friendship"),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "В этой версии поддерживается только romantic.")
        self.assertNotIn("52.231111", response.content.decode())
        self.assertEqual(CompatibilityReport.objects.count(), 0)
        self.assertEqual(NatalChart.objects.count(), charts)

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
                    "sign_a": "taurus",
                    "sign_b": "cancer",
                    "quality": "harmonizing",
                    "direction": "A_to_B",
                }
            ]
        },
        "meta": {},
    }


class CompatibilityWriterTests(SimpleTestCase):
    def test_prompts_resolve_before_http(self):
        from core.services.llm_prompts import load_prompt, resolve_model

        self.assertEqual(resolve_model("compatibility_bond"), "openai/gpt-5.6-luna-pro")
        self.assertEqual(resolve_model("compatibility_signs"), "openai/gpt-5.6-luna-pro")
        bond = load_prompt("compatibility_bond").body
        signs = load_prompt("compatibility_signs").body
        self.assertIn("между вами", bond)
        self.assertIn("«вы», «вам», «вас»", bond)
        self.assertNotIn("никого не называй", bond)
        self.assertIn("«вы», «вам», «вас»", signs)
        self.assertNotIn("Не используй «вы»/«вам»", signs)

    def test_writer_facts_omit_birth_data(self):
        import json

        from core.services.compatibility.writers import bond_facts, signs_facts

        raw = json.dumps({"bond": bond_facts(_writer_document()), "signs": signs_facts(_writer_document())}, ensure_ascii=False)
        self.assertNotIn("birth_date", raw)
        self.assertNotIn("latitude", raw)
        self.assertNotIn("timezone", raw)
        self.assertIn("Алина", raw)
        self.assertIn("cross-A-venus-B-mars-trine", raw)

    def test_polza_replaces_texts_and_keeps_facts(self):
        from core.services.compatibility.writers import enrich_document

        document = _writer_document()
        seen = []

        def fake_chat(**kwargs):
            seen.append(kwargs["prompt_id"])
            self.assertNotIn("birth_date", kwargs["user"])
            if kwargs["prompt_id"] == "compatibility_bond":
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
        self.assertEqual(sorted(seen), ["compatibility_bond", "compatibility_signs"])
        self.assertEqual(insight["title"], "Разговор держит интерес")
        self.assertEqual(insight["category"], "attraction")
        self.assertEqual(insight["evidence_ids"][0], "cross-A-venus-B-mars-trine")
        self.assertEqual(insight["eyebrow"], "Венера A тригон Марс B")
        comparison = document["signs"]["comparisons"][0]
        self.assertIn("Ты быстрее", comparison["meaning"])
        self.assertEqual(comparison["pair_placements"]["A"]["sign"], "gemini")
        self.assertEqual(comparison["evidence_ids"], ["signs-sun"])
        self.assertEqual(document["meta"]["writers"], {"bond": "llm", "signs": "llm", "provider": "polza"})

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

