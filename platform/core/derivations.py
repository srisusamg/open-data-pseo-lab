"""Provider-neutral deterministic calculations over normalized observations."""

from __future__ import annotations

from typing import Iterable


def calculate_period_change(history: Iterable[dict], years: int) -> dict | None:
    rows = list(history)
    if not rows:
        return None
    latest = max(rows, key=lambda row: int(row["year"]))
    end_year = int(latest["year"])
    start_year = end_year - years
    start = next((row for row in rows if int(row["year"]) == start_year), None)
    if start is None:
        return None
    start_value, end_value = float(start["value"]), float(latest["value"])
    if start_value == 0:
        return None
    percentage_change = round(((end_value - start_value) / start_value) * 100, 6)
    cagr = None
    if start_value > 0 and end_value > 0:
        cagr = round(((end_value / start_value) ** (1 / years) - 1) * 100, 6)
    return {
        "start_year": start_year, "end_year": end_year,
        "percentage_change": percentage_change, "cagr": cagr,
    }


def calculate_derived_metrics(history: Iterable[dict]) -> dict:
    rows = list(history)
    return {
        "basis": "Exact calendar-year endpoints relative to the latest observation; no interpolation",
        "five_year": calculate_period_change(rows, 5),
        "ten_year": calculate_period_change(rows, 10),
    }
