import unittest

from scripts.model import (
    calculate_derived_metrics,
    calculate_period_change,
    canonical_url,
    format_change,
    format_value,
    latest_non_null,
    normalize_history,
    rank_observations,
    relative_url,
    source_url,
)


class SelectionTests(unittest.TestCase):
    def test_latest_non_null_skips_missing_values(self):
        rows = [{"date": "2024", "value": None}, {"date": "2023", "value": 7}, {"date": "2022", "value": 9}]
        self.assertEqual(latest_non_null(rows), {"date": "2023", "value": 7})

    def test_latest_non_null_returns_none_when_all_missing(self):
        self.assertIsNone(latest_non_null([{"date": "2024", "value": None}]))

    def test_history_keeps_real_years_without_interpolation(self):
        rows = [
            {"date": "2024", "value": 12},
            {"date": "2023", "value": None},
            {"date": "2022", "value": 10},
            {"date": "bad", "value": 9},
        ]
        self.assertEqual(normalize_history(rows), [{"year": 2024, "value": 12}, {"year": 2022, "value": 10}])

    def test_history_is_limited_to_newest_available_observations(self):
        rows = [{"date": str(year), "value": year} for year in range(2000, 2021)]
        history = normalize_history(rows, 15)
        self.assertEqual(len(history), 15)
        self.assertEqual((history[0]["year"], history[-1]["year"]), (2020, 2006))


class DerivedMetricTests(unittest.TestCase):
    def test_exact_five_year_change_and_cagr(self):
        history = [{"year": 2024, "value": 200}, {"year": 2019, "value": 100}]
        result = calculate_period_change(history, 5)
        self.assertEqual(result["percentage_change"], 100.0)
        self.assertAlmostEqual(result["cagr"], 14.869835)
        self.assertEqual((result["start_year"], result["end_year"]), (2019, 2024))

    def test_missing_exact_endpoint_is_not_interpolated(self):
        history = [{"year": 2024, "value": 200}, {"year": 2018, "value": 100}]
        self.assertIsNone(calculate_period_change(history, 5))

    def test_zero_baseline_is_invalid(self):
        history = [{"year": 2024, "value": 10}, {"year": 2019, "value": 0}]
        self.assertIsNone(calculate_period_change(history, 5))

    def test_negative_endpoint_allows_change_but_not_cagr(self):
        history = [{"year": 2024, "value": 10}, {"year": 2019, "value": -5}]
        result = calculate_period_change(history, 5)
        self.assertEqual(result["percentage_change"], -300.0)
        self.assertIsNone(result["cagr"])

    def test_derived_metrics_are_separate_periods(self):
        history = [{"year": 2024, "value": 121}, {"year": 2019, "value": 110}, {"year": 2014, "value": 100}]
        result = calculate_derived_metrics(history)
        self.assertEqual(result["five_year"]["percentage_change"], 10.0)
        self.assertEqual(result["ten_year"]["percentage_change"], 21.0)


class RankingTests(unittest.TestCase):
    def test_ranking_is_descending_and_excludes_missing(self):
        rows = [{"country_name": "Beta", "value": 2}, {"country_name": "Alpha", "value": 2}, {"country_name": "Missing", "value": None}, {"country_name": "Gamma", "value": 4}]
        self.assertEqual([row["country_name"] for row in rank_observations(rows)], ["Gamma", "Alpha", "Beta"])


class UrlTests(unittest.TestCase):
    def test_canonical_url_preserves_project_subpath(self):
        base = "https://example.github.io/open-data-pseo-lab/"
        self.assertEqual(canonical_url(base, "countries/india/"), base + "countries/india/")

    def test_relative_links_work_between_nested_pages(self):
        self.assertEqual(relative_url("countries/india/", "indicators/gdp/"), "../../indicators/gdp/")
        self.assertEqual(relative_url("indicators/gdp/", ""), "../../")

    def test_source_url_is_deterministic(self):
        self.assertEqual(source_url("IND", "SP.POP.TOTL"), "https://api.worldbank.org/v2/country/IND/indicator/SP.POP.TOTL?format=json")


class FormattingTests(unittest.TestCase):
    def test_missing_values_are_not_formatted_as_zero(self):
        self.assertEqual(format_value(None, "population"), "Not available")

    def test_life_expectancy_is_formatted_in_years(self):
        self.assertEqual(format_value(76.4321, "years"), "76.4 years")

    def test_change_includes_sign(self):
        self.assertEqual(format_change(4.25), "+4.2%")
        self.assertEqual(format_change(-4.25), "-4.2%")


if __name__ == "__main__": unittest.main()
