import platform as python_platform
import unittest
from pathlib import Path

from scripts.build import DEFAULT_PATHS
from platform.core.derivations import calculate_derived_metrics
from platform.core.facts import series_value
from platform.providers.world_bank.normalizer import normalize_snapshot
from platform.recipes.change import derive_change_metric
from platform.recipes.comparison import build_comparison


ROOT = Path(__file__).resolve().parents[1]


def source_series(entity_id: str, metric_id: str, values: list[tuple[int, float]]) -> dict:
    observations = [{"year": year, "value": value} for year, value in values]
    return {
        "country_code": entity_id, "indicator_code": metric_id,
        "source_url": f"https://source.test/{entity_id}/{metric_id}",
        "observations": observations, "latest_observation": observations[0] if observations else None,
        "derived_metrics": calculate_derived_metrics(observations),
    }


class BoundaryTests(unittest.TestCase):
    entities = [
        {"code": "AAA", "slug": "alpha", "name": "Alpha"},
        {"code": "BBB", "slug": "beta", "name": "Beta"},
    ]
    metrics = [
        {"code": "METRIC.X", "slug": "metric-x", "name": "Metric X", "unit": "units", "format": "population"},
    ]

    def dataset(self):
        snapshot = {
            "source": {"name": "Fixture Source", "api": "Fixture API"},
            "retrieved_at": "2026-01-01T00:00:00Z",
            "series": [
                source_series("AAA", "METRIC.X", [(2025, 200), (2020, 150), (2015, 100)]),
                source_series("BBB", "METRIC.X", [(2025, 150), (2020, 125), (2015, 100)]),
            ],
        }
        return normalize_snapshot(snapshot, self.entities, self.metrics)

    def test_provider_normalizer_is_the_only_world_bank_shape_boundary(self):
        dataset = self.dataset()
        flattened = series_value(dataset["series"][0])
        self.assertEqual(flattened["entity_id"], "AAA")
        self.assertEqual(flattened["metric_id"], "METRIC.X")
        self.assertNotIn("country_code", flattened)
        self.assertNotIn("indicator_code", flattened)
        self.assertEqual(flattened["provenance"]["source_name"], "Fixture Source")

    def test_comparison_recipe_consumes_canonical_series(self):
        dataset = self.dataset()
        series = [series_value(item) for item in dataset["series"]]
        result = build_comparison(dataset["entities"][0], dataset["entities"][1], series[:1], series[1:])
        self.assertEqual(result["entity_a"]["id"], "AAA")
        self.assertEqual(result["metrics"][0]["metric_id"], "METRIC.X")
        self.assertNotIn("country_a", result)
        self.assertNotIn("indicator_code", result["metrics"][0])

    def test_change_recipe_retains_canonical_provenance(self):
        series = series_value(self.dataset()["series"][0])
        result = derive_change_metric(series, 2015, 2025, tolerance_years=0, minimum_span_years=10)
        self.assertEqual(result["source_facts"][0]["provenance"]["source_name"], "Fixture Source")
        self.assertNotIn("source", result["source_facts"][0])

    def test_recipes_do_not_import_world_bank_provider(self):
        for path in (ROOT / "platform" / "recipes").glob("*.py"):
            with self.subTest(path=path.name):
                self.assertNotIn("platform.providers.world_bank", path.read_text(encoding="utf-8"))

    def test_site_assets_are_with_the_site_definition(self):
        self.assertTrue((DEFAULT_PATHS.config / "site.json").is_file())
        self.assertTrue((DEFAULT_PATHS.templates / "home.html").is_file())
        self.assertTrue((DEFAULT_PATHS.static / "styles.css").is_file())

    def test_package_keeps_standard_platform_api_available(self):
        self.assertIsInstance(python_platform.system(), str)


if __name__ == "__main__":
    unittest.main()
