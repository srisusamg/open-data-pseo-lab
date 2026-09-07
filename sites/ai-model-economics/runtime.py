"""AI Model Economics paths and curated provider composition."""

from __future__ import annotations

from pathlib import Path

from platform.core.configuration import SitePaths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PATHS = SitePaths(
    root=Path(__file__).resolve().parent,
    output=PROJECT_ROOT / "site" / "ai-model-economics",
    generated_data=PROJECT_ROOT / "data" / "generated" / "ai-model-economics",
)

