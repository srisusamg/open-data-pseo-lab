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
    benchmark_data_is_compatible, benchmark_groups, blended_workload_cost, comparable_performance,
    complete_dated_provenance, enrich_models, frontier_insights, frontier_path, model_insights, model_path,
    normalize_benchmark_score, observation_is_fresh, order_releases, pareto_frontier,
    price_performance_frontier, pricing_is_fresh, provider_path, rank_models, ranking_insights, ranking_path,
    relative_price_difference, release_path, validate_composite_definitions, validate_workload_profiles,
    value_ranking_path,
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

    def test_ranking_and_frontier_summaries_are_deterministic(self):
        rows = rank_models("input-cost", self.models, self.benchmarks, self.config)
        self.assertEqual(ranking_insights("input-cost", rows), ranking_insights("input-cost", rows))
        empty = ranking_insights("speed", [])
        self.assertIn("missing values are not treated as zero", empty["summary"])
        frontier = price_performance_frontier(self.models, self.benchmarks, self.config)
        first = frontier_insights(frontier, "coding")
        self.assertEqual(first, frontier_insights(frontier, "coding"))
        self.assertEqual(first["selected"][0]["type"], "cost_performance_frontier")

    def test_url_generation_matches_required_recipes(self):
        self.assertEqual(model_path({"slug": "model-a"}), "models/model-a/")
        self.assertEqual(provider_path({"slug": "provider-a"}), "providers/provider-a/")
        self.assertEqual(ranking_path("input-cost"), "rankings/input-cost/")
        self.assertEqual(value_ranking_path("coding"), "rankings/value/coding/")
        self.assertEqual(frontier_path(), "rankings/price-performance-frontier/")
        self.assertEqual(release_path(2026), "models/releases/2026/")

    def test_catalog_spans_requested_provider_taxonomy(self):
        provider_ids = {item["id"] for item in self.dataset["providers"]}
        self.assertEqual(len(self.models), 44)
        self.assertTrue({"openai", "anthropic", "google", "xai", "meta", "deepseek", "mistral", "qwen", "cohere", "microsoft", "nvidia", "amazon", "moonshot", "minimax", "zhipu"}.issubset(provider_ids))

    def test_optional_pricing_does_not_block_profile_or_context_ranking(self):
        scout = self.by_id["meta:llama-4-scout"]
        self.assertFalse(scout["pricing_available"])
        self.assertIsNone(scout["pricing"])
        self.assertFalse(scout["ranking_eligibility"]["input_cost"])
        self.assertTrue(scout["ranking_eligibility"]["context_window"])
        self.assertIn(scout["id"], {row["model"]["id"] for row in BUILD._ranking("context-window", self.models)})
        self.assertNotIn(scout["id"], {row["model"]["id"] for row in BUILD._ranking("input-cost", self.models)})

    def test_open_and_local_model_metadata_is_preserved(self):
        model = self.by_id["qwen:qwen3-30b-a3b"]
        self.assertEqual(model["openness"], "open")
        self.assertTrue(model["weights_available"])
        self.assertIn("local", model["distribution_types"])
        self.assertEqual(model["open_model"]["parameter_count_billions"], 30)
        self.assertEqual(model["open_model"]["active_parameter_count_billions"], 3)
        self.assertEqual(model["license"], "Apache 2.0")

    def test_product_only_model_is_explicit_and_unpriced(self):
        model = self.by_id["openai:chatgpt-4o"]
        self.assertEqual(model["distribution_types"], ["product_only"])
        self.assertTrue(model["product_available"])
        self.assertFalse(model["api_available"])
        self.assertFalse(model["pricing_available"])
        self.assertIsNone(model["pricing"])

    def test_missing_benchmark_data_is_metric_specific(self):
        model = self.by_id["microsoft:phi-4-mini-instruct"]
        self.assertEqual(model["performance"], [])
        self.assertEqual(model["ranking_eligibility"]["benchmarks"], [])
        self.assertTrue(model["ranking_eligibility"]["context_window"])

    def test_benchmark_grouping_keeps_observations_semantically_separate(self):
        grouped = benchmark_groups(self.dataset["benchmarks"])
        self.assertEqual([item["id"] for item in grouped["general_intelligence"]], ["aa-intelligence-index-v4.1"])
        self.assertEqual([item["id"] for item in grouped["reasoning"]], ["agents-last-exam-v1"])
        self.assertEqual([item["id"] for item in grouped["coding"]], ["terminal-bench-2.1"])
        observation = self.dataset["performance_observations"][0]
        self.assertTrue({"benchmark_name", "benchmark_version", "evaluation_date", "source", "evaluator", "metric_direction", "normalization_method"}.issubset(observation))

    def test_explicit_benchmark_normalization_only(self):
        self.assertEqual(normalize_benchmark_score(75, "percent_to_unit_interval"), 0.75)
        self.assertEqual(normalize_benchmark_score(25, "min_max", minimum=0, maximum=100), 0.25)
        self.assertEqual(normalize_benchmark_score(58.9, None), 58.9)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            normalize_benchmark_score(1, "mystery")
        validate_composite_definitions([], set(self.benchmarks))
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            validate_composite_definitions([{"id": "x", "version": "v1", "included_benchmarks": ["agents-last-exam-v1"], "weights": {"agents-last-exam-v1": .5}, "normalization_method": "identity"}], set(self.benchmarks))

    def test_workload_costs_and_value_metrics_are_profile_specific(self):
        model = self.by_id["openai:gpt-5.6-sol"]
        self.assertEqual(set(model["workload_costs"]), {"coding", "chat", "batch"})
        self.assertEqual(model["workload_costs"]["coding"]["value"], 8.8)
        self.assertEqual(model["workload_costs"]["chat"]["value"], 13.6)
        self.assertEqual(model["workload_costs"]["batch"]["value"], 5.6)
        metrics = {item["workload"]: item for item in model["value_metrics"]}
        self.assertEqual(metrics["coding"]["intelligence_per_input_dollar"], 14.725)
        self.assertEqual(metrics["coding"]["intelligence_per_output_dollar"], 2.945)
        self.assertIsNone(metrics["coding"]["speed_adjusted_value"])
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            validate_workload_profiles({"bad": {"input_share": .7, "output_share": .4, "total_tokens": 1, "formula_version": "v1"}})

    def test_metric_eligibility_excludes_missing_and_stale_facts(self):
        unpriced = self.by_id["meta:llama-4-scout"]
        self.assertFalse(unpriced["ranking_eligibility"]["input_cost"])
        self.assertEqual(unpriced["ranking_eligibility"]["value_workloads"], [])
        stale_dataset = copy.deepcopy(self.dataset)
        price = next(item for item in stale_dataset["pricing_observations"] if item["model_id"] == "openai:gpt-5.6-sol")
        price["provenance"]["observation_date"] = "2025-01-01"
        stale_models = enrich_models(stale_dataset, self.config)
        stale = next(item for item in stale_models if item["id"] == "openai:gpt-5.6-sol")
        self.assertFalse(stale["ranking_eligibility"]["input_cost"])
        self.assertFalse(observation_is_fresh(price, self.config["as_of_date"], self.config["maximum_pricing_age_days"]))

    def test_multi_dimensional_ranking_is_deterministic_and_cohort_local(self):
        first = rank_models("intelligence", self.models, self.benchmarks, self.config)
        second = rank_models("intelligence", self.models, self.benchmarks, self.config)
        self.assertEqual(first, second)
        self.assertEqual([row["model"]["id"] for row in first], ["openai:gpt-5.6-sol", "openai:gpt-5.6-terra", "openai:gpt-5.6-luna"])
        self.assertTrue(all(row["cohort"] == first[0]["cohort"] for row in first))
        self.assertEqual(rank_models("coding", self.models, self.benchmarks, self.config), [])

    def test_latency_throughput_and_speed_adjusted_value_require_fresh_observations(self):
        dataset = copy.deepcopy(self.dataset)
        provenance = copy.deepcopy(self.by_id["openai:gpt-5.6-sol"]["pricing"]["provenance"])
        dataset["operational_observations"] = []
        for model_id, throughput, latency in (("openai:gpt-5.6-sol", 100, .4), ("openai:gpt-5.6-terra", 120, .6)):
            dataset["operational_observations"].extend([
                {"model_id": model_id, "metric": "throughput", "value": throughput, "unit": "tokens_per_second", "evaluation_configuration": "same harness", "comparison_group": "synthetic-test-cohort", "provenance": copy.deepcopy(provenance)},
                {"model_id": model_id, "metric": "latency", "value": latency, "unit": "seconds_to_first_token", "evaluation_configuration": "same harness", "comparison_group": "synthetic-test-cohort", "provenance": copy.deepcopy(provenance)},
            ])
        models = enrich_models(dataset, self.config)
        speed = rank_models("speed", models, self.benchmarks, self.config)
        latency = rank_models("latency", models, self.benchmarks, self.config)
        self.assertEqual([row["model"]["id"] for row in speed], ["openai:gpt-5.6-terra", "openai:gpt-5.6-sol"])
        self.assertEqual([row["model"]["id"] for row in latency], ["openai:gpt-5.6-sol", "openai:gpt-5.6-terra"])
        sol = next(item for item in models if item["id"] == "openai:gpt-5.6-sol")
        self.assertTrue(all(item["speed_adjusted_value"] is not None for item in sol["value_metrics"]))

    def test_pareto_frontier_removes_only_dominated_comparable_models(self):
        rows = [
            {"model": {"id": "a", "name": "A"}, "performance": 10, "cost": 5, "cohort": ("same",)},
            {"model": {"id": "b", "name": "B"}, "performance": 12, "cost": 4, "cohort": ("same",)},
            {"model": {"id": "c", "name": "C"}, "performance": 9, "cost": 2, "cohort": ("same",)},
            {"model": {"id": "d", "name": "D"}, "performance": 1, "cost": 99, "cohort": ("other",)},
        ]
        self.assertEqual([row["model"]["id"] for row in pareto_frontier(rows)], ["d", "c", "b"])
        actual = price_performance_frontier(self.models, self.benchmarks, self.config)
        self.assertEqual(actual, price_performance_frontier(self.models, self.benchmarks, self.config))
        self.assertTrue(actual)

    def test_model_status_values_and_validation(self):
        statuses = {item["status"] for item in self.models}
        self.assertIn("active", statuses)
        self.assertIn("legacy", statuses)
        invalid = copy.deepcopy(self.catalog)
        invalid["models"][0]["status"] = "rumored"
        self.assertTrue(any("invalid status" in error for error in validate_catalog(invalid)))

    def test_every_model_slug_has_a_stable_unique_url(self):
        paths = [model_path(model) for model in self.models]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(path.startswith("models/") and path.endswith("/") for path in paths))


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
        for model in dataset["models"]:
            expected = set(model) - {"id", "slug", "provenance", "fact_provenance"}
            self.assertTrue(expected.issubset(model["fact_provenance"]))
            self.assertTrue(all(complete_dated_provenance(value) for value in model["fact_provenance"].values()))

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
