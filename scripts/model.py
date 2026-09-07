"""Configuration, URL, selection, ranking, and formatting helpers."""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_config() -> tuple[dict, list[dict], list[dict]]:
    site = load_json(ROOT / "config" / "site.json")
    countries = load_json(ROOT / "config" / "countries.json")
    indicators = load_json(ROOT / "config" / "indicators.json")
    base_url = site.get("base_url", "")
    if not base_url.startswith("https://") or not base_url.endswith("/"):
        raise ValueError("config/site.json base_url must be an https URL ending in '/'")
    return site, countries, indicators


def load_comparisons(countries: list[dict]) -> list[tuple[dict, dict]]:
    """Resolve and validate the ordered comparison allow-list."""
    configured = load_json(ROOT / "config" / "comparisons.json")
    if not isinstance(configured, list):
        raise ValueError("config/comparisons.json must contain a list of country-code pairs")
    by_code = {country["code"]: country for country in countries}
    resolved = []
    seen: set[frozenset[str]] = set()
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
    """Select the newest numeric observation, never inventing a missing value."""
    valid = [row for row in records if row.get("value") is not None]
    if not valid:
        return None
    return max(valid, key=lambda row: int(row["date"]))


def normalize_history(records: Iterable[dict], limit: int = 15) -> list[dict]:
    """Return the newest real observations with their source years unchanged."""
    by_year: dict[int, int | float] = {}
    for row in records:
        value = row.get("value")
        if value is None:
            continue
        try:
            year = int(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        by_year[year] = value
    years = sorted(by_year, reverse=True)[:limit]
    return [{"year": year, "value": by_year[year]} for year in years]


def calculate_period_change(history: Iterable[dict], years: int) -> dict | None:
    """Compare the latest value with the exact calendar-year endpoint."""
    rows = list(history)
    if not rows:
        return None
    latest = max(rows, key=lambda row: int(row["year"]))
    end_year = int(latest["year"])
    start_year = end_year - years
    start = next((row for row in rows if int(row["year"]) == start_year), None)
    if start is None:
        return None
    start_value = float(start["value"])
    end_value = float(latest["value"])
    if start_value == 0:
        return None
    percentage_change = round(((end_value - start_value) / start_value) * 100, 6)
    cagr = None
    if start_value > 0 and end_value > 0:
        cagr = round(((end_value / start_value) ** (1 / years) - 1) * 100, 6)
    return {
        "start_year": start_year,
        "end_year": end_year,
        "percentage_change": percentage_change,
        "cagr": cagr,
    }


def calculate_derived_metrics(history: Iterable[dict]) -> dict:
    rows = list(history)
    return {
        "basis": "Exact calendar-year endpoints relative to the latest observation; no interpolation",
        "five_year": calculate_period_change(rows, 5),
        "ten_year": calculate_period_change(rows, 10),
    }


def rank_observations(observations: Iterable[dict]) -> list[dict]:
    available = [item for item in observations if item.get("value") is not None]
    return sorted(available, key=lambda item: (-float(item["value"]), item["country_name"]))


def source_url(country_code: str, indicator_code: str) -> str:
    return (
        "https://api.worldbank.org/v2/country/"
        f"{quote(country_code)}/indicator/{quote(indicator_code, safe='.')}?format=json"
    )


def canonical_url(base_url: str, page_path: str) -> str:
    return urljoin(base_url, page_path.lstrip("/"))


def relative_url(from_page: str, to_page: str) -> str:
    """Return a link between generated page paths, preserving trailing slashes."""
    start = posixpath.dirname(from_page)
    target = to_page.rstrip("/") or "."
    result = posixpath.relpath(target, start=start or ".")
    if to_page.endswith("/") or to_page == "":
        result += "/"
    return result


def base_path(base_url: str) -> str:
    path = urlparse(base_url).path
    return path if path.endswith("/") else path + "/"


def format_value(value: int | float | None, style: str) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if style == "population":
        return f"{number:,.0f}"
    if style == "currency":
        if abs(number) >= 1_000_000_000_000:
            return f"US${number / 1_000_000_000_000:.2f} trillion"
        if abs(number) >= 1_000_000_000:
            return f"US${number / 1_000_000_000:.2f} billion"
        return f"US${number:,.0f}"
    if style == "currency_per_person":
        return f"US${number:,.2f}"
    if style == "percentage":
        return f"{number:.1f}%"
    if style == "years":
        return f"{number:.1f} years"
    return f"{number:,}"


def format_change(value: int | float | None) -> str:
    if value is None:
        return "Not available"
    return f"{float(value):+.1f}%"


def format_difference(value: int | float | None, style: str) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if style == "percentage":
        return f"{number:+.1f} percentage points"
    sign = "+" if number > 0 else "-" if number < 0 else ""
    return sign + format_value(abs(number), style)
