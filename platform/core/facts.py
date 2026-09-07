"""Canonical normalized facts and series utilities."""

from __future__ import annotations

from typing import Iterable, TypedDict

from platform.core.entities import Entity, Metric
from platform.core.provenance import Provenance


class Observation(TypedDict):
    year: int
    value: int | float


class Fact(TypedDict):
    entity_id: str
    metric_id: str
    value: int | float
    unit: str
    observation_year: int
    provenance: Provenance


class NormalizedSeries(TypedDict):
    entity: Entity
    metric: Metric
    observations: list[Observation]
    latest_observation: Observation | None
    derived_metrics: dict
    provenance: Provenance


def normalize_observations(records: Iterable[dict], limit: int = 15) -> list[Observation]:
    """Keep newest valid year/value pairs without interpolation or substitution."""
    by_year: dict[int, int | float] = {}
    for row in records:
        value = row.get("value")
        try:
            year = int(row["year"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        by_year[year] = value
    return [{"year": year, "value": by_year[year]} for year in sorted(by_year, reverse=True)[:limit]]


def facts_for_series(series: NormalizedSeries) -> list[Fact]:
    """Expand a normalized series into traceable canonical facts."""
    return [
        {
            "entity_id": series["entity"]["id"], "metric_id": series["metric"]["id"],
            "value": row["value"], "unit": series["metric"]["unit"],
            "observation_year": row["year"], "provenance": series["provenance"],
        }
        for row in series["observations"]
    ]


def series_value(series: NormalizedSeries) -> dict:
    """Create the provider-neutral flattened view used by standard recipes."""
    entity, metric = series["entity"], series["metric"]
    return {
        "entity_id": entity["id"], "entity_slug": entity["slug"], "entity_name": entity["name"],
        "metric_id": metric["id"], "metric_slug": metric["slug"], "metric_name": metric["name"],
        "unit": metric["unit"], "format": metric["format"],
        "latest_observation": series["latest_observation"], "observations": series["observations"],
        "derived_metrics": series["derived_metrics"], "provenance": series["provenance"],
        "source_url": series["provenance"]["source_url"],
    }
