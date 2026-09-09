"""Safely import completed research rows into the curated fact store."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform.providers.ai_models.curated import load_catalog
from platform.providers.ai_models.hybrid import CURATED_COLUMNS, load_field_registry, validate_curated_rows

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "sites" / "ai-model-economics"
DESTINATION = ROOT / "data" / "curated" / "model_facts.csv"


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CURATED_COLUMNS:
            raise ValueError("input columns do not match the curated fact schema")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader if (row.get("value") or "").strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--overwrite", action="store_true", help="replace existing model/field rows")
    args = parser.parse_args()
    incoming, existing = _read(args.path), _read(DESTINATION)
    catalog = load_catalog(SITE / "config" / "catalog.json")
    registry = load_field_registry(SITE / "config" / "field_registry.json")
    errors = validate_curated_rows(incoming, registry, {item["id"] for item in catalog["models"]})
    if errors:
        raise ValueError("invalid import: " + "; ".join(errors))
    incoming_keys = {(row["model_id"], row["field_id"]) for row in incoming}
    collisions = incoming_keys & {(row["model_id"], row["field_id"]) for row in existing}
    if collisions and not args.overwrite:
        raise ValueError("existing curated facts would be overwritten; rerun with --overwrite: " + ", ".join(f"{a}/{b}" for a, b in sorted(collisions)))
    if args.overwrite:
        existing = [row for row in existing if (row["model_id"], row["field_id"]) not in incoming_keys]
    rows = sorted(existing + incoming, key=lambda row: (row["model_id"], row["field_id"]))
    with DESTINATION.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CURATED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Imported {len(incoming)} curated facts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
