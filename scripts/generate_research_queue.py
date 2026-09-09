"""Regenerate the AI Model Economics reports and research queue."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_ai_model_economics import main


if __name__ == "__main__":
    raise SystemExit(main())
