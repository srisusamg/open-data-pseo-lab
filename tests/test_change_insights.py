import json
import unittest
from pathlib import Path

from scripts.change_metrics import derive_change_metric, select_observation
from scripts.insights import generate_candidates, render_insight, render_summary, select_insights
from scripts.model import ROOT, canonical_url
from scripts.page_quality import change_page_skip_reason


CONFIG = {
    "minimum_usable_metrics": 3,
    "minimum_insight_candidates": 3,
    "minimum_selected_insights": 3,
    "maximum_selected_insights": 6,
    "standout_ratio_threshold": 1.75,
    "acceleration_relative_rate_threshold": 0.25,
    "acceleration_percentage_point_rate_threshold": 0.5,
}


def series(slug="gdp", style="currency", values=None, code="NY.GDP.MKTP.CD", name="GDP"):
    observations = [{"year": year, "value": value} for year, value in (values or [])]
    return {
        "country_code": "TST", "indicator_code": code, "indicator_slug": slug,
        "indicator_name": name, "unit": "% of population" if style == "percentage" else "units",
        "format": style, "source_url": f"https://api.worldbank.test/{code}", "observations": observations,
    }


def metric(slug="gdp", style="currency", values=None, code="NY.GDP.MKTP.CD", name="GDP", start=2015, end=2025):
    return derive_change_metric(
        series(slug, style, values, code, name), start, end,
        tolerance_years=1, minimum_span_years=8, acceleration_minimum_observations=6,
    )


class ObservationSelectionTests(unittest.TestCase):
    rows = [{"year": 2014, "value": 1}, {"year": 2015, "value": 2}, {"year": 2016, "value": 3}]

    def test_exact_year_wins(self):
        self.assertEqual(select_observation(self.rows, 2015, 1)["year"], 2015)

    def test_nearest_start_tie_prefers_earlier(self):
        self.assertEqual(select_observation([self.rows[0], self.rows[2]], 2015, 1)["year"], 2014)

    def test_nearest_end_tie_prefers_latest(self):
        self.assertEqual(select_observation([self.rows[0], self.rows[2]], 2015, 1, prefer_latest=True)["year"], 2016)

    def test_tolerance_boundary_is_inclusive(self):
        self.assertEqual(select_observation([{"year": 2014, "value": 1}], 2015, 1)["year"], 2014)

    def test_no_acceptable_year(self):
        self.assertIsNone(select_observation([{"year": 2013, "value": 1}], 2015, 1))

    def test_insufficient_span_skips_metric(self):
        item = series(values=[(2016, 1), (2024, 2)])
        self.assertIsNone(derive_change_metric(item, 2015, 2025, tolerance_years=1, minimum_span_years=9))


class ChangeMathTests(unittest.TestCase):
    def test_absolute_relative_percentage_point_and_cagr(self):
        result = metric("internet-users", "percentage", [(2015, 20), (2025, 40)], "IT.NET.USER.ZS", "Internet users")
        self.assertEqual(result["absolute_change"], 20)
        self.assertEqual(result["percentage_point_change"], 20)
        self.assertEqual(result["percent_change"], 100)
        self.assertAlmostEqual(result["cagr"], 7.177346)
        self.assertEqual(result["direction"], "increased")
        self.assertEqual(result["span_years"], 10)

    def test_zero_start_keeps_absolute_but_not_relative_or_cagr(self):
        result = metric(values=[(2015, 0), (2025, 10)])
        self.assertEqual(result["absolute_change"], 10)
        self.assertIsNone(result["percent_change"])
        self.assertIsNone(result["cagr"])

    def test_negative_start_has_relative_change_but_no_cagr(self):
        result = metric(values=[(2015, -5), (2025, 10)])
        self.assertEqual(result["percent_change"], 300)
        self.assertIsNone(result["cagr"])

    def test_missing_values_are_ignored_not_zeroed(self):
        item = series(values=[(2015, None), (2016, 2), (2025, 4)])
        result = derive_change_metric(item, 2015, 2025, tolerance_years=1, minimum_span_years=8)
        self.assertEqual((result["actual_start_year"], result["start_value"]), (2016, 2))

    def test_source_facts_are_separate_and_traceable(self):
        result = metric(values=[(2015, 10), (2025, 15)])
        self.assertEqual(len(result["source_facts"]), 2)
        self.assertEqual(result["source_facts"][0]["source"], "World Bank")
        self.assertNotIn("percent_change", result["source_facts"][0])


class InsightCandidateTests(unittest.TestCase):
    def setUp(self):
        annual_internet = [(year, 20 + (year - 2015) * (1 if year <= 2020 else 4)) for year in range(2015, 2026)]
        self.metrics = [
            metric("population", "population", [(2015, 100), (2020, 105), (2025, 110)], "SP.POP.TOTL", "Population"),
            metric("gdp", "currency", [(2015, 100), (2020, 140), (2025, 220)], "NY.GDP.MKTP.CD", "GDP"),
            metric("gdp-per-capita", "currency_per_person", [(2015, 100), (2020, 120), (2025, 150)], "NY.GDP.PCAP.CD", "GDP per capita"),
            metric("internet-users", "percentage", annual_internet, "IT.NET.USER.ZS", "Internet users"),
        ]

    def test_required_candidate_types_are_generated(self):
        types = {item["type"] for item in generate_candidates(self.metrics, CONFIG)}
        self.assertIn("largest_relative_change", types)
        self.assertIn("largest_percentage_point_change", types)
        self.assertIn("cagr", types)
        self.assertIn("direction_summary", types)
        self.assertIn("acceleration", types)

    def test_largest_relative_change_uses_non_percentage_metrics(self):
        candidate = next(item for item in generate_candidates(self.metrics, CONFIG) if item["type"] == "largest_relative_change")
        self.assertEqual(candidate["metric_name"], "GDP")

    def test_freshness_caveat_uses_actual_years(self):
        shifted = metric("life-expectancy", "years", [(2014, 70), (2024, 72)], "SP.DYN.LE00.IN", "Life expectancy", 2015, 2025)
        candidates = generate_candidates(self.metrics + [shifted], CONFIG)
        caveat = next(item for item in candidates if item["type"] == "data_freshness_caveat")
        self.assertEqual(caveat["evidence"]["end_years"], [2024, 2025])


class InsightSelectionAndTextTests(unittest.TestCase):
    @staticmethod
    def candidate(kind, priority, metric_id, key):
        return {"type": kind, "priority": priority, "metric_id": metric_id, "dedupe_key": key}

    def test_priority_deduplication_diversity_limit_and_stability(self):
        candidates = [
            self.candidate("scale_change", 45, "A", "same"),
            self.candidate("largest_relative_change", 85, "A", "same"),
            self.candidate("cagr", 70, "A", "cagr:A"),
            self.candidate("cagr", 70, "B", "cagr:B"),
            self.candidate("direction_summary", 60, None, "direction"),
            self.candidate("data_freshness_caveat", 30, None, "freshness"),
        ]
        first = select_insights(candidates, maximum=4)
        second = select_insights(list(reversed(candidates)), maximum=4)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual(first[0]["type"], "largest_relative_change")
        self.assertEqual(sum(item["dedupe_key"] == "same" for item in first), 1)
        self.assertIn("B", {item.get("metric_id") for item in first})

    def test_percentage_point_sentence_matches_evidence(self):
        item = metric("internet-users", "percentage", [(2015, 20), (2025, 40)], "IT.NET.USER.ZS", "Internet users")
        insight = next(candidate for candidate in generate_candidates([item], CONFIG) if candidate["type"] == "largest_percentage_point_change")
        sentence = render_insight(insight)
        self.assertIn("20.0 percentage points", sentence)
        self.assertNotIn("20.0%", sentence)

    def test_rendering_is_deterministic_and_references_present_metrics(self):
        items = [
            metric("population", "population", [(2015, 100), (2025, 110)], "SP.POP.TOTL", "Population"),
            metric("gdp", "currency", [(2015, 100), (2025, 200)], "NY.GDP.MKTP.CD", "GDP"),
            metric("internet-users", "percentage", [(2015, 20), (2025, 40)], "IT.NET.USER.ZS", "Internet users"),
        ]
        selected = select_insights(generate_candidates(items, CONFIG), 6)
        self.assertEqual(render_summary(selected), render_summary(selected))
        self.assertNotIn("Life expectancy", render_summary(selected))


class PageQualityAndOutputTests(unittest.TestCase):
    def test_quality_gate_generates_with_enough_evidence(self):
        metrics = [{"source_url": "https://example.test", "source_facts": [{}, {}]}] * 3
        result = {"candidates": [{}, {}, {}], "selected": [{}, {}, {}]}
        self.assertIsNone(change_page_skip_reason(metrics, result, CONFIG))

    def test_quality_gate_skips_insufficient_data(self):
        reason = change_page_skip_reason([], {"candidates": [], "selected": []}, CONFIG)
        self.assertIn("minimum usable metrics", reason)

    def test_generated_page_has_seo_attribution_and_internal_links(self):
        page = ROOT / "site/countries/india/change/2015-2025/index.html"
        text = page.read_text(encoding="utf-8")
        self.assertIn("<title>How India changed, 2015–2025", text)
        self.assertIn("<h1>How India changed, 2015–2025</h1>", text)
        self.assertIn('<link rel="canonical" href="https://srisusamg.github.io/open-data-pseo-lab/countries/india/change/2015-2025/">', text)
        self.assertIn("World Bank", text)
        self.assertIn('../../">View the India country profile', text)
        self.assertIn('../../../../indicators/internet-users/', text)

    def test_sitemap_includes_generated_and_excludes_skipped_url(self):
        sitemap = (ROOT / "site/sitemap.xml").read_text(encoding="utf-8")
        site = json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
        generated = canonical_url(site["base_url"], "countries/india/change/2015-2025/")
        skipped = canonical_url(site["base_url"], "countries/test/change/2015-2025/")
        self.assertIn(f"<loc>{generated}</loc>", sitemap)
        self.assertNotIn(f"<loc>{skipped}</loc>", sitemap)


if __name__ == "__main__":
    unittest.main()
