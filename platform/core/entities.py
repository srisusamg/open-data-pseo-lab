"""Canonical entity and metric definitions shared by providers and recipes."""

from __future__ import annotations

from typing import Any, TypedDict


class Entity(TypedDict):
    id: str
    slug: str
    name: str


class Metric(TypedDict):
    id: str
    slug: str
    name: str
    unit: str
    format: str


def entity_from_config(item: dict[str, Any]) -> Entity:
    """Map a site/provider identifier to the small canonical entity contract."""
    identifier = item.get("id", item.get("code"))
    if not identifier:
        raise ValueError("entity requires an id (or compatibility code)")
    return {"id": str(identifier), "slug": str(item["slug"]), "name": str(item["name"])}


def metric_from_config(item: dict[str, Any]) -> Metric:
    """Map a site/provider metric definition to the canonical metric contract."""
    identifier = item.get("id", item.get("code"))
    if not identifier:
        raise ValueError("metric requires an id (or compatibility code)")
    return {
        "id": str(identifier), "slug": str(item["slug"]), "name": str(item["name"]),
        "unit": str(item["unit"]), "format": str(item["format"]),
    }
