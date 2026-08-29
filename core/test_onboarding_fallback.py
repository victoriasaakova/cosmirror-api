"""Deterministic onboarding insight fallback."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from core.services.onboarding_fallback import (
    build_onboarding_fallback,
    load_onboarding_fallback_library,
    load_onboarding_semantics,
    normalize_onboarding,
    score_themes,
    select_variant,
)


def _insight_with(*keys: str) -> dict:
    return {
        "influences": [{"key": key, "title": key, "text": "x"} for key in keys],
        "cycles": [],
        "disclaimer": "",
    }


class OnboardingFallbackLibraryTests(SimpleTestCase):
    def test_library_has_nine_themes_and_defaults(self):
        library = load_onboarding_fallback_library()
        themes = library["themes"]
        self.assertEqual(len(themes), 9)
        variants = 0
        for theme in themes.values():
            self.assertIn("default", theme["variants"])
            tags = theme["variants"]["default"]["tags"]
            self.assertEqual(tags["focuses"], [])
            self.assertEqual(tags["desired_outcomes"], [])
            self.assertEqual(tags["life_context"], [])
            self.assertEqual(tags["triggers"], [])
            variants += len(theme["variants"])
            for variant in theme["variants"].values():
                self.assertNotIn("bridge_key", variant)
        self.assertEqual(variants, 27)
        self.assertIn("opening", library["global_fallback"])
        self.assertNotIn("canonical_bridges", library)
        self.assertNotIn("bridge_key", library["global_fallback"])


class OnboardingFallbackScoringTests(SimpleTestCase):
    def test_fixture_primary_saturn_moon_wins(self):
        result = score_themes(
            [
                {"key": "saturn_on_moon"},
                {"key": "jupiter_on_moon"},
                {"key": "pluto_on_ascendant"},
            ]
        )
        self.assertEqual(result["theme_id"], "responsibility_vs_capacity")
        self.assertAlmostEqual(result["scores"]["responsibility_vs_capacity"], 100.0)
        self.assertAlmostEqual(result["scores"]["direction_vs_inertia"], 65.0)
        self.assertAlmostEqual(result["scores"]["stability_vs_change"], 40.0)

    def test_two_secondary_signals_can_outrank_primary(self):
        result = score_themes(
            [
                {"key": "jupiter_on_sun"},
                {"key": "uranus_on_moon"},
                {"key": "pluto_on_mars"},
            ]
        )
        # jupiter direction 100, uranus+pluto both map stability 100
        # 100*1 + 0 vs 100*0.65 + 100*0.40 = 105
        self.assertEqual(result["theme_id"], "stability_vs_change")
        self.assertAlmostEqual(result["scores"]["stability_vs_change"], 105.0)
        self.assertAlmostEqual(result["scores"]["direction_vs_inertia"], 100.0)

    def test_empty_influences_use_global_fallback(self):
        payload = build_onboarding_fallback(
            insight=_insight_with(),
            natal={},
            quiz={},
        )
        self.assertEqual(payload["source"], "templates")
        self.assertEqual(payload["fallback_variant"], "global_fallback")
        self.assertEqual(
            payload["opening"]["insight"],
            "сейчас карта полезнее как точный вопрос, а не как готовый ответ",
        )
        self.assertEqual(payload["opening"]["bridge"], "")
        self.assertTrue(payload["body"])

    def test_curiosity_does_not_select_variant(self):
        context_curious = normalize_onboarding(
            {"astrology_trigger": "curious", "focus": ["love"]}
        )
        self.assertIn("curiosity", context_curious["triggers"])
        chosen = select_variant("autonomy_vs_closeness", context_curious)
        self.assertEqual(chosen["variant_id"], "relationships")

        context_plain = normalize_onboarding({"focus": ["love"]})
        same = select_variant("autonomy_vs_closeness", context_plain)
        self.assertEqual(same["variant_id"], chosen["variant_id"])

    def test_unknown_enum_does_not_crash(self):
        context = normalize_onboarding(
            {"focus": ["brand-new-focus"], "intent": "not-a-real-intent"}
        )
        self.assertEqual(context["focuses"], [])
        self.assertEqual(context["desired_outcomes"], [])

    def test_gender_override_does_not_change_theme(self):
        insight = _insight_with("saturn_on_moon", "jupiter_on_moon", "pluto_on_ascendant")
        quiz = {"gender": "female", "focus": ["energy"]}
        female = build_onboarding_fallback(insight=insight, natal={}, quiz=quiz)
        male = build_onboarding_fallback(
            insight=insight, natal={}, quiz={**quiz, "gender": "male"}
        )
        self.assertEqual(female["fallback_theme"], male["fallback_theme"])
        self.assertEqual(female["fallback_variant"], male["fallback_variant"])
        self.assertEqual(female["fallback_theme"], "responsibility_vs_capacity")
        self.assertEqual(female["opening"]["bridge"], "")
        self.assertEqual(male["opening"]["bridge"], "")

    def test_opening_is_api_object_without_bridge_copy(self):
        payload = build_onboarding_fallback(
            insight=_insight_with("saturn_on_moon"),
            natal={},
            quiz={"focus": ["energy"]},
        )
        self.assertEqual(payload["opening"]["bridge"], "")
        self.assertTrue(payload["opening"]["insight"])
        self.assertNotIn("bridge_key", payload["opening"])
        self.assertNotIn("canonical_bridges", load_onboarding_fallback_library())

    def test_relationships_opening_is_self_contained(self):
        payload = build_onboarding_fallback(
            insight=_insight_with("uranus_on_moon", "pluto_on_mars"),
            natal={},
            quiz={"focus": ["love"]},
        )
        self.assertEqual(payload["fallback_theme"], "stability_vs_change")
        self.assertEqual(payload["fallback_variant"], "relationships")
        self.assertEqual(
            payload["opening"]["insight"],
            "сейчас в близости может проявляться не чувство, а форма связи",
        )
        self.assertEqual(payload["opening"]["bridge"], "")

    def test_work_path_opening_is_self_contained(self):
        payload = build_onboarding_fallback(
            insight=_insight_with("uranus_on_moon", "pluto_on_mars"),
            natal={},
            quiz={"focus": ["path"]},
        )
        self.assertEqual(payload["fallback_theme"], "stability_vs_change")
        self.assertEqual(payload["fallback_variant"], "work_path")
        self.assertEqual(
            payload["opening"]["insight"],
            "сейчас надёжный маршрут может уже не вести туда, куда тебе нужно",
        )
        self.assertEqual(payload["opening"]["bridge"], "")

    def test_all_focuses_preserved(self):
        context = normalize_onboarding({"focus": ["love", "path", "money"]})
        self.assertEqual(
            context["focuses"],
            ["relationships", "self_realization", "work_path", "money"],
        )


class OnboardingFallbackPersonalizeTests(SimpleTestCase):
    @override_settings(LLM_PROVIDER="off", POLZA_API_KEY="", GROQ_API_KEY="")
    def test_personalize_uses_library_not_sentence_lego(self):
        from core.services.personalize import personalize_insight

        result = personalize_insight(
            insight=_insight_with("saturn_on_moon", "jupiter_on_moon", "pluto_on_ascendant"),
            natal={"planets": {}, "has_birth_time": True},
            quiz={"focus": ["energy"], "gender": "female"},
        )
        self.assertEqual(result["source"], "templates")
        self.assertNotIn("Чтобы ", result["body"])
        self.assertNotIn("тема «", result["body"])
        self.assertEqual(result["fallback_theme"], "responsibility_vs_capacity")
