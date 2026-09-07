"""Backward-compatible imports for the canonical change recipe."""

from __future__ import annotations

from platform.recipes.change import change_path, derive_change_metric as _derive_change_metric, select_observation


def derive_change_metric(series: dict, *args, **kwargs) -> dict | None:
    canonical = dict(series)
    aliases = {
        "entity_id": "country_code", "metric_id": "indicator_code",
        "metric_slug": "indicator_slug", "metric_name": "indicator_name",
    }
    for target, source in aliases.items():
        if target not in canonical and source in canonical:
            canonical[target] = canonical[source]
    canonical.setdefault("provenance", {
        "source_name": "World Bank", "source_url": canonical.get("source_url", ""),
        "source_metric_id": canonical.get("metric_id", ""),
    })
    result = _derive_change_metric(canonical, *args, **kwargs)
    if result:
        for fact in result["source_facts"]:
            fact.setdefault("source", fact["provenance"]["source_name"])
    return result


__all__ = ["change_path", "derive_change_metric", "select_observation"]
