"""Compatibility surface for callers written before the platform split."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from scripts.build import DEFAULT_PATHS
from platform.core.configuration import load_json
from platform.core.derivations import calculate_derived_metrics, calculate_period_change
from platform.core.facts import normalize_observations
from platform.core.rendering import format_change, format_difference, format_value
from platform.core.rendering import rank_observations as _rank_observations
from platform.core.urls import base_path, canonical_url, relative_url
from platform.providers.world_bank.client import source_url

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> tuple[dict, list[dict], list[dict]]:
    site = load_json(DEFAULT_PATHS.config / "site.json")
    countries = load_json(DEFAULT_PATHS.config / "countries.json")
    indicators = load_json(DEFAULT_PATHS.config / "indicators.json")
    base_url = site.get("base_url", "")
    if not base_url.startswith("https://") or not base_url.endswith("/"):
        raise ValueError("site base_url must be an https URL ending in '/'")
    return site, countries, indicators


def load_comparisons(countries: list[dict]) -> list[tuple[dict, dict]]:
    configured = load_json(DEFAULT_PATHS.config / "comparisons.json")
    if not isinstance(configured, list):
        raise ValueError("comparisons.json must contain a list of country-code pairs")
    by_code = {country["code"]: country for country in countries}
    resolved, seen = [], set()
    for index, pair in enumerate(configured, 1):
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(code, str) for code in pair):
            raise ValueError(f"comparison {index} must be a two-item list of country codes")
        code_a, code_b = pair
        missing = [code for code in pair if code not in by_code]
        if missing:
            raise ValueError(f"comparison {index} references unknown country code(s): {', '.join(missing)}")
        if code_a == code_b:
            raise ValueError(f"comparison {index} cannot compare {code_a} with itself")
        key = frozenset(pair)
        if key in seen:
            raise ValueError(f"comparison {index} duplicates an existing pair (including reversed pairs): {code_a}/{code_b}")
        seen.add(key)
        resolved.append((by_code[code_a], by_code[code_b]))
    return resolved


def latest_non_null(records: Iterable[dict]) -> dict | None:
    valid = [row for row in records if row.get("value") is not None]
    return max(valid, key=lambda row: int(row["date"])) if valid else None


def normalize_history(records: Iterable[dict], limit: int = 15) -> list[dict]:
    return normalize_observations(
        ({"year": row.get("date"), "value": row.get("value")} for row in records), limit,
    )


def rank_observations(observations: Iterable[dict]) -> list[dict]:
    rows = []
    for item in observations:
        rows.append({**item, "entity_name": item.get("entity_name", item.get("country_name", ""))})
    return _rank_observations(rows)
