"""Reusable, deterministic programmatic-SEO platform.

The requested package name overlaps Python's standard-library ``platform``
module. Re-exporting that module's public API keeps third-party imports such as
``platform.system()`` working while allowing ``platform.core`` subpackages.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_stdlib_path = Path(os.__file__).with_name("platform.py")
_spec = importlib.util.spec_from_file_location("_stdlib_platform", _stdlib_path)
if _spec is None or _spec.loader is None:  # pragma: no cover - interpreter invariant
    raise ImportError(f"cannot load standard-library platform module from {_stdlib_path}")
_stdlib_platform = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stdlib_platform)
for _name in dir(_stdlib_platform):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_stdlib_platform, _name))

del _name, _spec, _stdlib_path
