"""Build entry point for the AI Model Economics site."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_runtime = importlib.import_module("sites.ai-model-economics.runtime")
_builder = importlib.import_module("sites.ai-model-economics.build")
DEFAULT_PATHS = _runtime.PATHS


def main() -> int:
    try:
        count = _builder.render_site(DEFAULT_PATHS)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: AI Model Economics build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {count} AI Model Economics HTML pages in {DEFAULT_PATHS.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
