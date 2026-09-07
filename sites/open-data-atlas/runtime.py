"""OpenData Atlas paths and World Bank provider composition."""

from __future__ import annotations

from pathlib import Path

from platform.core.configuration import SitePaths
from platform.providers.world_bank.client import SCHEMA_VERSION, fetch_snapshot as fetch_world_bank_snapshot
from platform.providers.world_bank.normalizer import normalize_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PATHS = SitePaths(
    root=Path(__file__).resolve().parent,
    output=PROJECT_ROOT / "site",
    generated_data=PROJECT_ROOT / "data" / "generated",
)


def fetch_snapshot(output: Path, site: dict, entities: list[dict], metrics: list[dict]) -> dict:
    return fetch_world_bank_snapshot(
        output, entities, metrics,
        user_agent=site.get("provider_user_agent", "Reusable-pSEO-platform/1.0"),
    )
