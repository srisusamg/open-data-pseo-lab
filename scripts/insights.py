"""Shared deterministic insight generation, scoring, selection, and rendering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class InsightContext:
    """The small input boundary shared by deterministic insight recipes."""

    context_type: str
    metrics: list[dict]
    config: Mapping[str, Any] = field(default_factory=dict)
    subject: Mapping[str, Any] = field(default_factory=dict)


TYPE_ORDER = {
    "metric_leader": 0, "standout_change": 1, "growth_leader": 2,
    "largest_percentage_point_change": 3, "largest_relative_gap": 4,
    "largest_relative_change": 5, "convergence": 6, "divergence": 7,
    "cagr": 8, "acceleration": 9, "deceleration": 10,
    "observation_year_caveat": 11, "direction_summary": 12,
    "scale_change": 13, "data_freshness_caveat": 14,
}

SCORES = {
    "change": {
        "standout_change": 100, "largest_percentage_point_change": 90,
        "largest_relative_change": 85, "cagr": 70, "acceleration": 65,
        "deceleration": 65, "direction_summary": 60, "scale_change": 45,
        "data_freshness_caveat": 30,
    },
    "comparison": {
        "metric_leader": 100, "growth_leader": 90,
        "largest_relative_gap": 80,
        # A caveat displaced the fourth substantive claim in the old recipe.
        "observation_year_caveat": 75, "convergence": 70, "divergence": 70,
    },
}


def _context(value: InsightContext | Mapping[str, Any]) -> InsightContext:
    if isinstance(value, InsightContext):
        return value
    # ``type`` remains accepted for callers written before the shared context API.
    context_type = value.get("context_type", value.get("type"))
    return InsightContext(
        context_type=str(context_type or ""), metrics=list(value.get("metrics", [])),
        config=value.get("config", {}),
        subject=value.get("subject", value.get("comparison", {})),
    )


def _candidate(context_type: str, kind: str, *, dedupe_key: str,
               entity_id: str | None = None, metric_id: str | None = None,
               metric_name: str | None = None, value: Any = None,
               evidence: Mapping[str, Any] | None = None, **extra: Any) -> dict:
    """Create the common structured shape used by every insight recipe."""
    return {
        "context_type": context_type, "type": kind, "priority": None,
        "entity_id": entity_id, "metric_id": metric_id,
        "metric_name": metric_name, "value": value,
        "evidence": dict(evidence or {}), "dedupe_key": dedupe_key, **extra,
    }


def _change_evidence(metric: dict) -> dict:
    return {key: metric[key] for key in (
        "start_value", "end_value", "absolute_change", "percent_change",
        "percentage_point_change", "cagr", "actual_start_year",
        "actual_end_year", "span_years", "direction",
    )}


def generate_change_candidates(context: InsightContext) -> list[dict]:
    """Generate unscored What Changed claims from derived metrics."""
    metrics, config = context.metrics, context.config
    candidates: list[dict] = []
    percentage_metrics = [m for m in metrics if m["percentage_point_change"] is not None]
    if percentage_metrics:
        metric = max(percentage_metrics, key=lambda m: (abs(m["percentage_point_change"]), m["metric_id"]))
        candidates.append(_candidate(
            "change", "largest_percentage_point_change", entity_id=metric["entity_id"],
            metric_id=metric["metric_id"], metric_name=metric["metric_name"],
            format=metric["format"], value=metric["percentage_point_change"],
            evidence=_change_evidence(metric), dedupe_key=f"primary-change:{metric['metric_id']}",
        ))

    relative = [m for m in metrics if m["format"] != "percentage" and m["percent_change"] is not None]
    if len(relative) >= 2:
        metric = max(relative, key=lambda m: (abs(m["percent_change"]), m["metric_id"]))
        candidates.append(_candidate(
            "change", "largest_relative_change", entity_id=metric["entity_id"],
            metric_id=metric["metric_id"], metric_name=metric["metric_name"],
            format=metric["format"], value=metric["percent_change"],
            evidence=_change_evidence(metric), dedupe_key=f"primary-change:{metric['metric_id']}",
        ))

    ordered = sorted(relative, key=lambda m: (-abs(m["percent_change"]), m["metric_id"]))
    if len(ordered) >= 3 and abs(ordered[1]["percent_change"]) > 0:
        ratio = abs(ordered[0]["percent_change"]) / abs(ordered[1]["percent_change"])
        if ratio >= config["standout_ratio_threshold"]:
            metric = ordered[0]
            candidates.append(_candidate(
                "change", "standout_change", entity_id=metric["entity_id"],
                metric_id=metric["metric_id"], metric_name=metric["metric_name"],
                format=metric["format"], value=metric["percent_change"],
                ratio_to_next=round(ratio, 6), evidence=_change_evidence(metric),
                dedupe_key=f"primary-change:{metric['metric_id']}",
            ))

    for metric in metrics:
        if metric["cagr"] is not None and abs(metric["cagr"]) >= 0.1:
            candidates.append(_candidate(
                "change", "cagr", entity_id=metric["entity_id"],
                metric_id=metric["metric_id"], metric_name=metric["metric_name"],
                format=metric["format"], value=metric["cagr"],
                evidence=_change_evidence(metric), dedupe_key=f"cagr:{metric['metric_id']}",
            ))
        rates = metric.get("phase_rates")
        if rates:
            earlier, later = rates["earlier_rate"], rates["later_rate"]
            threshold = (config["acceleration_percentage_point_rate_threshold"]
                         if metric["format"] == "percentage"
                         else config["acceleration_relative_rate_threshold"] * max(abs(earlier), 0.1))
            if abs(later - earlier) >= threshold:
                direction = metric["direction"]
                if direction == "increased" and earlier >= 0 and later >= 0:
                    kind = "acceleration" if later > earlier else "deceleration"
                elif direction == "declined" and earlier <= 0 and later <= 0:
                    kind = "acceleration" if later < earlier else "deceleration"
                else:
                    continue
                candidates.append(_candidate(
                    "change", kind, entity_id=metric["entity_id"],
                    metric_id=metric["metric_id"], metric_name=metric["metric_name"],
                    format=metric["format"], value=round(later - earlier, 6),
                    phase_rates=rates, evidence=_change_evidence(metric),
                    dedupe_key=f"phase:{metric['metric_id']}",
                ))

    counts = Counter(metric["direction"] for metric in metrics)
    if metrics:
        directions = dict(sorted(counts.items()))
        candidates.append(_candidate(
            "change", "direction_summary", entity_id=metrics[0]["entity_id"],
            value=directions, metric_count=len(metrics), evidence={"directions": directions},
            dedupe_key="direction-summary",
        ))

    scale_preference = {"population": 0, "gdp": 1, "gdp-per-capita": 2}
    for metric in metrics:
        if metric["metric_slug"] in scale_preference and metric["direction"] != "unchanged":
            candidates.append(_candidate(
                "change", "scale_change", entity_id=metric["entity_id"],
                metric_id=metric["metric_id"], metric_name=metric["metric_name"],
                format=metric["format"], value=metric["absolute_change"],
                score_offset=-scale_preference[metric["metric_slug"]],
                evidence=_change_evidence(metric), dedupe_key=f"scale:{metric['metric_id']}",
            ))

    starts = {metric["actual_start_year"] for metric in metrics}
    ends = {metric["actual_end_year"] for metric in metrics}
    if len(starts) > 1 or len(ends) > 1:
        years = {"start_years": sorted(starts), "end_years": sorted(ends)}
        candidates.append(_candidate(
            "change", "data_freshness_caveat", entity_id=metrics[0]["entity_id"],
            value=years, evidence=years, dedupe_key="freshness",
        ))
    return candidates


def _comparison_id(comparison: Mapping[str, Any]) -> str | None:
    if not comparison:
        return None
    a, b = comparison.get("country_a", {}), comparison.get("country_b", {})
    return f"{a.get('code', '')}:{b.get('code', '')}"


def generate_comparison_candidates(context: InsightContext) -> list[dict]:
    """Generate unscored comparison claims from comparison-derived metrics."""
    comparison, candidates = context.subject, []
    entity_id = _comparison_id(comparison)
    metrics_by_slug = {metric["indicator_slug"]: metric for metric in context.metrics}
    leads = []
    for slug in ("population", "gdp", "gdp-per-capita", "internet-users"):
        metric = metrics_by_slug.get(slug)
        if metric and metric["leader"]:
            leads.append({"indicator_name": metric["indicator_name"],
                          "leader": metric["leader"]["country_name"]})
    if leads:
        shown = leads[:2]
        candidates.append(_candidate(
            "comparison", "metric_leader", entity_id=entity_id, value=shown,
            evidence={"leads": shown}, dedupe_key="metric-leaders",
        ))

    growth = []
    for metric in context.metrics:
        period = metric["periods"]["ten_year"]
        if period["growth_leader"]:
            gap = abs(period["country_a"]["percentage_change"] - period["country_b"]["percentage_change"])
            growth.append((gap, metric, period))
    if growth:
        _, metric, period = max(growth, key=lambda item: (item[0], item[1]["indicator_slug"]))
        evidence = {"period_years": 10, "leader": period["growth_leader"]["country_name"]}
        candidates.append(_candidate(
            "comparison", "growth_leader", entity_id=entity_id,
            metric_id=metric["indicator_code"], metric_name=metric["indicator_name"],
            value=evidence["leader"], evidence=evidence,
            dedupe_key=f"growth:{metric['indicator_code']}",
        ))

    gaps = [metric for metric in context.metrics if metric["relative_gap"] is not None]
    if gaps:
        metric = max(gaps, key=lambda item: (item["relative_gap"], item["indicator_slug"]))
        candidates.append(_candidate(
            "comparison", "largest_relative_gap", entity_id=entity_id,
            metric_id=metric["indicator_code"], metric_name=metric["indicator_name"],
            value=metric["relative_gap"], evidence={"relative_gap": metric["relative_gap"]},
            dedupe_key=f"relative-gap:{metric['indicator_code']}",
        ))

    changing = [m for m in context.metrics if m["gap_change"] and m["gap_change"]["direction"] != "unchanged"]
    if changing:
        metric = max(changing, key=lambda m: abs(m["gap_change"]["end_relative_gap"] - m["gap_change"]["start_relative_gap"]))
        gap = metric["gap_change"]
        kind = "convergence" if gap["direction"] == "narrowed" else "divergence"
        candidates.append(_candidate(
            "comparison", kind, entity_id=entity_id, metric_id=metric["indicator_code"],
            metric_name=metric["indicator_name"],
            value=gap["end_relative_gap"] - gap["start_relative_gap"], evidence=gap,
            dedupe_key=f"gap-change:{metric['indicator_code']}",
        ))

    mismatches = [metric for metric in context.metrics if metric["temporally_imperfect"]]
    if mismatches:
        candidates.append(_candidate(
            "comparison", "observation_year_caveat", entity_id=entity_id,
            value=len(mismatches), evidence={"count": len(mismatches)},
            dedupe_key="freshness",
        ))
    return candidates


def score_candidates(candidates: list[dict], context_type: str) -> list[dict]:
    """Assign explicit recipe scores without changing candidate evidence."""
    if context_type not in SCORES:
        raise ValueError(f"Unsupported insight context: {context_type}")
    scored = []
    for candidate in candidates:
        item = dict(candidate)
        item["priority"] = SCORES[context_type][item["type"]] + item.pop("score_offset", 0)
        scored.append(item)
    return sorted(scored, key=_sort_key)


def _sort_key(candidate: dict) -> tuple:
    return (-candidate["priority"], TYPE_ORDER[candidate["type"]], candidate.get("metric_id") or "")


def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    """Keep the highest-scoring deterministic candidate for each claim key."""
    unique, seen = [], set()
    for candidate in sorted(candidates, key=_sort_key):
        if candidate["dedupe_key"] not in seen:
            seen.add(candidate["dedupe_key"])
            unique.append(candidate)
    return unique


def select_insights(candidates: list[dict], maximum: int = 6,
                    *, prefer_metric_diversity: bool = True) -> list[dict]:
    """Select stable, diverse insights from already-scored candidates."""
    unique = deduplicate_candidates(candidates)
    if not prefer_metric_diversity:
        return unique[:maximum]
    selected, selected_metrics, selected_types = [], set(), set()
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


def _join_leads(leads: list[dict]) -> str:
    if len(leads) == 2 and leads[0]["leader"] == leads[1]["leader"]:
        return f"{leads[0]['leader']} has the higher latest {leads[0]['indicator_name'].lower()} and {leads[1]['indicator_name'].lower()} values"
    phrases = [f"{lead['leader']} has the higher latest {lead['indicator_name'].lower()} value" for lead in leads]
    return phrases[0] if len(phrases) == 1 else f"{phrases[0]}, while {phrases[1]}"


def render_insight(insight: dict) -> str:
    """Render one selected structured insight using only its evidence."""
    evidence, kind = insight["evidence"], insight["type"]
    if kind == "metric_leader":
        return _join_leads(evidence["leads"]) + " among the latest available observations."
    if kind == "growth_leader":
        return f"Over the last {evidence['period_years']} years of exact observations, {evidence['leader']}'s {insight['metric_name'].lower()} had the larger percentage change."
    if kind == "largest_relative_gap":
        return f"Among the available indicators, {insight['metric_name'].lower()} has the largest scale-neutral relative gap, at {insight['value']:.1f}%."
    if kind in {"convergence", "divergence"}:
        return f"The relative {insight['metric_name'].lower()} gap {evidence['direction']} from {evidence['start_year']} to {evidence['end_year']}."
    if kind == "observation_year_caveat":
        count = evidence["count"]
        noun = "indicator uses" if count == 1 else "indicators use"
        return f"The comparison is temporally imperfect because {count} {noun} latest observations from different years; each year is shown in the tables."
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
        counts, total = evidence["directions"], insight["metric_count"]
        if counts.get("increased") == total:
            return f"All {total} tracked indicators increased over their observed periods."
        parts = []
        for direction in ("increased", "declined", "unchanged"):
            count = counts.get(direction, 0)
            if count:
                parts.append(f"{count} tracked {'indicator' if count == 1 else 'indicators'} {direction}")
        if len(parts) == 1:
            return parts[0].capitalize() + "."
        return (", while ".join(parts) if len(parts) == 2 else ", ".join(parts[:-1]) + ", while " + parts[-1]) + "."
    if kind == "scale_change":
        return f"{insight['metric_name']} {evidence['direction']} from {_format_value(evidence['start_value'], insight['format'])} to {_format_value(evidence['end_value'], insight['format'])}."
    if kind == "data_freshness_caveat":
        return "The exact start and end observation years vary by indicator and are shown below."
    raise ValueError(f"Unsupported insight type: {kind}")


def render_summary(insights: list[dict],
                   context: InsightContext | Mapping[str, Any] | None = None) -> str:
    sentences = [render_insight(insight) for insight in insights]
    normalized = _context(context) if context is not None else None
    if normalized and normalized.context_type == "comparison" and len(sentences) < 2:
        a = normalized.subject["country_a"]["name"]
        b = normalized.subject["country_b"]["name"]
        sentences.append(f"Available values for {a} and {b} are shown with their actual observation years and are not interpolated.")
    if normalized and normalized.context_type == "comparison":
        sentences = sentences[:5]
    return " ".join(sentences)


def generate_insights(context: InsightContext | Mapping[str, Any]) -> dict:
    """Run derived facts through generation, scoring, dedupe, selection, and rendering."""
    normalized = _context(context)
    generators = {"change": generate_change_candidates,
                  "comparison": generate_comparison_candidates}
    if normalized.context_type not in generators:
        raise ValueError(f"Unsupported insight context: {normalized.context_type}")
    raw = generators[normalized.context_type](normalized)
    candidates = score_candidates(raw, normalized.context_type)
    maximum = int(normalized.config.get(
        "maximum_selected_insights", 6 if normalized.context_type == "change" else 4))
    selected = select_insights(
        candidates, maximum,
        prefer_metric_diversity=normalized.context_type == "change",
    )
    return {"candidates": candidates, "selected": selected,
            "summary": render_summary(selected, normalized)}


def generate_candidates(metrics: list[dict], config: Mapping[str, Any]) -> list[dict]:
    """Backward-compatible scored What Changed candidate API."""
    context = InsightContext("change", metrics, config)
    return score_candidates(generate_change_candidates(context), "change")
