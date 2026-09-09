from __future__ import annotations

import copy
import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from platform.core.configuration import SitePaths
from platform.providers.ai_models.curated import load_catalog
from platform.providers.ai_models.hybrid import (
    apply_canonical, automated_facts, build_reports, freshness_status,
    load_field_registry, load_freshness_policy, merge_facts, validate_curated_rows,
)
from platform.providers.ai_models.normalizer import normalize_catalog
from platform.recipes.model_economics import enrich_models

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "sites" / "ai-model-economics"


class HybridDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_field_registry(SITE / "config" / "field_registry.json")
        cls.policy = load_freshness_policy(SITE / "config" / "freshness_policy.json")
        cls.catalog = load_catalog(SITE / "config" / "catalog.json")
        cls.dataset = normalize_catalog(cls.catalog)
        cls.model_ids = {item["id"] for item in cls.dataset["models"]}

    def curated(self, **changes):
        row = {"model_id": "openai:gpt-5.6-sol", "field_id": "context_window_tokens", "value": "2000000", "unit": "tokens", "source_name": "Example source", "source_url": "https://example.test/source", "observed_at": "2026-09-01", "curated_at": "2026-09-07", "confidence": "high", "status": "verified", "notes": "fixture", "lock_mode": "PREFERRED"}
        row.update(changes)
        return row

    def test_automated_store_has_values_and_omits_missing_values(self):
        facts = automated_facts(self.dataset, self.registry)
        self.assertTrue(any(item["field_id"] == "input_price_per_1m" for item in facts))
        self.assertFalse(any(item["value"] is None for item in facts))
        self.assertTrue(all(item["source_type"] == "automated" for item in facts))

    def test_fresh_aging_and_stale_classification(self):
        field = next(item for item in self.registry if item["field_id"] == "input_price_per_1m")
        self.assertEqual(freshness_status({"observed_at": "2026-09-01"}, field, self.policy, "2026-09-07"), "FRESH")
        self.assertEqual(freshness_status({"observed_at": "2026-05-20"}, field, self.policy, "2026-09-07"), "AGING")
        self.assertEqual(freshness_status({"observed_at": "2026-01-01"}, field, self.policy, "2026-09-07"), "STALE")

    def test_curated_validation_rejects_missing_source_invalid_value_and_duplicates(self):
        missing = self.curated(source_url="")
        invalid = self.curated(field_id="input_price_per_1m", value="not-a-number")
        errors = validate_curated_rows([missing, invalid, copy.deepcopy(invalid)], self.registry, self.model_ids)
        self.assertTrue(any("requires source_url" in item for item in errors))
        self.assertTrue(any("invalid value" in item for item in errors))
        self.assertTrue(any("duplicate fact" in item for item in errors))

    def test_human_preferred_conflict_retains_provenance(self):
        automated = [{"model_id": "openai:gpt-5.6-sol", "field_id": "context_window_tokens", "value": 1000000, "unit": "tokens", "source_type": "automated", "source_name": "Provider", "source_url": "https://example.test/provider", "observed_at": "2026-09-02", "retrieved_at": "2026-09-07", "confidence": "high", "status": "verified"}]
        human = [{**self.curated(), "value": 2000000, "source_type": "human_curated", "lock_mode": "PREFERRED"}]
        canonical, conflicts = merge_facts(automated, human, self.registry, self.policy, "2026-09-07")
        selected = canonical["openai:gpt-5.6-sol"]["context_window_tokens"]
        self.assertEqual(selected["value"], 2000000)
        self.assertEqual(selected["selected_source_type"], "human_curated")
        self.assertEqual(selected["source_url"], "https://example.test/source")
        self.assertEqual(conflicts[0]["difference"], 1000000.0)

    def test_stale_human_yields_to_automation_but_locked_human_does_not(self):
        auto = [{"model_id": "openai:gpt-5.6-sol", "field_id": "input_price_per_1m", "value": 4.0, "unit": "USD_per_1M_tokens", "source_type": "automated", "source_name": "Provider", "source_url": "https://example.test/provider", "observed_at": "2026-09-02", "retrieved_at": "2026-09-07", "confidence": "high", "status": "verified"}]
        human = [{**self.curated(field_id="input_price_per_1m", value="5", observed_at="2026-01-01"), "value": 5.0, "source_type": "human_curated", "lock_mode": "PREFERRED"}]
        canonical, _ = merge_facts(auto, human, self.registry, self.policy, "2026-09-07")
        self.assertEqual(canonical["openai:gpt-5.6-sol"]["input_price_per_1m"]["value"], 4.0)
        human[0]["lock_mode"] = "LOCKED"
        canonical, conflicts = merge_facts(auto, human, self.registry, self.policy, "2026-09-07")
        self.assertEqual(canonical["openai:gpt-5.6-sol"]["input_price_per_1m"]["value"], 5.0)
        self.assertEqual(conflicts[0]["reason"], "human_locked")

    def test_fixture_model_a_curated_gap_increases_coverage(self):
        automated = automated_facts(self.dataset, self.registry)
        target = "anthropic:claude-opus-5"
        automated = [item for item in automated if not (item["model_id"] == target and item["field_id"] == "reasoning_score")]
        before, _ = merge_facts(automated, [], self.registry, self.policy, "2026-09-07")
        before_rows = build_reports(self.dataset, before, [], self.registry, "2026-09-07")["coverage"]
        human = [{**self.curated(model_id=target, field_id="reasoning_score", value="44.2"), "value": 44.2, "unit": "percent", "source_type": "human_curated", "lock_mode": "PREFERRED"}]
        after, _ = merge_facts(automated, human, self.registry, self.policy, "2026-09-07")
        after_rows = build_reports(self.dataset, after, [], self.registry, "2026-09-07")["coverage"]
        before_row = next(item for item in before_rows if item["model_id"] == target)
        after_row = next(item for item in after_rows if item["model_id"] == target)
        self.assertEqual(after_row["fields_populated"], before_row["fields_populated"] + 1)
        self.assertEqual(after[target]["reasoning_score"]["source_name"], "Example source")

    def test_fixture_model_b_locked_conflict_is_applied_and_reported(self):
        human = [{**self.curated(lock_mode="LOCKED"), "value": 2000000, "source_type": "human_curated", "lock_mode": "LOCKED"}]
        canonical, conflicts = merge_facts(automated_facts(self.dataset, self.registry), human, self.registry, self.policy, "2026-09-07")
        merged = apply_canonical(self.dataset, canonical, self.registry)
        model = next(item for item in merged["models"] if item["id"] == "openai:gpt-5.6-sol")
        self.assertEqual(model["context_window_tokens"], 2000000)
        self.assertTrue(any(item["field_id"] == "context_window_tokens" for item in conflicts))

    def test_curated_benchmark_can_fill_ranking_input(self):
        target = "anthropic:claude-opus-5"
        human = [{**self.curated(model_id=target, field_id="intelligence_score", value="50"), "value": 50.0, "unit": "index_score", "source_type": "human_curated", "lock_mode": "PREFERRED"}]
        canonical, _ = merge_facts(automated_facts(self.dataset, self.registry), human, self.registry, self.policy, "2026-09-07")
        merged = apply_canonical(self.dataset, canonical, self.registry)
        config = json.loads((SITE / "config" / "site.json").read_text(encoding="utf-8"))
        model = next(item for item in enrich_models(merged, config) if item["id"] == target)
        self.assertIn("aa-intelligence-index-v4.1", model["ranking_eligibility"]["benchmarks"])

    def test_generated_model_page_shows_field_source_and_freshness(self):
        build = importlib.import_module("sites.ai-model-economics.build")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site_copy = root / "sites" / "ai-model-economics"
            shutil.copytree(SITE, site_copy)
            (root / "data" / "curated").mkdir(parents=True)
            header = "model_id,field_id,value,unit,source_name,source_url,observed_at,curated_at,confidence,status,notes,lock_mode\n"
            (root / "data" / "curated" / "model_facts.csv").write_text(header, encoding="utf-8")
            paths = SitePaths(site_copy, root / "site", root / "generated")
            build.render_site(paths)
            html = (paths.output / "models" / "gpt-5-6-sol" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Sources &amp; data freshness", html)
            self.assertIn("OpenAI model documentation", html)
            self.assertIn("FRESH", html)


if __name__ == "__main__":
    unittest.main()
