"""Provider-neutral recipes for AI model economics pages and insights."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from platform.core.insights import InsightContext, run_insight_pipeline

PROVENANCE_FIELDS = (
    "source_name", "source_url", "source_metric_id", "observation_date",
    "effective_date", "retrieved_at", "source_type", "confidence", "status",
)

INSIGHT_SCORES = {
    "price_position": 100, "context_position": 90, "release_recency": 80,
    "value_standout": 70, "cheaper_input": 100, "cheaper_output": 95,
    "larger_context": 90, "performance_leader": 85, "value_leader": 80,
    "ranking_leader": 100, "ranking_spread": 90, "ranking_cluster": 80,
}
INSIGHT_ORDER = {kind: index for index, kind in enumerate(INSIGHT_SCORES)}


def complete_dated_provenance(record: dict) -> bool:
    value = record.get("provenance")
    return isinstance(value, dict) and all(value.get(key) not in (None, "") for key in PROVENANCE_FIELDS)


def model_path(model: dict) -> str:
    return f"models/{model['slug']}/"


def provider_path(provider: dict) -> str:
    return f"providers/{provider['slug']}/"


def comparison_path(model_a: dict, model_b: dict) -> str:
    return f"compare/models/{model_a['slug']}/{model_b['slug']}/"


def ranking_path(metric: str) -> str:
    return f"models/rankings/{metric}/"


def release_path(year: int) -> str:
    return f"models/releases/{year}/"


def order_releases(models: Iterable[dict], year: int) -> list[dict]:
    return sorted(
        (item for item in models if item["release_date"].startswith(str(year))),
        key=lambda item: (-date.fromisoformat(item["release_date"]).toordinal(), item["name"]),
    )


def latest_pricing(observations: Iterable[dict], model_id: str, as_of_date: str) -> dict | None:
    eligible = [
        item for item in observations
        if item["model_id"] == model_id and item["provenance"]["effective_date"] <= as_of_date
    ]
    return max(eligible, key=lambda item: (item["provenance"]["effective_date"], item["provenance"]["retrieved_at"]), default=None)


def pricing_is_fresh(pricing: dict | None, as_of_date: str, maximum_age_days: int) -> bool:
    if pricing is None or not complete_dated_provenance(pricing):
        return False
    age = (date.fromisoformat(as_of_date) - date.fromisoformat(pricing["provenance"]["observation_date"])).days
    return 0 <= age <= maximum_age_days


def blended_workload_cost(pricing: dict | None, workload: dict) -> dict | None:
    if pricing is None:
        return None
    input_tokens = int(workload["input_tokens"])
    output_tokens = int(workload["output_tokens"])
    if input_tokens < 0 or output_tokens < 0 or input_tokens + output_tokens == 0:
        raise ValueError("blended workload token counts must be non-negative and non-zero in total")
    input_cost = pricing["input_price_per_million_tokens"] * input_tokens / 1_000_000
    output_cost = pricing["output_price_per_million_tokens"] * output_tokens / 1_000_000
    return {
        "value": round(input_cost + output_cost, 8), "currency": "USD",
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "formula_version": workload["formula_version"],
        "formula": "input_price_per_1m * input_tokens / 1m + output_price_per_1m * output_tokens / 1m",
    }


def relative_price_difference(value_a: float, value_b: float) -> float | None:
    """Return A versus B using B as the explicit, reproducible baseline."""
    if value_b == 0:
        return None
    return round((value_a - value_b) / value_b * 100, 6)


def intelligence_per_dollar(performance: dict, blended_cost: dict, formula: dict) -> dict | None:
    if not performance or not blended_cost or blended_cost["value"] <= 0:
        return None
    if performance["benchmark_id"] not in formula["included_benchmarks"]:
        return None
    return {
        "value": round(float(performance["value"]) / blended_cost["value"], 8),
        "benchmark_id": performance["benchmark_id"],
        "benchmark_value": performance["value"],
        "formula_version": formula["version"],
        "formula": "benchmark_score / configured_blended_workload_cost_usd",
        "included_benchmarks": list(formula["included_benchmarks"]),
        "comparison_group": performance["comparison_group"],
    }


def comparable_performance(model_a_id: str, model_b_id: str, observations: Iterable[dict]) -> list[tuple[dict, dict]]:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for item in observations:
        by_model[item["model_id"]].append(item)
    pairs = []
    for left in by_model[model_a_id]:
        for right in by_model[model_b_id]:
            if (
                left["benchmark_id"] == right["benchmark_id"]
                and left["unit"] == right["unit"]
                and left["comparison_group"] == right["comparison_group"]
                and left["evaluation_configuration"] == right["evaluation_configuration"]
                and complete_dated_provenance(left) and complete_dated_provenance(right)
            ):
                pairs.append((left, right))
    return sorted(pairs, key=lambda pair: pair[0]["benchmark_id"])


def benchmark_data_is_compatible(model_a_id: str, model_b_id: str, observations: Iterable[dict]) -> bool:
    """Reject a pair when both models have benchmark data but none aligns."""
    rows = list(observations)
    left = any(item["model_id"] == model_a_id for item in rows)
    right = any(item["model_id"] == model_b_id for item in rows)
    return not (left and right) or bool(comparable_performance(model_a_id, model_b_id, rows))


def enrich_models(dataset: dict, config: dict) -> list[dict]:
    providers = {item["id"]: item for item in dataset["providers"]}
    performance_by_model: dict[str, list[dict]] = defaultdict(list)
    for item in dataset["performance_observations"]:
        performance_by_model[item["model_id"]].append(item)
    enriched = []
    for source in dataset["models"]:
        model = dict(source)
        price = latest_pricing(dataset["pricing_observations"], model["id"], config["as_of_date"])
        blend = blended_workload_cost(price, config["blended_workload"])
        performance = sorted(performance_by_model[model["id"]], key=lambda item: item["benchmark_id"])
        values = [intelligence_per_dollar(item, blend, config["intelligence_per_dollar"]) for item in performance]
        model.update({
            "provider": providers[model["provider_id"]], "pricing": price, "blended_cost": blend,
            "performance": performance, "value_metrics": [item for item in values if item],
        })
        enriched.append(model)
    return sorted(enriched, key=lambda item: (item["provider"]["name"], item["name"]))


def _candidate(context_type: str, kind: str, subject_id: str, value: object, evidence: dict, *, metric_id: str | None = None, dedupe_key: str | None = None) -> dict:
    return {
        "context_type": context_type, "type": kind, "priority": None,
        "entity_id": subject_id, "metric_id": metric_id, "metric_name": metric_id,
        "value": value, "evidence": evidence, "dedupe_key": dedupe_key or kind,
    }


def _ordinal(position: int) -> str:
    suffix = "th" if 10 <= position % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    return f"{position}{suffix}"


def _render(insight: dict) -> str:
    evidence, kind = insight["evidence"], insight["type"]
    if kind == "price_position":
        return f"Its configured blended workload cost ranks {_ordinal(evidence['position'])} lowest among {evidence['total']} models with current pricing."
    if kind == "context_position":
        return f"Its context window ranks {_ordinal(evidence['position'])} largest among {evidence['total']} eligible models."
    if kind == "release_recency":
        return f"It was released {evidence['days']} days before this catalog's {evidence['as_of_date']} as-of date."
    if kind == "value_standout":
        return f"On {evidence['benchmark_name']}, its versioned intelligence-per-dollar value ranks {_ordinal(evidence['position'])} within a {evidence['total']}-model comparable cohort."
    if kind in {"cheaper_input", "cheaper_output"}:
        label = "input" if kind == "cheaper_input" else "output"
        return f"{evidence['leader']} has the lower {label} token price (${evidence['low']:.2f} versus ${evidence['high']:.2f} per 1M tokens)."
    if kind == "larger_context":
        return f"{evidence['leader']} has the larger context window ({evidence['large']:,} versus {evidence['small']:,} tokens)."
    if kind == "performance_leader":
        return f"{evidence['leader']} has the higher {evidence['benchmark_name']} result within the shared {evidence['comparison_group']} evaluation configuration."
    if kind == "value_leader":
        return f"{evidence['leader']} has the higher versioned intelligence-per-dollar result for {evidence['benchmark_name']} under the configured workload."
    if kind == "ranking_leader":
        return f"{evidence['leader']} ranks first at {evidence['formatted_value']}."
    if kind == "ranking_spread":
        return f"The eligible range runs from {evidence['low']} to {evidence['high']}, a spread of {evidence['spread']}."
    if kind == "ranking_cluster":
        return f"{', '.join(evidence['models'])} share the same ranked value at {evidence['formatted_value']}."
    raise ValueError(f"unsupported model insight type: {kind}")


def model_insights(model: dict, models: list[dict], benchmarks: dict[str, dict], as_of_date: str) -> dict:
    candidates = []
    priced = sorted((item for item in models if item["blended_cost"]), key=lambda item: (item["blended_cost"]["value"], item["name"]))
    if model["blended_cost"]:
        position = 1 + sum(item["blended_cost"]["value"] < model["blended_cost"]["value"] for item in priced)
        candidates.append(_candidate("model_profile", "price_position", model["id"], position, {"position": position, "total": len(priced)}, metric_id="blended-cost"))
    contexts = sorted(models, key=lambda item: (-item["context_window_tokens"], item["name"]))
    position = 1 + sum(item["context_window_tokens"] > model["context_window_tokens"] for item in contexts)
    candidates.append(_candidate("model_profile", "context_position", model["id"], position, {"position": position, "total": len(contexts)}, metric_id="context-window"))
    days = (date.fromisoformat(as_of_date) - date.fromisoformat(model["release_date"])).days
    candidates.append(_candidate("model_profile", "release_recency", model["id"], days, {"days": days, "as_of_date": as_of_date}, metric_id="release-date"))
    for metric in model["value_metrics"]:
        cohort = [
            (item, value) for item in models for value in item["value_metrics"]
            if value["benchmark_id"] == metric["benchmark_id"] and value["comparison_group"] == metric["comparison_group"]
        ]
        ordered = sorted(cohort, key=lambda pair: (-pair[1]["value"], pair[0]["name"]))
        position = 1 + sum(pair[1]["value"] > metric["value"] for pair in ordered)
        candidates.append(_candidate("model_profile", "value_standout", model["id"], metric["value"], {
            "position": position, "total": len(ordered), "benchmark_name": benchmarks[metric["benchmark_id"]]["name"],
        }, metric_id=metric["benchmark_id"], dedupe_key=f"value:{metric['benchmark_id']}"))
    return run_insight_pipeline(InsightContext("model_profile", [], subject=model), candidates, INSIGHT_SCORES, INSIGHT_ORDER, _render, maximum=4, prefer_metric_diversity=True)


def comparison_insights(model_a: dict, model_b: dict, performance_pairs: list[tuple[dict, dict]], benchmarks: dict[str, dict]) -> dict:
    candidates = []
    for field, kind in (("input_price_per_million_tokens", "cheaper_input"), ("output_price_per_million_tokens", "cheaper_output")):
        a, b = model_a["pricing"][field], model_b["pricing"][field]
        if a != b:
            leader, low, high = (model_a, a, b) if a < b else (model_b, b, a)
            candidates.append(_candidate("model_comparison", kind, f"{model_a['id']}:{model_b['id']}", low, {"leader": leader["name"], "low": low, "high": high}, metric_id=field))
    if model_a["context_window_tokens"] != model_b["context_window_tokens"]:
        leader, other = (model_a, model_b) if model_a["context_window_tokens"] > model_b["context_window_tokens"] else (model_b, model_a)
        candidates.append(_candidate("model_comparison", "larger_context", f"{model_a['id']}:{model_b['id']}", leader["context_window_tokens"], {
            "leader": leader["name"], "large": leader["context_window_tokens"], "small": other["context_window_tokens"],
        }, metric_id="context-window"))
    for left, right in performance_pairs:
        benchmark = benchmarks[left["benchmark_id"]]
        if left["value"] != right["value"]:
            leader = model_a if (left["value"] > right["value"]) == benchmark["higher_is_better"] else model_b
            candidates.append(_candidate("model_comparison", "performance_leader", f"{model_a['id']}:{model_b['id']}", max(left["value"], right["value"]), {
                "leader": leader["name"], "benchmark_name": benchmark["name"], "comparison_group": left["comparison_group"],
            }, metric_id=left["benchmark_id"], dedupe_key=f"performance:{left['benchmark_id']}"))
        value_a = next((item for item in model_a["value_metrics"] if item["benchmark_id"] == left["benchmark_id"] and item["comparison_group"] == left["comparison_group"]), None)
        value_b = next((item for item in model_b["value_metrics"] if item["benchmark_id"] == right["benchmark_id"] and item["comparison_group"] == right["comparison_group"]), None)
        if value_a and value_b and value_a["value"] != value_b["value"]:
            leader = model_a if value_a["value"] > value_b["value"] else model_b
            candidates.append(_candidate("model_comparison", "value_leader", f"{model_a['id']}:{model_b['id']}", max(value_a["value"], value_b["value"]), {
                "leader": leader["name"], "benchmark_name": benchmark["name"],
            }, metric_id=f"value:{left['benchmark_id']}", dedupe_key=f"value:{left['benchmark_id']}"))
    return run_insight_pipeline(InsightContext("model_comparison", [], subject={"model_a": model_a, "model_b": model_b}), candidates, INSIGHT_SCORES, INSIGHT_ORDER, _render, maximum=5, prefer_metric_diversity=True)


def ranking_insights(metric: str, rows: list[dict]) -> dict:
    candidates = []
    if rows:
        first, low_row, high_row = rows[0], min(rows, key=lambda row: row["value"]), max(rows, key=lambda row: row["value"])
        def formatted(value: float) -> str:
            return f"{int(value):,} tokens" if metric == "context-window" else f"${value:,.2f} per 1M tokens"

        candidates.append(_candidate("model_ranking", "ranking_leader", metric, first["value"], {"leader": first["model"]["name"], "formatted_value": formatted(first["value"])}, metric_id=metric))
        difference = high_row["value"] - low_row["value"]
        candidates.append(_candidate("model_ranking", "ranking_spread", metric, difference, {
            "low": formatted(low_row["value"]), "high": formatted(high_row["value"]), "spread": formatted(difference),
        }, metric_id=f"{metric}:spread"))
        groups: dict[float, list[str]] = defaultdict(list)
        for row in rows:
            groups[row["value"]].append(row["model"]["name"])
        clusters = [(value, names) for value, names in groups.items() if len(names) >= 2]
        if clusters:
            value, names = sorted(clusters, key=lambda item: (-len(item[1]), item[0], item[1]))[0]
            candidates.append(_candidate("model_ranking", "ranking_cluster", metric, value, {"models": names, "formatted_value": formatted(value)}, metric_id=f"{metric}:cluster"))
    return run_insight_pipeline(InsightContext("model_ranking", [], subject={"metric": metric}), candidates, INSIGHT_SCORES, INSIGHT_ORDER, _render, maximum=3)
