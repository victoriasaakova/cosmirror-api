"""Выбор первого инсайта: тема, статус и натальные якоря. Deep Dive и Scoring не проверяются."""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from core.services.compatibility.insight import build_insight_slot, relevant_anchors
from core.services.compatibility.insight_select import rank_openings, select_opening
from core.services.compatibility.writers import _validate_insight, insight_facts


def _cross(aspect_id, point_a, point_b, aspect, orb, allowed, *, quality=None):
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
        "direction": "A_to_B",
    }


def _document(aspects, *, relationship="romantic", status="together", names=("Алина", "Марк")):
    return {
        "relationship_type": relationship,
        "relationship_context": {"type": relationship, "status": status},
        "persons": [
            {"id": "A", "display_name": names[0], "birth_time_status": "known"},
            {"id": "B", "display_name": names[1], "birth_time_status": "known"},
        ],
        "chart": {"cross_aspects": aspects},
    }


class InsightSelectionTests(SimpleTestCase):
    def test_venus_mars_is_a_candidate_and_not_forced_to_win(self):
        document = _document(
            [
                _cross("jupiter-mars", "jupiter", "mars", "conjunction", 0.04, 5),
                _cross("jupiter-sun", "jupiter", "sun", "conjunction", 1.51, 5),
                _cross("moon-jupiter", "moon", "jupiter", "trine", 2.11, 4),
                _cross("venus-mars", "venus", "mars", "opposition", 1.06, 5),
                _cross("mars-mercury", "mars", "mercury", "trine", 0.34, 4),
            ]
        )
        ranked = rank_openings(document)
        themes = [row["theme_id"] for row in ranked[:3]]
        self.assertEqual(themes[0], "mutual_inspiration")
        self.assertIn("desire_and_pace", themes)
        self.assertIn("initiative_and_friction", themes)
        winner = ranked[0]
        self.assertEqual(winner["polarity"], "mixed")
        self.assertGreater(winner["astro_score"], ranked[1]["astro_score"])
        self.assertEqual(len(winner["aspects"]), 3)
        self.assertEqual(select_opening(document)["theme_id"], "mutual_inspiration")
        self.assertEqual([row["theme_id"] for row in rank_openings(document)[:3]], themes)

    def test_status_changes_a_close_pair_without_hardcoding_venus_mars(self):
        aspects = [
            _cross("mars-mercury", "mars", "mercury", "trine", 0.34, 4),
            _cross("venus-mars", "venus", "mars", "opposition", 1.06, 5),
        ]
        together = select_opening(_document(aspects, status="together"))
        crush = select_opening(_document(aspects, status="crush"))
        self.assertEqual(together["theme_id"], "initiative_and_friction")
        self.assertEqual(crush["theme_id"], "desire_and_pace")
        self.assertGreater(together["status_match"], 0)
        self.assertGreater(crush["status_match"], 0)

    def test_uncertain_can_prefer_boundaries_over_a_tighter_step(self):
        aspects = [
            _cross("mars-mercury", "mars", "mercury", "trine", 0.8, 4),
            _cross("venus-saturn", "venus", "saturn", "square", 0.4, 4),
        ]
        together = select_opening(_document(aspects, status="together"))
        uncertain = select_opening(_document(aspects, status="uncertain"))
        self.assertEqual(together["theme_id"], "initiative_and_friction")
        self.assertEqual(uncertain["theme_id"], "closeness_and_boundaries")

    def test_friendship_prefers_shared_language_over_venus_mars(self):
        document = _document(
            [
                _cross("mercury", "mercury", "mercury", "trine", 0.8, 4),
                _cross("venus-mars", "venus", "mars", "opposition", 1.0, 5),
            ],
            relationship="friendship",
            status="close",
        )
        opening = select_opening(document)
        self.assertEqual(opening["theme_id"], "shared_language")
        slot = build_insight_slot(document)
        self.assertNotIn("сексу", slot["body"].casefold())

    def test_family_venus_mars_is_not_a_romantic_plot(self):
        document = _document(
            [_cross("venus-mars", "venus", "mars", "opposition", 1.0, 5)],
            relationship="family",
            status="strained",
        )
        slot = build_insight_slot(document)
        self.assertEqual(slot["theme_id"], "initiative_and_friction")
        lowered = slot["body"].casefold()
        self.assertNotIn("сексу", lowered)
        self.assertNotIn("поцел", lowered)
        self.assertNotIn("влюб", lowered)

    def test_family_responsibility_can_outrank_venus_mars(self):
        document = _document(
            [
                _cross("saturn-sun", "saturn", "sun", "trine", 0.5, 4),
                _cross("venus-mars", "venus", "mars", "opposition", 1.0, 5),
            ],
            relationship="family",
            status="active",
        )
        self.assertEqual(select_opening(document)["theme_id"], "responsibility_and_recognition")

    def test_ended_copy_does_not_explain_the_breakup(self):
        document = _document(
            [_cross("venus-uranus", "venus", "uranus", "opposition", 1.2, 5)],
            status="ended",
        )
        slot = build_insight_slot(document)
        self.assertEqual(slot["theme_id"], "attraction_and_freedom")
        self.assertIn("не объясняет", slot["body"].casefold())
        self.assertNotIn("верн", slot["body"].casefold())

    def test_node_twins_count_once(self):
        document = _document(
            [
                _cross("north", "north_node", "venus", "sextile", 0.1, 3),
                _cross("south", "south_node", "venus", "trine", 0.1, 3),
            ]
        )
        opening = select_opening(document)
        self.assertEqual(opening["theme_id"], "closeness_and_boundaries")
        self.assertEqual(len(opening["aspects"]), 1)
        self.assertAlmostEqual(opening["astro_score"], opening["aspects"] and rank_openings(document)[0]["astro_score"])
        self.assertEqual(len(rank_openings(document)[0]["aspects"]), 1)

    def test_anchors_follow_the_people_in_the_chosen_theme(self):
        document = _document([_cross("mars-mercury", "mars", "mercury", "trine", 0.3, 4)])
        document["natal_anchors"] = {
            "A": [
                {"id": "a-mars-pluto", "a": "mars", "b": "pluto", "aspect": "trine", "orb": 0.6},
                {"id": "a-venus-jupiter", "a": "venus", "b": "jupiter", "aspect": "opposition", "orb": 1.1},
            ],
            "B": [
                {"id": "b-mercury-saturn", "a": "mercury", "b": "saturn", "aspect": "sextile", "orb": 2.3},
                {"id": "b-sun-mars", "a": "sun", "b": "mars", "aspect": "conjunction", "orb": 1.5},
            ],
        }
        slot = build_insight_slot(document)
        document["insight"] = slot
        facts = insight_facts(document)
        self.assertEqual([row["id"] for row in facts["natal_anchors"]["A"]], ["a-mars-pluto"])
        self.assertEqual([row["id"] for row in facts["natal_anchors"]["B"]], ["b-mercury-saturn"])
        self.assertNotIn("Марс", facts["natal_anchors"]["A"][0]["quality_hint_ru"])
        self.assertIn("angle_ru", facts["selection"])
        raw = json.dumps(facts, ensure_ascii=False)
        self.assertNotIn("birth_date", raw)
        self.assertEqual(relevant_anchors({"natal_anchors": {}}, slot and []) , {"A": [], "B": []})

    def test_planet_glossary_is_rejected_and_a_name_is_kept(self):
        slot = {"temporal_frame": "base"}
        glossary = {
            "headline": "Когда импульс встречает точный ответ",
            "body": "Марс даёт инициативе ход, а Меркурий помогает этому ходу становиться понятным делом в разговоре. Так контакт быстро переходит от замысла к шагам и оставляет один общий ритм.",
        }
        self.assertIsNone(_validate_insight(glossary, slot))
        kept = {
            "headline": "Согласие о шаге может опережать согласие о смысле",
            "body": "Алина и Марк могут перевести намерение в движение быстрее, чем станет ясно, зачем оно им. Слаженность шага ещё не значит, что они хотят одного результата. Общий ход здесь легче найти, чем общий смысл этого хода.",
        }
        self.assertIsNotNone(_validate_insight(kept, slot))
