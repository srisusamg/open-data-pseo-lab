"""World Bank refresh entry point retained for compatibility."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build import DEFAULT_PATHS  # noqa: E402
from platform.core.configuration import load_site_config  # noqa: E402
from platform.providers.world_bank.client import (  # noqa: E402,F401
    HISTORY_OBSERVATIONS, SCHEMA_VERSION, WorldBankError,
    fetch_indicator, fetch_snapshot as _fetch_snapshot, session_with_retries, source_url,
)

ROOT = Path(__file__).resolve().parents[1]


def fetch_snapshot(output: Path) -> dict:
    site, entities, metrics = load_site_config(DEFAULT_PATHS)
    return _fetch_snapshot(
        output, entities, metrics,
        user_agent=site.get("provider_user_agent", "Reusable-pSEO-platform/1.0"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_PATHS.generated_data / "world_bank_snapshot.json")
    args = parser.parse_args()
    try:
        snapshot = fetch_snapshot(args.output)
    except (WorldBankError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Fetched {len(snapshot['series'])} country/indicator series to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
