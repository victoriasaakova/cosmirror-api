"""PDF render payload and natal wheel SVG — without rewriting pdf_report layout."""

from __future__ import annotations

from datetime import date, time

from django.test import TestCase

from core.services.natal_wheel_svg import render_natal_wheel_svg
from core.services.pdf_payload import build_pdf_render_payload, pdf_sections
from core.services.report_blueprint import build_report_document, flatten_document_sections
from core.services.report_facts import chart_wheel, natal_aspects
from core.services.report_types import PDF_OUTLINE, WEB_TABS
from core.services.swiss_engine import calculate_natal
from core.test_natal_chart import GDYNIA


class PdfPayloadTests(TestCase):
    def test_outline_is_independent_of_web_tabs_constant(self):
        self.assertEqual([tab["id"] for tab in WEB_TABS], PDF_OUTLINE)
        self.assertEqual(PDF_OUTLINE, ["natal", "aspects", "cycles", "request", "practice"])

    def test_payload_uses_pdf_outline_and_keeps_factual_natal(self):
        natal = calculate_natal(**GDYNIA)
        document = build_report_document(natal=natal, sky_now={}, quiz={})
        report = {
            "title": "Персональный астрологический отчёт",
            "subtitle": "test",
            "disclaimer": "disclaimer",
            "person": {"birth_date": "1995-05-26"},
            "document": document,
        }
        payload = build_pdf_render_payload(report)
        self.assertEqual(payload["outline"], PDF_OUTLINE)
        self.assertEqual([section["id"] for section in payload["sections"]], PDF_OUTLINE)
        self.assertEqual(payload["source_paths"]["natal_table"], "document.factual.natal.points")
        self.assertEqual(payload["source_paths"]["natal_aspects"], "document.factual.natal.aspects")

        sun = next(row for row in payload["natal_table"] if row["key"] == "sun")
        self.assertEqual(sun["sign_ru"], "Близнецы")
        self.assertIsInstance(sun["degree"], int)
        self.assertIsInstance(sun["minute"], int)
        self.assertTrue(sun.get("house"))
        self.assertIn("retrograde", sun)

        aspect = payload["natal_aspects"][0]
        self.assertTrue(aspect.get("aspect"))
        self.assertIn(aspect.get("kind"), {"hard", "soft"})
        self.assertIsInstance(aspect.get("orb"), float)

        self.assertEqual(len(payload["houses"]), 12)
        self.assertTrue(payload["wheel"].get("planets"))
        self.assertTrue(payload["wheel"].get("aspects"))

        web_linear = flatten_document_sections(document)
        self.assertEqual([row["id"] for row in web_linear], [tab["id"] for tab in WEB_TABS])
        natal_section = next(row for row in payload["sections"] if row["id"] == "natal")
        self.assertTrue(natal_section["blocks"])
        self.assertIn("questions", natal_section)
        self.assertIn("core_portrait", payload["interpretive"]["natal"] or {})

    def test_pdf_sections_follow_outline_not_dict_insertion(self):
        document = {
            "sections": {
                "practice": {"title": "Практика", "blocks": []},
                "natal": {"title": "Твоя карта", "blocks": [{"title": "A", "text": "B", "kind": "x"}]},
            }
        }
        sections = pdf_sections(document)
        self.assertEqual([row["id"] for row in sections], ["natal", "practice"])
        self.assertEqual(sections[0]["blocks"][0]["kind"], "x")


class PdfHtmlTests(TestCase):
    def test_html_keeps_all_chapters_and_one_wheel(self):
        from core.services.pdf_html import render_report_html
        from core.services.swiss_engine import calculate_sky_now

        natal = calculate_natal(**GDYNIA)
        document = build_report_document(
            natal=natal,
            sky_now=calculate_sky_now(),
            quiz={"name": "Виктория"},
        )
        html = render_report_html(
            {
                "title": "Персональный астрологический отчёт",
                "disclaimer": "Это не прогноз будущего и не замена терапии.",
                "person": {
                    "name": "Виктория",
                    "birth_date": "1995-05-26",
                    "birth_time": "19:25",
                    "birth_place": "Гдыня",
                    "has_birth_time": True,
                },
                "document": document,
            }
        )
        self.assertEqual(html.count('class="wheel"'), 1)
        self.assertEqual(html.count('class="cover"'), 1)
        self.assertIn("Виктория", html)
        self.assertIn("26 мая 1995", html)
        self.assertIn("19:25", html)
        self.assertIn("Гдыня", html)
        self.assertIn("Твоя карта", html)
        self.assertIn("Аспекты", html)
        self.assertIn("Циклы", html)
        self.assertIn("Запрос", html)
        self.assertIn("Практика", html)
        self.assertIn("Положения", html)
        self.assertIn("Где это может проявляться", html)
        self.assertIn("<svg ", html)
        self.assertIn("cover.webp", html)
        self.assertIn("chapter.webp", html)
        self.assertIn("eye.png", html)
        self.assertNotIn("assets/wheel.png", html)

    def test_payload_puts_name_on_person_for_cover(self):
        natal = calculate_natal(**GDYNIA)
        document = build_report_document(natal=natal, sky_now={}, quiz={"name": "Виктория"})
        payload = build_pdf_render_payload(
            {
                "title": "Персональный астрологический отчёт",
                "person": {"birth_date": "1995-05-26"},
                "document": document,
            }
        )
        self.assertEqual(payload["person"]["name"], "Виктория")


class NatalWheelSvgTests(TestCase):
    def test_svg_matches_wheel_json_and_is_transparent(self):
        natal = calculate_natal(**GDYNIA)
        wheel = chart_wheel(natal, natal_aspects(natal))
        svg = render_natal_wheel_svg(wheel)
        self.assertTrue(svg.startswith("<svg "))
        self.assertIn('style="background:transparent"', svg)
        self.assertIn("viewBox=\"0 0 500 500\"", svg)
        self.assertIn("☉", svg)
        self.assertIn("ASC", svg)
        self.assertIn("MC", svg)
        self.assertNotIn('fill="#050d4a"', svg)
        self.assertGreater(svg.count("<line"), 50)
