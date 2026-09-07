"""Deterministic comparison recipe over canonical entities and normalized series."""

from __future__ import annotations

from typing import Iterable


def comparison_path(entity_a: dict, entity_b: dict) -> str:
    """Return the stable path for an ordered configured pair."""
    return f"compare/{entity_a['slug']}/{entity_b['slug']}/"


def _period_metric(series: dict, period: str) -> dict | None:
    metric = series.get("derived_metrics", {}).get(period)
    return metric if isinstance(metric, dict) else None


def _growth_leader(entity_a: dict, entity_b: dict, metric_a: dict | None, metric_b: dict | None) -> dict | None:
    if not metric_a or not metric_b:
        return None
    a_change = metric_a.get("percentage_change")
    b_change = metric_b.get("percentage_change")
    if a_change is None or b_change is None or a_change == b_change:
        return None
    leader = entity_a if a_change > b_change else entity_b
    return {"entity_id": leader["id"], "entity_name": leader["name"], "metric": "percentage_change"}


def _cagr_leader(entity_a: dict, entity_b: dict, metric_a: dict | None, metric_b: dict | None) -> dict | None:
    if not metric_a or not metric_b:
        return None
    a_cagr = metric_a.get("cagr")
    b_cagr = metric_b.get("cagr")
    if a_cagr is None or b_cagr is None or a_cagr == b_cagr:
        return None
    leader = entity_a if a_cagr > b_cagr else entity_b
    return {"entity_id": leader["id"], "entity_name": leader["name"], "metric": "cagr"}


def _gap_direction(series_a: dict, series_b: dict, years: int) -> dict | None:
    """Compare a scale-neutral relative gap at matching exact endpoints."""
    history_a = {row["year"]: float(row["value"]) for row in series_a.get("observations", [])}
    history_b = {row["year"]: float(row["value"]) for row in series_b.get("observations", [])}
    latest_a = series_a.get("latest_observation")
    latest_b = series_b.get("latest_observation")
    if not latest_a or not latest_b or latest_a["year"] != latest_b["year"]:
        return None
    end_year = int(latest_a["year"])
    start_year = end_year - years
    values = (history_a.get(start_year), history_b.get(start_year), history_a.get(end_year), history_b.get(end_year))
    if any(value is None or value <= 0 for value in values):
        return None
    start_gap = abs(values[0] - values[1]) / max(values[0], values[1]) * 100
    end_gap = abs(values[2] - values[3]) / max(values[2], values[3]) * 100
    if abs(start_gap - end_gap) < 1e-9:
        direction = "unchanged"
    else:
        direction = "narrowed" if end_gap < start_gap else "widened"
    return {
        "period_years": years,
        "start_year": start_year,
        "end_year": end_year,
        "start_relative_gap": round(start_gap, 6),
        "end_relative_gap": round(end_gap, 6),
        "direction": direction,
    }


def calculate_metric_comparison(entity_a: dict, entity_b: dict, series_a: dict, series_b: dict) -> dict:
    latest_a = series_a.get("latest_observation")
    latest_b = series_b.get("latest_observation")
    comparable = bool(latest_a and latest_b)
    absolute_difference = percentage_difference = None
    leader = None
    if comparable:
        value_a = float(latest_a["value"])
        value_b = float(latest_b["value"])
        absolute_difference = round(value_a - value_b, 6)
        if value_b != 0:
            percentage_difference = round(((value_a - value_b) / abs(value_b)) * 100, 6)
        if value_a != value_b:
            leading_entity = entity_a if value_a > value_b else entity_b
            leader = {"entity_id": leading_entity["id"], "entity_name": leading_entity["name"]}

    periods = {}
    for key, years in (("five_year", 5), ("ten_year", 10)):
        metric_a = _period_metric(series_a, key)
        metric_b = _period_metric(series_b, key)
        periods[key] = {
            "years": years,
            "entity_a": metric_a,
            "entity_b": metric_b,
            "growth_leader": _growth_leader(entity_a, entity_b, metric_a, metric_b),
            "cagr_leader": _cagr_leader(entity_a, entity_b, metric_a, metric_b),
        }

    relative_gap = None
    if comparable:
        a_value = float(latest_a["value"])
        b_value = float(latest_b["value"])
        denominator = max(abs(a_value), abs(b_value))
        if denominator > 0:
            relative_gap = round(abs(a_value - b_value) / denominator * 100, 6)

    return {
        "metric_id": series_a["metric_id"],
        "metric_slug": series_a["metric_slug"],
        "metric_name": series_a["metric_name"],
        "unit": series_a["unit"],
        "format": series_a["format"],
        "entity_a": latest_a,
        "entity_b": latest_b,
        "absolute_difference": absolute_difference,
        "percentage_difference": percentage_difference,
        "relative_gap": relative_gap,
        "leader": leader,
        "temporally_imperfect": bool(comparable and latest_a["year"] != latest_b["year"]),
        "periods": periods,
        "gap_change": _gap_direction(series_a, series_b, 10) or _gap_direction(series_a, series_b, 5),
        "provenance": [series_a["provenance"], series_b["provenance"]],
    }


def build_comparison(entity_a: dict, entity_b: dict, series_a: Iterable[dict], series_b: Iterable[dict]) -> dict:
    by_metric_b = {item["metric_id"]: item for item in series_b}
    metrics = [
        calculate_metric_comparison(entity_a, entity_b, item, by_metric_b[item["metric_id"]])
        for item in series_a
        if item["metric_id"] in by_metric_b
    ]
    return {"entity_a": entity_a, "entity_b": entity_b, "path": comparison_path(entity_a, entity_b), "metrics": metrics}
