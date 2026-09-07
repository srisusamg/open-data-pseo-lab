"""Reusable, deterministic publication eligibility for generated page recipes.

The evaluator consumes facts prepared by the build pipeline and never renders HTML.
Common validation lives here; page-type thresholds stay in ``PAGE_POLICIES``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

from platform.core.provenance import complete_provenance


@dataclass(frozen=True)
class PagePolicy:
    minimum_usable_facts: int
    minimum_historical_metrics: int
    maximum_source_age_years: int
    minimum_differentiated_content: int
    minimum_insight_candidates: int = 0
    minimum_selected_insights: int = 0
    minimum_required_internal_links: int = 2


PAGE_POLICIES = {
    "country_profile": PagePolicy(3, 3, 3, 3, minimum_required_internal_links=2),
    "indicator_ranking": PagePolicy(3, 0, 3, 2, minimum_required_internal_links=2),
    "comparison": PagePolicy(3, 2, 3, 2, 2, 2, 3),
    "what_changed": PagePolicy(3, 3, 3, 3, 3, 3, 3),
}


def valid_canonical_url(url: str, expected_url: str) -> bool:
    """Require the one deterministic HTTPS canonical, without query or fragment."""
    parsed = urlparse(url)
    return bool(url == expected_url and parsed.scheme == "https" and parsed.netloc and not parsed.query and not parsed.fragment and parsed.path.endswith("/"))


def duplicate_intents(intent_keys: list[str]) -> set[str]:
    """Identify duplicated semantic intents independently of their URL ordering."""
    counts = Counter(intent_keys)
    return {key for key, count in counts.items() if count > 1}


def source_freshness(source_years: list[int], as_of_year: int, maximum_age: int) -> dict:
    valid_years = [year for year in source_years if isinstance(year, int)]
    ages = [max(0, as_of_year - year) for year in valid_years]
    return {
        "as_of_year": as_of_year,
        "newest_source_year": max(valid_years, default=None),
        "oldest_source_year": min(valid_years, default=None),
        "maximum_age_years": max(ages, default=None),
        "allowed_age_years": maximum_age,
        "stale_fact_count": sum(age > maximum_age for age in ages),
    }


def _add_check(checks: list[dict], name: str, passed: bool, reason: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "reason": None if passed else reason})


def evaluate_page_quality(page_context: dict) -> dict:
    """Evaluate a potential page using common checks and its page-type policy."""
    page_type = page_context["page_type"]
    if page_type not in PAGE_POLICIES:
        raise ValueError(f"unknown page type: {page_type}")
    policy = PAGE_POLICIES[page_type]
    overrides = page_context.get("policy_overrides", {})
    policy = PagePolicy(**{**policy.__dict__, **overrides})

    facts = int(page_context.get("usable_facts", 0))
    historical = int(page_context.get("usable_historical_metrics", 0))
    candidates = int(page_context.get("insight_candidate_count", 0))
    selected = int(page_context.get("selected_insight_count", 0))
    differentiated = int(page_context.get("differentiated_content_count", 0))
    required_links = list(dict.fromkeys(page_context.get("required_internal_links", [])))
    available_links = set(page_context.get("available_internal_links", []))
    missing_links = sorted(link for link in required_links if link not in available_links)
    freshness = source_freshness(page_context.get("source_years", []), int(page_context["as_of_year"]), policy.maximum_source_age_years)

    checks: list[dict] = []
    _add_check(checks, "minimum_usable_facts", facts >= policy.minimum_usable_facts, f"usable facts {facts} below required {policy.minimum_usable_facts}")
    _add_check(checks, "minimum_historical_coverage", historical >= policy.minimum_historical_metrics, f"usable historical metrics {historical} below required {policy.minimum_historical_metrics}")
    _add_check(checks, "provenance_completeness", bool(page_context.get("provenance_complete")), "source provenance is incomplete")
    _add_check(checks, "source_freshness", bool(page_context.get("source_years")) and freshness["stale_fact_count"] == 0, "one or more source facts are stale or undated")
    _add_check(checks, "differentiated_content", differentiated >= policy.minimum_differentiated_content, f"differentiated content {differentiated} below required {policy.minimum_differentiated_content}")
    _add_check(checks, "minimum_insight_candidates", candidates >= policy.minimum_insight_candidates, f"insight candidates {candidates} below required {policy.minimum_insight_candidates}")
    _add_check(checks, "minimum_selected_insights", selected >= policy.minimum_selected_insights, f"selected insights {selected} below required {policy.minimum_selected_insights}")
    _add_check(checks, "unique_page_intent", not page_context.get("duplicate_intent", False), "page intent duplicates another potential page")
    _add_check(checks, "required_internal_links", len(required_links) >= policy.minimum_required_internal_links and not missing_links, "required internal links are missing or target ineligible pages")
    _add_check(checks, "valid_canonical_url", valid_canonical_url(page_context.get("canonical_url", ""), page_context.get("expected_canonical_url", "")), "canonical URL is invalid or non-deterministic")
    unsupported = int(page_context.get("unsupported_calculations", 0))
    _add_check(checks, "supported_calculations", unsupported == 0, f"found {unsupported} unsupported or unverifiable calculations")

    reasons = [check["reason"] for check in checks if not check["passed"]]
    score = round(sum(check["passed"] for check in checks) / len(checks) * 100)
    metrics = {
        "usable_facts": facts,
        "usable_historical_metrics": historical,
        "insight_candidate_count": candidates,
        "selected_insight_count": selected,
        "differentiated_content_count": differentiated,
        "source_freshness": freshness,
        "required_internal_link_count": len(required_links),
        "missing_internal_links": missing_links,
        "unsupported_calculation_count": unsupported,
        "checks": checks,
    }
    return {"status": "generated" if not reasons else "skipped", "score": score, "reasons": reasons, "metrics": metrics}


def quality_report_row(page_context: dict, result: dict) -> dict:
    """Flatten stable report fields while retaining detailed diagnostics."""
    metrics = result["metrics"]
    return {
        "url": page_context["url"], "page_type": page_context["page_type"], "status": result["status"],
        "quality_score": result["score"], "usable_facts": metrics["usable_facts"],
        "usable_historical_metrics": metrics["usable_historical_metrics"],
        "insight_candidate_count": metrics["insight_candidate_count"],
        "selected_insight_count": metrics["selected_insight_count"],
        "source_freshness": metrics["source_freshness"], "skip_reasons": result["reasons"], "metrics": metrics,
    }


def change_page_skip_reason(metrics: list[dict], insight_result: dict, config: dict) -> str | None:
    """Backward-compatible adapter for callers of the original narrow gate."""
    if len(metrics) < int(config["minimum_usable_metrics"]):
        return "fewer than the configured minimum usable metrics"
    if len(insight_result["candidates"]) < int(config["minimum_insight_candidates"]):
        return "fewer than the configured minimum worthwhile insight candidates"
    if len(insight_result["selected"]) < int(config["minimum_selected_insights"]):
        return "fewer than the configured minimum selected insights"
    if any(not metric.get("source_url") or len(metric.get("source_facts", [])) != 2 for metric in metrics):
        return "missing valid provenance"
    return None
