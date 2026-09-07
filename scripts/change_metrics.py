"""Select real historical facts and calculate deterministic change metrics."""

from __future__ import annotations

from typing import Iterable


def _valid_observations(history: Iterable[dict]) -> list[dict]:
    by_year: dict[int, float] = {}
    for row in history:
        value = row.get("value")
        year = row.get("year")
        if not isinstance(year, int) or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        by_year[year] = float(value)
    return [{"year": year, "value": by_year[year]} for year in sorted(by_year)]


def select_observation(
    history: Iterable[dict], requested_year: int, tolerance_years: int, *, prefer_latest: bool = False
) -> dict | None:
    """Select the nearest real observation; resolve ties deterministically."""
    candidates = [row for row in _valid_observations(history) if abs(row["year"] - requested_year) <= tolerance_years]
    if not candidates:
        return None
    tie_break = (lambda row: -row["year"]) if prefer_latest else (lambda row: row["year"])
    return min(candidates, key=lambda row: (abs(row["year"] - requested_year), tie_break(row)))


def _direction(change: float) -> str:
    if change > 0:
        return "increased"
    if change < 0:
        return "declined"
    return "unchanged"


def _segment_rate(start: dict, end: dict, percentage_metric: bool) -> float | None:
    span = end["year"] - start["year"]
    if span <= 0:
        return None
    difference = end["value"] - start["value"]
    if percentage_metric:
        return difference / span
    if start["value"] == 0:
        return None
    return (difference / abs(start["value"]) * 100) / span


def _phase_rates(rows: list[dict], percentage_metric: bool, minimum_observations: int) -> dict | None:
    if len(rows) < minimum_observations:
        return None
    midpoint = (rows[0]["year"] + rows[-1]["year"]) / 2
    pivot = min(rows, key=lambda row: (abs(row["year"] - midpoint), row["year"]))
    before = [row for row in rows if row["year"] <= pivot["year"]]
    after = [row for row in rows if row["year"] >= pivot["year"]]
    if len(before) < 3 or len(after) < 3:
        return None
    earlier_rate = _segment_rate(before[0], before[-1], percentage_metric)
    later_rate = _segment_rate(after[0], after[-1], percentage_metric)
    if earlier_rate is None or later_rate is None:
        return None
    return {
        "earlier_rate": round(earlier_rate, 6),
        "later_rate": round(later_rate, 6),
        "split_year": pivot["year"],
        "rate_unit": "percentage_points_per_year" if percentage_metric else "percent_per_year",
    }


def derive_change_metric(
    series: dict,
    requested_start_year: int,
    requested_end_year: int,
    *,
    tolerance_years: int,
    minimum_span_years: int,
    acceleration_minimum_observations: int = 6,
) -> dict | None:
    """Create source-fact endpoints and separate calculations for one series."""
    history = series.get("observations", [])
    start = select_observation(history, requested_start_year, tolerance_years)
    end = select_observation(history, requested_end_year, tolerance_years, prefer_latest=True)
    if not start or not end or end["year"] <= start["year"]:
        return None
    span = end["year"] - start["year"]
    if span < minimum_span_years:
        return None
    start_value, end_value = start["value"], end["value"]
    absolute_change = end_value - start_value
    percent_change = None if start_value == 0 else (absolute_change / abs(start_value)) * 100
    percentage_point_change = absolute_change if series.get("format") == "percentage" else None
    cagr = None
    if start_value > 0 and end_value > 0:
        cagr = ((end_value / start_value) ** (1 / span) - 1) * 100
    rows = [row for row in _valid_observations(history) if start["year"] <= row["year"] <= end["year"]]
    facts = [
        {
            "entity_id": series["country_code"], "metric_id": series["indicator_code"],
            "value": start_value, "unit": series["unit"], "observation_year": start["year"], "source": "World Bank",
        },
        {
            "entity_id": series["country_code"], "metric_id": series["indicator_code"],
            "value": end_value, "unit": series["unit"], "observation_year": end["year"], "source": "World Bank",
        },
    ]
    return {
        "entity_id": series["country_code"],
        "metric_id": series["indicator_code"],
        "metric_slug": series["indicator_slug"],
        "metric_name": series["indicator_name"],
        "unit": series["unit"],
        "format": series["format"],
        "requested_start_year": requested_start_year,
        "requested_end_year": requested_end_year,
        "actual_start_year": start["year"],
        "actual_end_year": end["year"],
        "start_value": start_value,
        "end_value": end_value,
        "absolute_change": round(absolute_change, 6),
        "percent_change": round(percent_change, 6) if percent_change is not None else None,
        "percentage_point_change": round(percentage_point_change, 6) if percentage_point_change is not None else None,
        "cagr": round(cagr, 6) if cagr is not None else None,
        "direction": _direction(absolute_change),
        "span_years": span,
        "phase_rates": _phase_rates(rows, series.get("format") == "percentage", acceleration_minimum_observations),
        "source_facts": facts,
        "source_url": series["source_url"],
    }


def change_path(country: dict, start_year: int, end_year: int) -> str:
    return f"countries/{country['slug']}/change/{start_year}-{end_year}/"
