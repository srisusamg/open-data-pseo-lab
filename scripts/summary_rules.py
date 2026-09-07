"""Select structured comparison insights and render neutral deterministic prose."""

from __future__ import annotations

SCALE_INDICATORS = ("population", "gdp", "gdp-per-capita", "internet-users")


def select_insights(comparison: dict) -> list[dict]:
    """Choose up to four informative facts without inventing missing comparisons."""
    metrics = {metric["indicator_slug"]: metric for metric in comparison["metrics"]}
    insights: list[dict] = []

    scale_leads = []
    for slug in SCALE_INDICATORS:
        metric = metrics.get(slug)
        if metric and metric["leader"]:
            scale_leads.append({"indicator_name": metric["indicator_name"], "leader": metric["leader"]["country_name"]})
    if scale_leads:
        insights.append({"type": "scale_leaders", "leads": scale_leads[:2]})

    growth_candidates = []
    for metric in comparison["metrics"]:
        period = metric["periods"]["ten_year"]
        if period["growth_leader"]:
            gap = abs(period["country_a"]["percentage_change"] - period["country_b"]["percentage_change"])
            growth_candidates.append((gap, metric, period))
    if growth_candidates:
        _, metric, period = max(growth_candidates, key=lambda item: (item[0], item[1]["indicator_slug"]))
        insights.append({
            "type": "growth_leader", "period_years": 10, "indicator_name": metric["indicator_name"],
            "leader": period["growth_leader"]["country_name"],
        })

    gaps = [metric for metric in comparison["metrics"] if metric["relative_gap"] is not None]
    if gaps:
        biggest = max(gaps, key=lambda metric: (metric["relative_gap"], metric["indicator_slug"]))
        insights.append({"type": "biggest_gap", "indicator_name": biggest["indicator_name"], "relative_gap": biggest["relative_gap"]})

    gap_changes = [metric for metric in comparison["metrics"] if metric["gap_change"] and metric["gap_change"]["direction"] != "unchanged"]
    if gap_changes:
        metric = max(gap_changes, key=lambda item: abs(item["gap_change"]["end_relative_gap"] - item["gap_change"]["start_relative_gap"]))
        insights.append({"type": "gap_change", "indicator_name": metric["indicator_name"], **metric["gap_change"]})

    mismatches = [metric for metric in comparison["metrics"] if metric["temporally_imperfect"]]
    if mismatches:
        freshness = {"type": "freshness", "count": len(mismatches)}
        return insights[:3] + [freshness]
    return insights[:4]


def _join_leads(leads: list[dict]) -> str:
    if len(leads) == 2 and leads[0]["leader"] == leads[1]["leader"]:
        return f"{leads[0]['leader']} has the higher latest {leads[0]['indicator_name'].lower()} and {leads[1]['indicator_name'].lower()} values"
    phrases = [f"{lead['leader']} has the higher latest {lead['indicator_name'].lower()} value" for lead in leads]
    return phrases[0] if len(phrases) == 1 else f"{phrases[0]}, while {phrases[1]}"


def render_summary(comparison: dict, insights: list[dict] | None = None) -> str:
    insights = select_insights(comparison) if insights is None else insights
    sentences = []
    for insight in insights:
        if insight["type"] == "scale_leaders":
            sentences.append(_join_leads(insight["leads"]) + " among the latest available observations.")
        elif insight["type"] == "growth_leader":
            sentences.append(f"Over the last {insight['period_years']} years of exact observations, {insight['leader']}'s {insight['indicator_name'].lower()} had the larger percentage change.")
        elif insight["type"] == "biggest_gap":
            sentences.append(f"Among the available indicators, {insight['indicator_name'].lower()} has the largest scale-neutral relative gap, at {insight['relative_gap']:.1f}%.")
        elif insight["type"] == "gap_change":
            sentences.append(f"The relative {insight['indicator_name'].lower()} gap {insight['direction']} from {insight['start_year']} to {insight['end_year']}.")
        elif insight["type"] == "freshness":
            noun = "indicator uses" if insight["count"] == 1 else "indicators use"
            sentences.append(f"The comparison is temporally imperfect because {insight['count']} {noun} latest observations from different years; each year is shown in the tables.")
    if len(sentences) < 2:
        a = comparison["country_a"]["name"]
        b = comparison["country_b"]["name"]
        sentences.append(f"Available values for {a} and {b} are shown with their actual observation years and are not interpolated.")
    return " ".join(sentences[:5])
