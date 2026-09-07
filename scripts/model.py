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


def latest_non_null(records: Iterable[dict]) -> dict | None:
    """Select the newest numeric observation, never inventing a missing value."""
    valid = [row for row in records if row.get("value") is not None]
    if not valid:
        return None
    return max(valid, key=lambda row: int(row["date"]))


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
    return f"{number:,}"
