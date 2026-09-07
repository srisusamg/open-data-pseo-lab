import copy
import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from platform.core.configuration import SitePaths
from platform.core.quality import evaluate_page_quality
from platform.providers.ai_models.curated import load_catalog, validate_catalog
from platform.providers.ai_models.normalizer import normalize_catalog, normalize_price
from platform.recipes.model_economics import (
    benchmark_data_is_compatible, blended_workload_cost, comparable_performance, complete_dated_provenance,
    enrich_models, model_insights, model_path, order_releases,
    pricing_is_fresh, provider_path, ranking_path, relative_price_difference, release_path,
)
from scripts.validate_ai_model_economics import validate as validate_generated_site

ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "sites" / "ai-model-economics"
BUILD = importlib.import_module("sites.ai-model-economics.build")


class PricingNormalizationTests(unittest.TestCase):
    def test_supported_units_normalize_to_per_million(self):
        self.assertEqual(normalize_price(0.000002, "usd_per_token"), 2.0)
        self.assertEqual(normalize_price(0.002, "usd_per_1k_tokens"), 2.0)
        self.assertEqual(normalize_price(2, "usd_per_1m_tokens"), 2.0)

    def test_normalized_observation_retains_canonical_unit(self):
        catalog = load_catalog(SITE_ROOT / "config" / "catalog.json")
        self.assertTrue(all(item["unit"] == "usd_per_1m_tokens" for item in normalize_catalog(catalog)["pricing_observations"]))

    def test_incompatible_unit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incompatible pricing unit"):
            normalize_price(2, "credits_per_token")

    def test_blended_workload_is_reproducible(self):
        pricing = {"input_price_per_million_tokens": 2.0, "output_price_per_million_tokens": 12.0}
        workload = {"input_tokens": 800_000, "output_tokens": 200_000, "formula_version": "v1"}
        self.assertEqual(blended_workload_cost(pricing, workload)["value"], 4.0)
        self.assertEqual(blended_workload_cost(pricing, workload), blended_workload_cost(pricing, workload))

    def test_missing_pricing_stays_missing(self):
        self.assertIsNone(blended_workload_cost(None, {"input_tokens": 1, "output_tokens": 1, "formula_version": "v1"}))


class ModelEconomicsRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(SITE_ROOT / "config" / "catalog.json")
        cls.config = json.loads((SITE_ROOT / "config" / "site.json").read_text(encoding="utf-8"))
        cls.dataset = normalize_catalog(cls.catalog)
        cls.models = enrich_models(cls.dataset, cls.config)
        cls.by_id = {item["id"]: item for item in cls.models}
        cls.benchmarks = {item["id"]: item for item in cls.dataset["benchmarks"]}

    def test_relative_price_difference_uses_second_model_as_baseline(self):
        self.assertEqual(relative_price_difference(3, 2), 50.0)
        self.assertEqual(relative_price_difference(1, 2), -50.0)
        self.assertIsNone(relative_price_difference(1, 0))

    def test_comparable_performance_requires_same_harness_metadata(self):
        pairs = comparable_performance("openai:gpt-5.6-sol", "openai:gpt-5.6-terra", self.dataset["performance_observations"])
        self.assertEqual([pair[0]["benchmark_id"] for pair in pairs], ["aa-intelligence-index-v4.1", "agents-last-exam-v1"])
        self.assertEqual(comparable_performance("openai:gpt-5.6-sol", "anthropic:claude-fable-5", self.dataset["performance_observations"]), [])
        incompatible = copy.deepcopy(self.dataset["performance_observations"])
        terra = next(item for item in incompatible if item["model_id"] == "openai:gpt-5.6-terra")
        terra["evaluation_configuration"] = "different harness"
        self.assertEqual(len(comparable_performance("openai:gpt-5.6-sol", "openai:gpt-5.6-terra", incompatible)), 1)

    def test_comparison_rejects_stale_prices_and_incomparable_benchmark_sets(self):
        pricing = copy.deepcopy(self.by_id["openai:gpt-5.6-sol"]["pricing"])
        self.assertTrue(pricing_is_fresh(pricing, "2026-09-07", 120))
        pricing["provenance"]["observation_date"] = "2025-01-01"
        self.assertFalse(pricing_is_fresh(pricing, "2026-09-07", 120))
        incompatible = copy.deepcopy(self.dataset["performance_observations"])
        for item in incompatible:
            if item["model_id"] == "openai:gpt-5.6-terra":
                item["comparison_group"] = "different-group"
        self.assertFalse(benchmark_data_is_compatible("openai:gpt-5.6-sol", "openai:gpt-5.6-terra", incompatible))
        self.assertTrue(benchmark_data_is_compatible("openai:gpt-5.6-sol", "anthropic:claude-fable-5", incompatible))

    def test_rankings_are_deterministic_and_missing_prices_are_excluded(self):
        first = BUILD._ranking("input-cost", self.models)
        second = BUILD._ranking("input-cost", self.models)
        self.assertEqual([row["model"]["id"] for row in first], [row["model"]["id"] for row in second])
        self.assertEqual([row["value"] for row in first], sorted(row["value"] for row in first))
        missing = copy.deepcopy(self.models)
        missing[0]["pricing"] = None
        self.assertNotIn(missing[0]["id"], {row["model"]["id"] for row in BUILD._ranking("input-cost", missing)})

    def test_release_ordering_is_latest_first_with_stable_ties(self):
        ordered = order_releases(self.models, 2026)
        self.assertEqual([item["release_date"] for item in ordered], sorted((item["release_date"] for item in ordered), reverse=True))
        self.assertEqual(ordered[0]["id"], "google:gemini-3.8-flash")

    def test_model_insights_are_deterministic(self):
        model = self.by_id["openai:gpt-5.6-sol"]
        first = model_insights(model, self.models, self.benchmarks, self.config["as_of_date"])
        second = model_insights(model, self.models, self.benchmarks, self.config["as_of_date"])
        self.assertEqual(first, second)
        self.assertIn("configured blended workload cost", first["summary"])
        self.assertTrue(all(item["evidence"] for item in first["selected"]))

    def test_url_generation_matches_required_recipes(self):
        self.assertEqual(model_path({"slug": "model-a"}), "models/model-a/")
        self.assertEqual(provider_path({"slug": "provider-a"}), "providers/provider-a/")
        self.assertEqual(ranking_path("input-cost"), "models/rankings/input-cost/")
        self.assertEqual(release_path(2026), "models/releases/2026/")


class QualityAndProvenanceTests(unittest.TestCase):
    def test_missing_pricing_fails_model_page_gate(self):
        context = {
            "url": "models/test/", "page_type": "model_profile", "as_of_year": 2026,
            "usable_facts": 4, "usable_historical_metrics": 0, "insight_candidate_count": 2,
            "selected_insight_count": 2, "source_years": [2026], "provenance_complete": False,
            "differentiated_content_count": 4, "duplicate_intent": False,
            "required_internal_links": ["providers/test/", "methodology/"],
            "available_internal_links": {"providers/test/", "methodology/"},
            "canonical_url": "https://example.test/models/test/", "expected_canonical_url": "https://example.test/models/test/",
            "unsupported_calculations": 0, "policy_overrides": {"minimum_usable_facts": 6},
        }
        result = evaluate_page_quality(context)
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(any("usable facts" in reason for reason in result["reasons"]))
        self.assertTrue(any("provenance" in reason for reason in result["reasons"]))

    def test_every_seed_record_has_complete_dated_provenance(self):
        dataset = normalize_catalog(load_catalog(SITE_ROOT / "config" / "catalog.json"))
        for collection in ("providers", "models", "benchmarks", "pricing_observations", "performance_observations"):
            with self.subTest(collection=collection):
                self.assertTrue(all(complete_dated_provenance(item) for item in dataset[collection]))

    def test_catalog_rejects_missing_provenance_field(self):
        catalog = copy.deepcopy(load_catalog(SITE_ROOT / "config" / "catalog.json"))
        del catalog["pricing_observations"][0]["provenance"]["retrieved_at"]
        self.assertTrue(any("pricing observation 1" in error for error in validate_catalog(catalog)))


class GeneratedSiteTests(unittest.TestCase):
    def test_build_sitemap_and_site_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site_definition = root / "site-definition"
            shutil.copytree(SITE_ROOT, site_definition)
            paths = SitePaths(site_definition, root / "site", root / "generated")
            page_count = BUILD.render_site(paths)
            urls = json.loads((paths.generated_data / "generated_urls.json").read_text(encoding="utf-8"))
            sitemap = (paths.output / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(page_count, len(urls))
            self.assertEqual(page_count, len(list(paths.output.rglob("index.html"))))
            self.assertTrue(all(f"<loc>{url}</loc>" in sitemap for url in urls))
            self.assertEqual(validate_generated_site(paths), [])


if __name__ == "__main__":
    unittest.main()
