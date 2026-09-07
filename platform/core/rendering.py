"""Reusable rendering, output, ranking, and display-format utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def rank_observations(observations: Iterable[dict]) -> list[dict]:
    available = [item for item in observations if item.get("value") is not None]
    return sorted(available, key=lambda item: (-float(item["value"]), item["entity_name"]))


def format_value(value: int | float | None, style: str) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if style == "population":
        return f"{number:,.0f}"
    if style == "currency":
        if abs(number) >= 1_000_000_000_000:
            return f"US${number / 1_000_000_000_000:.2f} trillion"
        if abs(number) >= 1_000_000_000:
            return f"US${number / 1_000_000_000:.2f} billion"
        return f"US${number:,.0f}"
    if style == "currency_per_person":
        return f"US${number:,.2f}"
    if style == "percentage":
        return f"{number:.1f}%"
    if style == "years":
        return f"{number:.1f} years"
    return f"{number:,}"


def format_change(value: int | float | None) -> str:
    return "Not available" if value is None else f"{float(value):+.1f}%"


def format_difference(value: int | float | None, style: str) -> str:
    if value is None:
        return "Not available"
    number = float(value)
    if style == "percentage":
        return f"{number:+.1f} percentage points"
    sign = "+" if number > 0 else "-" if number < 0 else ""
    return sign + format_value(abs(number), style)


def template_environment(template_root: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(template_root),
        autoescape=select_autoescape(("html", "xml")), trim_blocks=True, lstrip_blocks=True,
    )
    env.filters.update(value=format_value, change=format_change, difference=format_difference)
    return env
