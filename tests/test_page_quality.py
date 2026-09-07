import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build
from scripts.model import ROOT
from scripts.validate import validate_snapshot
from scripts.page_quality import (
    PAGE_POLICIES,
    complete_provenance,
    duplicate_intents,
    evaluate_page_quality,
    quality_report_row,
    valid_canonical_url,
)


def fixed_context(page_type="country_profile"):
    path = "countries/testland/"
    return {
        "url": path,
        "page_type": page_type,
        "as_of_year": 2026,
        "usable_facts": 5,
        "usable_historical_metrics": 5,
        "insight_candidate_count": 5,
        "selected_insight_count": 4,
        "source_years": [2025, 2024, 2025, 2025, 2024],
        "provenance_complete": True,
        "differentiated_content_count": 5,
        "duplicate_intent": False,
        "required_internal_links": ["methodology/", "indicators/gdp/", "countries/testland/"],
        "available_internal_links": {"methodology/", "indicators/gdp/", "countries/testland/"},
        "canonical_url": "https://example.test/atlas/countries/testland/",
        "expected_canonical_url": "https://example.test/atlas/countries/testland/",
        "unsupported_calculations": 0,
    }


class CommonQualityUtilityTests(unittest.TestCase):
    def test_canonical_must_be_exact_https_and_clean(self):
        expected = "https://example.test/atlas/countries/testland/"
        self.assertTrue(valid_canonical_url(expected, expected))
        self.assertFalse(valid_canonical_url(expected + "?draft=1", expected))
        self.assertFalse(valid_canonical_url(expected.replace("https://", "http://"), expected))

    def test_provenance_requires_every_field_on_every_fact(self):
        fields = ("source_url", "indicator_code")
        self.assertTrue(complete_provenance([{"source_url": "https://source.test", "indicator_code": "X"}], fields))
        self.assertFalse(complete_provenance([{"source_url": "https://source.test"}], fields))
        self.assertFalse(complete_provenance([], fields))

    def test_duplicate_intent_detection_is_deterministic(self):
        self.assertEqual(duplicate_intents(["a", "b", "a"]), {"a"})


class PageTypePolicyFixtureTests(unittest.TestCase):
    def test_every_supported_page_type_explicitly_generates_good_fixture(self):
        for page_type in PAGE_POLICIES:
            with self.subTest(page_type=page_type):
                result = evaluate_page_quality(fixed_context(page_type))
                self.assertEqual(result["status"], "generated")
                self.assertEqual(result["reasons"], [])

    def test_country_policy_skips_insufficient_history(self):
        context = fixed_context("country_profile")
        context["usable_historical_metrics"] = 2
        result = evaluate_page_quality(context)
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(any("historical metrics" in reason for reason in result["reasons"]))

    def test_indicator_policy_allows_no_historical_metric_threshold(self):
        context = fixed_context("indicator_ranking")
        context["usable_historical_metrics"] = 0
        self.assertEqual(evaluate_page_quality(context)["status"], "generated")

    def test_comparison_policy_requires_selected_insights(self):
        context = fixed_context("comparison")
        context["selected_insight_count"] = 1
        self.assertEqual(evaluate_page_quality(context)["status"], "skipped")

    def test_change_policy_can_take_page_specific_config_thresholds(self):
        context = fixed_context("what_changed")
        context["usable_facts"] = 4
        context["usable_historical_metrics"] = 4
        context["policy_overrides"] = {"minimum_usable_facts": 5, "minimum_historical_metrics": 5}
        self.assertEqual(evaluate_page_quality(context)["status"], "skipped")

    def test_each_common_gate_can_make_a_page_ineligible(self):
        mutations = {
            "provenance": ("provenance_complete", False),
            "freshness": ("source_years", [2020] * 5),
            "differentiation": ("differentiated_content_count", 1),
            "duplicate": ("duplicate_intent", True),
            "links": ("available_internal_links", {"methodology/"}),
            "canonical": ("canonical_url", "http://example.test/wrong/"),
            "calculation": ("unsupported_calculations", 1),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(gate=label):
                context = fixed_context("comparison")
                context[field] = value
                self.assertEqual(evaluate_page_quality(context)["status"], "skipped")

    def test_report_has_publication_fields_and_detailed_metrics(self):
        context = fixed_context("country_profile")
        result = evaluate_page_quality(context)
        row = quality_report_row(context, result)
        expected = {"url", "page_type", "status", "quality_score", "usable_facts", "usable_historical_metrics", "insight_candidate_count", "selected_insight_count", "source_freshness", "skip_reasons", "metrics"}
        self.assertEqual(set(row), expected)
        self.assertEqual(row["quality_score"], 100)

    def test_result_is_stable_for_same_fixed_fixture(self):
        context = fixed_context("what_changed")
        self.assertEqual(evaluate_page_quality(context), evaluate_page_quality(dict(context)))


class IntentionalSkipPipelineTests(unittest.TestCase):
    def test_short_valid_history_is_left_for_eligibility_not_snapshot_failure(self):
        countries = [{"code": "TST"}]
        indicators = [{"code": "TEST.X"}]
        snapshot = {
            "schema_version": "2.0",
            "series": [{
                "country_code": "TST", "indicator_code": "TEST.X", "observations": [],
                "latest_observation": None,
                "derived_metrics": {"basis": "Exact calendar-year endpoints relative to the latest observation; no interpolation", "five_year": None, "ten_year": None},
            }],
        }
        self.assertEqual(validate_snapshot(snapshot, countries, indicators), [])

    def test_skipped_fixtures_are_not_rendered_linked_or_sitemapped(self):
        country = {"code": "TST", "slug": "testland", "name": "Testland"}
        indicator = {"code": "TEST.X", "slug": "test-indicator", "name": "Test indicator", "unit": "units", "format": "population"}
        snapshot = {
            "schema_version": "2.0",
            "source": {"name": "World Bank"},
            "retrieved_at": "2026-01-01T00:00:00Z",
            "series": [{
                "country_code": "TST", "country_slug": "testland", "country_name": "Testland",
                "indicator_code": "TEST.X", "indicator_slug": "test-indicator", "indicator_name": "Test indicator",
                "unit": "units", "format": "population", "source_url": "https://source.test/TST/TEST.X",
                "latest_observation": None, "observations": [],
                "derived_metrics": {"basis": "Exact calendar-year endpoints relative to the latest observation; no interpolation", "five_year": None, "ten_year": None},
            }],
        }
        change_config = {
            "requested_end_year": 2025, "windows": [5], "observation_tolerance_years": 1,
            "minimum_span_by_window": {"5": 4}, "minimum_usable_metrics": 3,
            "minimum_insight_candidates": 3, "minimum_selected_insights": 3,
            "maximum_selected_insights": 6, "acceleration_minimum_observations": 6,
        }
        site_config = {"base_url": "https://example.test/atlas/", "name": "Fixture Atlas"}
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            shutil.copytree(ROOT / "templates", fixture_root / "templates")
            shutil.copytree(ROOT / "static", fixture_root / "static")
            with patch.object(build, "ROOT", fixture_root), patch.object(build, "load_config", return_value=(site_config, [country], [indicator])), patch.object(build, "load_comparisons", return_value=[]), patch.object(build, "load_json", return_value=change_config):
                self.assertEqual(build.render_site(snapshot), 2)

            skipped_paths = ["countries/testland/", "indicators/test-indicator/", "countries/testland/change/2020-2025/"]
            sitemap = (fixture_root / "site/sitemap.xml").read_text(encoding="utf-8")
            home = (fixture_root / "site/index.html").read_text(encoding="utf-8")
            report = json.loads((fixture_root / "data/generated/page_quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual({row["status"] for row in report}, {"skipped"})
            for path in skipped_paths:
                with self.subTest(path=path):
                    self.assertFalse((fixture_root / "site" / path / "index.html").exists())
                    self.assertNotIn(site_config["base_url"] + path, sitemap)
                    self.assertNotIn(path, home)


if __name__ == "__main__":
    unittest.main()
