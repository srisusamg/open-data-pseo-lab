"""Validate the human-editable AI model fact file without building the site."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform.providers.ai_models.curated import load_catalog
from platform.providers.ai_models.hybrid import load_curated_facts, load_field_registry

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "sites" / "ai-model-economics"


def main() -> int:
    registry = load_field_registry(SITE / "config" / "field_registry.json")
    catalog = load_catalog(SITE / "config" / "catalog.json")
    facts = load_curated_facts(ROOT / "data" / "curated" / "model_facts.csv", registry, {item["id"] for item in catalog["models"]})
    print(f"Validated {len(facts)} curated facts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
