import unittest

from scripts.model import canonical_url, format_value, latest_non_null, rank_observations, relative_url, source_url


class SelectionTests(unittest.TestCase):
    def test_latest_non_null_skips_missing_values(self):
        rows = [{"date": "2024", "value": None}, {"date": "2023", "value": 7}, {"date": "2022", "value": 9}]
        self.assertEqual(latest_non_null(rows), {"date": "2023", "value": 7})

    def test_latest_non_null_returns_none_when_all_missing(self):
        self.assertIsNone(latest_non_null([{"date": "2024", "value": None}]))


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


if __name__ == "__main__": unittest.main()
