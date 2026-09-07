"""Backward-compatible adapters for the canonical comparison recipe."""

from __future__ import annotations

from platform.recipes.comparison import (
    build_comparison as _build_comparison,
    calculate_metric_comparison as _calculate_metric_comparison,
    comparison_path,
)


def _entity(item: dict) -> dict:
    return {"id": item.get("id", item.get("code")), "slug": item["slug"], "name": item["name"]}


def _series(item: dict) -> dict:
    result = dict(item)
    aliases = {
        "entity_id": "country_code", "metric_id": "indicator_code",
        "metric_slug": "indicator_slug", "metric_name": "indicator_name",
    }
    for target, source in aliases.items():
        if target not in result and source in result:
            result[target] = result[source]
    result.setdefault("provenance", {
        "source_name": "World Bank", "source_url": result.get("source_url", ""),
        "source_metric_id": result.get("metric_id", ""),
    })
    return result


def _legacy_aliases(result: dict) -> dict:
    result["country_a"], result["country_b"] = result["entity_a"], result["entity_b"]
    for metric in result["metrics"]:
        metric.update({
            "indicator_code": metric["metric_id"], "indicator_slug": metric["metric_slug"],
            "indicator_name": metric["metric_name"], "country_a": metric["entity_a"],
            "country_b": metric["entity_b"],
            "source_urls": [item["source_url"] for item in metric["provenance"]],
        })
        if metric.get("leader"):
            metric["leader"].update({
                "country_code": metric["leader"]["entity_id"],
                "country_name": metric["leader"]["entity_name"],
            })
        for period in metric["periods"].values():
            period["country_a"], period["country_b"] = period["entity_a"], period["entity_b"]
            for key in ("growth_leader", "cagr_leader"):
                if period[key]:
                    period[key].update({
                        "country_code": period[key]["entity_id"],
                        "country_name": period[key]["entity_name"],
                    })
    return result


def calculate_indicator_comparison(country_a: dict, country_b: dict, series_a: dict, series_b: dict) -> dict:
    result = _calculate_metric_comparison(_entity(country_a), _entity(country_b), _series(series_a), _series(series_b))
    wrapped = {"entity_a": _entity(country_a), "entity_b": _entity(country_b), "metrics": [result]}
    return _legacy_aliases(wrapped)["metrics"][0]


def build_comparison(country_a: dict, country_b: dict, series_a, series_b) -> dict:
    result = _build_comparison(_entity(country_a), _entity(country_b), map(_series, series_a), map(_series, series_b))
    return _legacy_aliases(result)


__all__ = ["build_comparison", "calculate_indicator_comparison", "comparison_path"]
