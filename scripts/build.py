"""OpenData Atlas build entry point retained for CI and local users."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform import build as platform_build  # noqa: E402

_runtime = importlib.import_module("sites.open-data-atlas.runtime")
DEFAULT_PATHS = _runtime.PATHS
ROOT = Path(__file__).resolve().parents[1]


def render_site(snapshot: dict, paths=DEFAULT_PATHS) -> int:
    return platform_build.render_site(
        snapshot, paths, _runtime.normalize_snapshot, _runtime.SCHEMA_VERSION,
    )


def main(paths=DEFAULT_PATHS) -> int:
    return platform_build.main(
        paths, _runtime.fetch_snapshot, _runtime.normalize_snapshot, _runtime.SCHEMA_VERSION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
