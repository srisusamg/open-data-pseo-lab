"""Filesystem-backed site definition without provider or recipe behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class SitePaths:
    root: Path
    output: Path
    generated_data: Path

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def static(self) -> Path:
        return self.root / "static"


def load_site_config(paths: SitePaths) -> tuple[dict, list[dict], list[dict]]:
    site = load_json(paths.config / "site.json")
    entities = load_json(paths.config / "countries.json")
    metrics = load_json(paths.config / "indicators.json")
    base_url = site.get("base_url", "")
    if not base_url.startswith("https://") or not base_url.endswith("/"):
        raise ValueError("site base_url must be an https URL ending in '/'")
    return site, entities, metrics


def load_comparisons(paths: SitePaths, entities: list[dict]) -> list[tuple[dict, dict]]:
    """Resolve and validate the ordered comparison allow-list against canonical entities."""
    configured = load_json(paths.config / "comparisons.json")
    if not isinstance(configured, list):
        raise ValueError("comparisons.json must contain a list of entity-id pairs")
    by_id = {entity["id"]: entity for entity in entities}
    resolved, seen = [], set()
    for index, pair in enumerate(configured, 1):
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
            raise ValueError(f"comparison {index} must be a two-item list of entity ids")
        id_a, id_b = pair
        missing = [identifier for identifier in pair if identifier not in by_id]
        if missing:
            raise ValueError(f"comparison {index} references unknown entity id(s): {', '.join(missing)}")
        if id_a == id_b:
            raise ValueError(f"comparison {index} cannot compare {id_a} with itself")
        key = frozenset(pair)
        if key in seen:
            raise ValueError(f"comparison {index} duplicates an existing pair (including reversed pairs): {id_a}/{id_b}")
        seen.add(key)
        resolved.append((by_id[id_a], by_id[id_b]))
    return resolved
