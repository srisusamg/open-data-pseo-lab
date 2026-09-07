"""Reusable deterministic insight candidate, selection, and text-rendering layer."""

from __future__ import annotations

from collections import Counter

TYPE_ORDER = {
    "standout_change": 0,
    "largest_percentage_point_change": 1,
    "largest_relative_change": 2,
    "cagr": 3,
    "acceleration": 4,
    "deceleration": 5,
    "direction_summary": 6,
    "scale_change": 7,
    "data_freshness_caveat": 8,
}


def _evidence(metric: dict) -> dict:
    return {
        key: metric[key]
        for key in (
            "start_value", "end_value", "absolute_change", "percent_change", "percentage_point_change",
            "cagr", "actual_start_year", "actual_end_year", "span_years", "direction",
        )
    }


def generate_candidates(metrics: list[dict], config: dict) -> list[dict]:
    """Generate structured claims from derived metrics without producing prose."""
    candidates: list[dict] = []
    percentage_metrics = [metric for metric in metrics if metric["percentage_point_change"] is not None]
    if percentage_metrics:
        metric = max(percentage_metrics, key=lambda item: (abs(item["percentage_point_change"]), item["metric_id"]))
        candidates.append({
            "type": "largest_percentage_point_change", "priority": 90, "entity_id": metric["entity_id"],
            "metric_id": metric["metric_id"], "metric_name": metric["metric_name"], "format": metric["format"],
            "value": metric["percentage_point_change"], "evidence": _evidence(metric),
            "dedupe_key": f"primary-change:{metric['metric_id']}",
        })

    relative = [metric for metric in metrics if metric["format"] != "percentage" and metric["percent_change"] is not None]
    if len(relative) >= 2:
        metric = max(relative, key=lambda item: (abs(item["percent_change"]), item["metric_id"]))
        candidates.append({
            "type": "largest_relative_change", "priority": 85, "entity_id": metric["entity_id"],
            "metric_id": metric["metric_id"], "metric_name": metric["metric_name"], "format": metric["format"],
            "value": metric["percent_change"], "evidence": _evidence(metric),
            "dedupe_key": f"primary-change:{metric['metric_id']}",
        })

    # Percentage indicators are compared in percentage points elsewhere; keep
    # this scale-neutral outlier comparison within non-percentage metrics.
    normalized = [metric for metric in metrics if metric["format"] != "percentage" and metric["percent_change"] is not None]
    ordered = sorted(normalized, key=lambda item: (-abs(item["percent_change"]), item["metric_id"]))
    if len(ordered) >= 3 and abs(ordered[1]["percent_change"]) > 0:
        ratio = abs(ordered[0]["percent_change"]) / abs(ordered[1]["percent_change"])
        if ratio >= config["standout_ratio_threshold"]:
            metric = ordered[0]
            candidates.append({
                "type": "standout_change", "priority": 100, "entity_id": metric["entity_id"],
                "metric_id": metric["metric_id"], "metric_name": metric["metric_name"], "format": metric["format"],
                "value": metric["percent_change"], "ratio_to_next": round(ratio, 6), "evidence": _evidence(metric),
                "dedupe_key": f"primary-change:{metric['metric_id']}",
            })

    for metric in metrics:
        if metric["cagr"] is not None and abs(metric["cagr"]) >= 0.1:
            candidates.append({
                "type": "cagr", "priority": 70, "entity_id": metric["entity_id"], "metric_id": metric["metric_id"],
                "metric_name": metric["metric_name"], "format": metric["format"], "value": metric["cagr"],
                "evidence": _evidence(metric), "dedupe_key": f"cagr:{metric['metric_id']}",
            })
        rates = metric.get("phase_rates")
        if rates:
            earlier, later = rates["earlier_rate"], rates["later_rate"]
            threshold = (
                config["acceleration_percentage_point_rate_threshold"]
                if metric["format"] == "percentage"
                else config["acceleration_relative_rate_threshold"] * max(abs(earlier), 0.1)
            )
            if abs(later - earlier) >= threshold:
                direction = metric["direction"]
                if direction == "increased" and earlier >= 0 and later >= 0:
                    insight_type = "acceleration" if later > earlier else "deceleration"
                elif direction == "declined" and earlier <= 0 and later <= 0:
                    insight_type = "acceleration" if later < earlier else "deceleration"
                else:
                    continue
                candidates.append({
                    "type": insight_type, "priority": 65, "entity_id": metric["entity_id"],
                    "metric_id": metric["metric_id"], "metric_name": metric["metric_name"], "format": metric["format"],
                    "value": round(later - earlier, 6), "phase_rates": rates, "evidence": _evidence(metric),
                    "dedupe_key": f"phase:{metric['metric_id']}",
                })

    counts = Counter(metric["direction"] for metric in metrics)
    if metrics:
        candidates.append({
            "type": "direction_summary", "priority": 60, "entity_id": metrics[0]["entity_id"],
            "metric_id": None, "value": dict(sorted(counts.items())), "metric_count": len(metrics),
            "evidence": {"directions": dict(sorted(counts.items()))}, "dedupe_key": "direction-summary",
        })

    scale_preference = {"population": 0, "gdp": 1, "gdp-per-capita": 2}
    for metric in metrics:
        if metric["metric_slug"] in scale_preference and metric["direction"] != "unchanged":
            candidates.append({
                "type": "scale_change", "priority": 45 - scale_preference[metric["metric_slug"]],
                "entity_id": metric["entity_id"], "metric_id": metric["metric_id"], "metric_name": metric["metric_name"],
                "format": metric["format"], "value": metric["absolute_change"], "evidence": _evidence(metric),
                "dedupe_key": f"scale:{metric['metric_id']}",
            })

    starts = {metric["actual_start_year"] for metric in metrics}
    ends = {metric["actual_end_year"] for metric in metrics}
    if len(starts) > 1 or len(ends) > 1:
        candidates.append({
            "type": "data_freshness_caveat", "priority": 30, "entity_id": metrics[0]["entity_id"],
            "metric_id": None, "value": {"start_years": sorted(starts), "end_years": sorted(ends)},
            "evidence": {"start_years": sorted(starts), "end_years": sorted(ends)}, "dedupe_key": "freshness",
        })
    return sorted(candidates, key=_sort_key)


def _sort_key(candidate: dict) -> tuple:
    return (-candidate["priority"], TYPE_ORDER[candidate["type"]], candidate.get("metric_id") or "")


def select_insights(candidates: list[dict], maximum: int = 6) -> list[dict]:
    """Deduplicate and prefer metric/type diversity with stable ordering."""
    unique: list[dict] = []
    seen_keys: set[str] = set()
    for candidate in sorted(candidates, key=_sort_key):
        if candidate["dedupe_key"] not in seen_keys:
            seen_keys.add(candidate["dedupe_key"])
            unique.append(candidate)
    selected: list[dict] = []
    selected_metrics: set[str] = set()
    selected_types: set[str] = set()
    for candidate in unique:
        metric_id = candidate.get("metric_id")
        if candidate["type"] not in selected_types and (metric_id is None or metric_id not in selected_metrics):
            selected.append(candidate)
            selected_types.add(candidate["type"])
            if metric_id:
                selected_metrics.add(metric_id)
            if len(selected) == maximum:
                return sorted(selected, key=_sort_key)
    for candidate in unique:
        if candidate not in selected:
            selected.append(candidate)
            if len(selected) == maximum:
                break
    return sorted(selected, key=_sort_key)


def _format_value(value: float, style: str) -> str:
    from scripts.model import format_value
    return format_value(value, style)


def render_insight(insight: dict) -> str:
    """Render one selected structured insight using only its evidence."""
    evidence = insight["evidence"]
    name = insight.get("metric_name", "").lower()
    kind = insight["type"]
    if kind == "standout_change":
        direction = "increase" if insight["value"] > 0 else "decline"
        return f"{insight['metric_name']} had the standout relative {direction} among the tracked indicators, changing by {abs(insight['value']):.1f}%."
    if kind == "largest_percentage_point_change":
        return f"{insight['metric_name']} {evidence['direction']} by {abs(insight['value']):.1f} percentage points."
    if kind == "largest_relative_change":
        direction = "increase" if insight["value"] > 0 else "decline"
        return f"{insight['metric_name']} recorded the largest relative {direction} among the tracked non-percentage indicators, changing by {abs(insight['value']):.1f}%."
    if kind == "cagr":
        verb = "grew" if insight["value"] > 0 else "declined"
        return f"{insight['metric_name']} {verb} at an annualized rate of approximately {abs(insight['value']):.1f}% over the observed period."
    if kind in {"acceleration", "deceleration"}:
        pace = "faster" if kind == "acceleration" else "more slowly"
        action = "increased" if evidence["direction"] == "increased" else "declined" if evidence["direction"] == "declined" else "changed"
        return f"{insight['metric_name']} {action} {pace} in the second half of the observed period."
    if kind == "direction_summary":
        counts = evidence["directions"]
        total = insight["metric_count"]
        if counts.get("increased") == total:
            return f"All {total} tracked indicators increased over their observed periods."
        parts = []
        for direction in ("increased", "declined", "unchanged"):
            count = counts.get(direction, 0)
            if count:
                noun = "indicator" if count == 1 else "indicators"
                parts.append(f"{count} tracked {noun} {direction}")
        if len(parts) == 1:
            return parts[0].capitalize() + "."
        return (", while ".join(parts) if len(parts) == 2 else ", ".join(parts[:-1]) + ", while " + parts[-1]) + "."
    if kind == "scale_change":
        return f"{insight['metric_name']} {evidence['direction']} from {_format_value(evidence['start_value'], insight['format'])} to {_format_value(evidence['end_value'], insight['format'])}."
    if kind == "data_freshness_caveat":
        return "The exact start and end observation years vary by indicator and are shown below."
    raise ValueError(f"Unsupported insight type: {kind}")


def render_summary(insights: list[dict]) -> str:
    return " ".join(render_insight(insight) for insight in insights)


def generate_insights(context: dict) -> dict:
    """Small reusable API; future page types can provide their own candidate generator."""
    if context.get("type") != "change":
        raise ValueError(f"Unsupported insight context: {context.get('type')}")
    candidates = generate_candidates(context["metrics"], context["config"])
    selected = select_insights(candidates, context["config"].get("maximum_selected_insights", 6))
    return {"candidates": candidates, "selected": selected, "summary": render_summary(selected)}
