"""Compatibility adapters for the former comparison-only summary module."""

from __future__ import annotations

from scripts.insights import InsightContext, generate_insights, render_summary as _render_summary


def _context(comparison: dict) -> InsightContext:
    return InsightContext(
        context_type="comparison",
        metrics=comparison["metrics"],
        subject=comparison,
    )


def select_insights(comparison: dict) -> list[dict]:
    """Delegate legacy callers to the shared deterministic insight pipeline."""
    return [_legacy_shape(item) for item in generate_insights(_context(comparison))["selected"]]


def _legacy_shape(insight: dict) -> dict:
    """Keep the former module's return contract without retaining its engine."""
    kind, evidence = insight["type"], insight["evidence"]
    if kind == "metric_leader":
        return {"type": "scale_leaders", "leads": evidence["leads"]}
    if kind == "growth_leader":
        return {"type": kind, "period_years": evidence["period_years"],
                "indicator_name": insight["metric_name"], "leader": evidence["leader"]}
    if kind == "largest_relative_gap":
        return {"type": "biggest_gap", "indicator_name": insight["metric_name"],
                "relative_gap": insight["value"]}
    if kind in {"convergence", "divergence"}:
        return {"type": "gap_change", "indicator_name": insight["metric_name"], **evidence}
    if kind == "observation_year_caveat":
        return {"type": "freshness", "count": evidence["count"]}
    return insight


def _shared_shape(insight: dict) -> dict:
    kind = insight["type"]
    if kind == "scale_leaders":
        return {"type": "metric_leader", "evidence": {"leads": insight["leads"]}}
    if kind == "growth_leader":
        return {"type": kind, "metric_name": insight["indicator_name"],
                "evidence": {"period_years": insight["period_years"], "leader": insight["leader"]}}
    if kind == "biggest_gap":
        return {"type": "largest_relative_gap", "metric_name": insight["indicator_name"],
                "value": insight["relative_gap"], "evidence": {"relative_gap": insight["relative_gap"]}}
    if kind == "gap_change":
        shared_kind = "convergence" if insight["direction"] == "narrowed" else "divergence"
        return {"type": shared_kind, "metric_name": insight["indicator_name"], "evidence": insight}
    if kind == "freshness":
        return {"type": "observation_year_caveat", "evidence": {"count": insight["count"]}}
    return insight


def render_summary(comparison: dict, insights: list[dict] | None = None) -> str:
    """Render through the shared text renderer while preserving the old API."""
    context = _context(comparison)
    if insights is None:
        return generate_insights(context)["summary"]
    return _render_summary([_shared_shape(item) for item in insights], context)
