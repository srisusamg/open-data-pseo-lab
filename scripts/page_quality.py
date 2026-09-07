"""Deterministic publication gates for generated page recipes."""

from __future__ import annotations


def change_page_skip_reason(metrics: list[dict], insight_result: dict, config: dict) -> str | None:
    if len(metrics) < int(config["minimum_usable_metrics"]):
        return "fewer than the configured minimum usable metrics"
    if len(insight_result["candidates"]) < int(config["minimum_insight_candidates"]):
        return "fewer than the configured minimum worthwhile insight candidates"
    if len(insight_result["selected"]) < int(config["minimum_selected_insights"]):
        return "fewer than the configured minimum selected insights"
    if any(not metric.get("source_url") or len(metric.get("source_facts", [])) != 2 for metric in metrics):
        return "missing valid provenance"
    return None
