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
    "catalog_scope": 60,
    "value_standout": 70, "cheaper_input": 100, "cheaper_output": 95,
    "larger_context": 90, "performance_leader": 85, "value_leader": 80,
    "ranking_leader": 100, "ranking_spread": 90, "ranking_cluster": 80,
    "ranking_unavailable": 60,
    "cost_performance_frontier": 100,
}
INSIGHT_ORDER = {kind: index for index, kind in enumerate(INSIGHT_SCORES)}

RANKING_DEFINITIONS = {
    "intelligence": {"title": "General intelligence", "kind": "benchmark", "group": "general_intelligence", "direction": "desc"},
    "reasoning": {"title": "Reasoning", "kind": "benchmark", "group": "reasoning", "direction": "desc"},
    "coding": {"title": "Coding", "kind": "benchmark", "group": "coding", "direction": "desc"},
    "speed": {"title": "Throughput", "kind": "operational", "metric": "throughput", "direction": "desc"},
    "latency": {"title": "Latency", "kind": "operational", "metric": "latency", "direction": "asc"},
    "input-cost": {"title": "Input cost", "kind": "price", "field": "input_price_per_million_tokens", "direction": "asc"},
    "output-cost": {"title": "Output cost", "kind": "price", "field": "output_price_per_million_tokens", "direction": "asc"},
    "context": {"title": "Context window", "kind": "model", "field": "context_window_tokens", "direction": "desc"},
    "open-models": {"title": "Open-weight models", "kind": "open", "direction": "none"},
    "value": {"title": "Intelligence per dollar", "kind": "value", "direction": "desc"},
}


def complete_dated_provenance(record: dict) -> bool:
    value = record.get("provenance", record)
    return isinstance(value, dict) and all(value.get(key) not in (None, "") for key in PROVENANCE_FIELDS)


def model_path(model: dict) -> str:
    return f"models/{model['slug']}/"


def provider_path(provider: dict) -> str:
    return f"providers/{provider['slug']}/"


def comparison_path(model_a: dict, model_b: dict) -> str:
    return f"compare/models/{model_a['slug']}/{model_b['slug']}/"


def ranking_path(metric: str) -> str:
    return f"rankings/{metric}/"


def value_ranking_path(workload: str) -> str:
    return f"rankings/value/{workload}/"


def frontier_path() -> str:
    return "rankings/price-performance-frontier/"


def release_path(year: int) -> str:
    return f"models/releases/{year}/"


def order_releases(models: Iterable[dict], year: int) -> list[dict]:
    return sorted(
        (item for item in models if item["release_date"] and item["release_date"].startswith(str(year))),
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


def observation_age_days(observation: dict | None, as_of_date: str) -> int | None:
    if observation is None or not complete_dated_provenance(observation):
        return None
    return (date.fromisoformat(as_of_date) - date.fromisoformat(observation["provenance"]["observation_date"])).days


def observation_is_fresh(observation: dict | None, as_of_date: str, maximum_age_days: int) -> bool:
    age = observation_age_days(observation, as_of_date)
    return age is not None and 0 <= age <= maximum_age_days


def benchmark_groups(benchmarks: Iterable[dict]) -> dict[str, list[dict]]:
    """Group benchmark definitions without merging or averaging their observations."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for benchmark in benchmarks:
        grouped[benchmark["group"]].append(benchmark)
    return {key: sorted(value, key=lambda item: (item["name"], item["version"], item["id"])) for key, value in sorted(grouped.items())}


def normalize_benchmark_score(value: float, method: str | None, *, minimum: float | None = None, maximum: float | None = None) -> float:
    """Apply only an explicitly declared, reproducible normalization method."""
    if method in (None, "none", "identity"):
        return float(value)
    if method == "percent_to_unit_interval":
        return round(float(value) / 100, 12)
    if method == "min_max":
        if minimum is None or maximum is None or maximum <= minimum:
            raise ValueError("min_max normalization requires an increasing minimum and maximum")
        return round((float(value) - minimum) / (maximum - minimum), 12)
    raise ValueError(f"unsupported benchmark normalization method: {method}")


def validate_workload_profiles(profiles: dict[str, dict]) -> None:
    for slug, profile in profiles.items():
        input_share = profile.get("input_share")
        output_share = profile.get("output_share")
        if not isinstance(input_share, (int, float)) or not isinstance(output_share, (int, float)) or abs(input_share + output_share - 1) > 1e-9:
            raise ValueError(f"workload profile {slug} shares must be numeric and sum to 1")
        if int(profile.get("total_tokens", 0)) <= 0 or not profile.get("formula_version"):
            raise ValueError(f"workload profile {slug} requires positive total_tokens and a formula version")


def validate_composite_definitions(composites: Iterable[dict], benchmark_ids: set[str]) -> None:
    """Require every optional composite to publish a reproducible methodology."""
    for composite in composites:
        required = {"id", "version", "included_benchmarks", "weights", "normalization_method"}
        if not required.issubset(composite):
            raise ValueError("composite definitions require id, version, included benchmarks, weights, and normalization method")
        included = composite["included_benchmarks"]
        weights = composite["weights"]
        if not included or set(included) != set(weights) or not set(included).issubset(benchmark_ids):
            raise ValueError(f"composite {composite['id']} has invalid benchmark weights")
        if any(not isinstance(value, (int, float)) or value < 0 for value in weights.values()) or abs(sum(weights.values()) - 1) > 1e-9:
            raise ValueError(f"composite {composite['id']} weights must be non-negative and sum to 1")


def workload_token_counts(profile: dict) -> dict:
    total = int(profile["total_tokens"])
    input_tokens = int(round(total * float(profile["input_share"])))
    return {
        "input_tokens": input_tokens,
        "output_tokens": total - input_tokens,
        "formula_version": profile["formula_version"],
    }


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


def derive_value_metrics(performance: dict, pricing: dict | None, workloads: dict[str, dict], formula: dict, throughput: dict | None = None) -> list[dict]:
    """Return deterministic economics for one benchmark observation, separately per workload."""
    if pricing is None or performance["benchmark_id"] not in formula["included_benchmarks"]:
        return []
    input_price = float(pricing["input_price_per_million_tokens"])
    output_price = float(pricing["output_price_per_million_tokens"])
    score = float(performance["value"])
    rows = []
    for workload_slug, profile in sorted(workloads.items()):
        blend = blended_workload_cost(pricing, workload_token_counts(profile))
        blended_value = blend["value"] if blend else None
        per_blended = score / blended_value if blended_value and blended_value > 0 else None
        speed_adjusted = per_blended * float(throughput["value"]) if per_blended is not None and throughput else None
        rows.append({
            "workload": workload_slug,
            "benchmark_id": performance["benchmark_id"],
            "benchmark_version": performance["benchmark_version"],
            "comparison_group": performance["comparison_group"],
            "evaluation_configuration": performance["evaluation_configuration"],
            "intelligence_per_input_dollar": round(score / input_price, 8) if input_price > 0 else None,
            "intelligence_per_output_dollar": round(score / output_price, 8) if output_price > 0 else None,
            "blended_workload_cost": blend,
            "intelligence_per_blended_dollar": round(per_blended, 8) if per_blended is not None else None,
            "value": round(per_blended, 8) if per_blended is not None else None,
            "speed_adjusted_value": round(speed_adjusted, 8) if speed_adjusted is not None else None,
            "speed_metric": "tokens_per_second" if throughput else None,
            "formula_version": formula["version"],
            "included_benchmarks": list(formula["included_benchmarks"]),
        })
    return rows


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
    operational_by_model: dict[str, list[dict]] = defaultdict(list)
    for item in dataset.get("operational_observations", []):
        operational_by_model[item["model_id"]].append(item)
    workloads = config.get("workload_profiles")
    if workloads is None:
        legacy = config["blended_workload"]
        total = legacy["input_tokens"] + legacy["output_tokens"]
        workloads = {"configured": {"input_share": legacy["input_tokens"] / total, "output_share": legacy["output_tokens"] / total, "total_tokens": total, "formula_version": legacy["formula_version"]}}
    validate_workload_profiles(workloads)
    validate_composite_definitions(config.get("composites", []), {item["id"] for item in dataset["benchmarks"]})
    maximum_price_age = int(config["maximum_pricing_age_days"])
    maximum_benchmark_age = int(config.get("maximum_benchmark_age_days", 365))
    maximum_operational_age = int(config.get("maximum_operational_age_days", 120))
    enriched = []
    for source in dataset["models"]:
        model = dict(source)
        price = latest_pricing(dataset["pricing_observations"], model["id"], config["as_of_date"])
        workload_costs = {slug: blended_workload_cost(price, workload_token_counts(profile)) for slug, profile in sorted(workloads.items())}
        primary_workload = config.get("default_workload_profile", next(iter(workloads)))
        blend = workload_costs[primary_workload]
        performance = sorted(performance_by_model[model["id"]], key=lambda item: item["benchmark_id"])
        operational = sorted(operational_by_model[model["id"]], key=lambda item: (item["metric"], item["comparison_group"]))
        throughput = next((item for item in operational if item["metric"] == "throughput" and observation_is_fresh(item, config["as_of_date"], maximum_operational_age)), None)
        fresh_price = pricing_is_fresh(price, config["as_of_date"], maximum_price_age)
        values = [value for item in performance if fresh_price and observation_is_fresh(item, config["as_of_date"], maximum_benchmark_age) for value in derive_value_metrics(item, price, workloads, config["intelligence_per_dollar"], throughput)]
        fresh_performance = [item for item in performance if observation_is_fresh(item, config["as_of_date"], maximum_benchmark_age)]
        fresh_operational = [item for item in operational if observation_is_fresh(item, config["as_of_date"], maximum_operational_age)]
        model.update({
            "provider": providers[model["provider_id"]], "pricing": price, "blended_cost": blend,
            "workload_costs": workload_costs, "performance": performance, "operational": operational,
            "data_age_days": {
                "pricing": observation_age_days(price, config["as_of_date"]),
                "benchmarks": {item["benchmark_id"]: observation_age_days(item, config["as_of_date"]) for item in performance},
                "operational": {item["metric"]: observation_age_days(item, config["as_of_date"]) for item in operational},
            },
            "value_metrics": values,
            "ranking_eligibility": {
                "input_cost": fresh_price,
                "output_cost": fresh_price,
                "context_window": model["context_window_tokens"] is not None,
                "open_models": model["weights_available"] and "open_weight" in model["distribution_types"],
                "benchmarks": sorted({item["benchmark_id"] for item in fresh_performance}),
                "latency": any(item["metric"] == "latency" for item in fresh_operational),
                "throughput": any(item["metric"] == "throughput" for item in fresh_operational),
                "value_workloads": sorted({item["workload"] for item in values if item["intelligence_per_blended_dollar"] is not None}) if fresh_price else [],
            },
        })
        enriched.append(model)
    return sorted(enriched, key=lambda item: (item["provider"]["name"], item["name"]))


def _rank_rows(rows: list[dict], direction: str) -> list[dict]:
    def cohort(row: dict) -> tuple:
        return tuple(row.get("cohort", ()))
    reverse_value = direction == "desc"
    rows = sorted(rows, key=lambda row: (cohort(row), -row["value"] if reverse_value else row["value"], row["model"]["name"], row["model"]["id"]))
    for row in rows:
        comparable = [other for other in rows if cohort(other) == cohort(row)]
        if direction == "none":
            row["rank"] = 1
        else:
            row["rank"] = 1 + sum(other["value"] > row["value"] if reverse_value else other["value"] < row["value"] for other in comparable)
    return rows


def rank_models(metric: str, models: list[dict], benchmarks: dict[str, dict], config: dict, *, workload: str | None = None) -> list[dict]:
    """Build quality-gated rankings; cohort keys prevent cross-benchmark comparisons."""
    definition = RANKING_DEFINITIONS[metric]
    rows: list[dict] = []
    if definition["kind"] == "price":
        eligibility = metric.replace("-", "_")
        rows = [{"model": model, "value": model["pricing"][definition["field"]], "observed": model["pricing"]["provenance"]["observation_date"], "age_days": observation_age_days(model["pricing"], config["as_of_date"])} for model in models if model["ranking_eligibility"][eligibility]]
    elif definition["kind"] == "model":
        rows = [{"model": model, "value": model[definition["field"]], "observed": model["provenance"]["observation_date"], "age_days": observation_age_days(model, config["as_of_date"])} for model in models if model["ranking_eligibility"]["context_window"]]
    elif definition["kind"] == "open":
        rows = [{"model": model, "value": 1, "display_value": "Verified open weights", "observed": model["provenance"]["observation_date"], "age_days": observation_age_days(model, config["as_of_date"])} for model in models if model["ranking_eligibility"]["open_models"]]
    elif definition["kind"] == "benchmark":
        for model in models:
            for observation in model["performance"]:
                benchmark = benchmarks[observation["benchmark_id"]]
                if observation["benchmark_id"] in model["ranking_eligibility"]["benchmarks"] and benchmark["group"] == definition["group"]:
                    cohort = (observation["benchmark_id"], observation["benchmark_version"], observation["unit"], observation["comparison_group"], observation["evaluation_configuration"])
                    rows.append({"model": model, "value": observation["value"], "unit": observation["unit"], "observation": observation, "cohort": cohort, "cohort_label": f"{observation['benchmark_name']} {observation['benchmark_version']} · {observation['comparison_group']}", "observed": observation["evaluation_date"], "age_days": observation_age_days(observation, config["as_of_date"])})
    elif definition["kind"] == "operational":
        for model in models:
            for observation in model["operational"]:
                if observation["metric"] == definition["metric"] and model["ranking_eligibility"][definition["metric"]]:
                    cohort = (observation["metric"], observation["unit"], observation["comparison_group"], observation["evaluation_configuration"])
                    rows.append({"model": model, "value": observation["value"], "unit": observation["unit"], "observation": observation, "cohort": cohort, "cohort_label": observation["comparison_group"], "observed": observation["provenance"]["observation_date"], "age_days": observation_age_days(observation, config["as_of_date"])})
    elif definition["kind"] == "value":
        profile = workload or config["default_workload_profile"]
        for model in models:
            for value in model["value_metrics"]:
                if value["workload"] == profile and value["intelligence_per_blended_dollar"] is not None and profile in model["ranking_eligibility"]["value_workloads"]:
                    cohort = (value["benchmark_id"], value["benchmark_version"], value["comparison_group"], value["evaluation_configuration"], profile)
                    rows.append({"model": model, "value": value["intelligence_per_blended_dollar"], "unit": "benchmark_points_per_usd", "value_metrics": value, "cohort": cohort, "cohort_label": f"{benchmarks[value['benchmark_id']]['name']} {value['benchmark_version']} · {profile}", "observed": model["pricing"]["provenance"]["observation_date"], "age_days": observation_age_days(model["pricing"], config["as_of_date"])})
    return _rank_rows(rows, definition["direction"])


def pareto_frontier(rows: list[dict]) -> list[dict]:
    """Return non-dominated rows within each explicit comparability cohort."""
    frontier = []
    for row in rows:
        peers = [other for other in rows if tuple(other.get("cohort", ())) == tuple(row.get("cohort", ())) and other is not row]
        dominated = any(
            other["performance"] >= row["performance"] and other["cost"] <= row["cost"]
            and (other["performance"] > row["performance"] or other["cost"] < row["cost"])
            for other in peers
        )
        if not dominated:
            frontier.append({**row, "on_frontier": True})
    return sorted(frontier, key=lambda row: (tuple(row.get("cohort", ())), row["cost"], -row["performance"], row["model"]["name"], row["model"]["id"]))


def price_performance_frontier(models: list[dict], benchmarks: dict[str, dict], config: dict, workload: str | None = None) -> list[dict]:
    profile = workload or config["default_workload_profile"]
    candidates = []
    for model in models:
        for value in model["value_metrics"]:
            if value["workload"] != profile or value["blended_workload_cost"] is None:
                continue
            observation = next((item for item in model["performance"] if item["benchmark_id"] == value["benchmark_id"] and item["comparison_group"] == value["comparison_group"] and item["evaluation_configuration"] == value["evaluation_configuration"]), None)
            if observation is None:
                continue
            benchmark = benchmarks[value["benchmark_id"]]
            performance = observation["value"] if benchmark["higher_is_better"] else -observation["value"]
            candidates.append({"model": model, "performance": performance, "display_performance": observation["value"], "cost": value["blended_workload_cost"]["value"], "benchmark": benchmark, "workload": profile, "cohort": (value["benchmark_id"], value["benchmark_version"], value["comparison_group"], value["evaluation_configuration"], profile), "cohort_label": f"{benchmark['name']} {value['benchmark_version']} · {profile}"})
    return pareto_frontier(candidates)


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
    if kind == "catalog_scope":
        return f"It is cataloged as an {evidence['openness']} model available through {evidence['distribution']}."
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
    if kind == "ranking_unavailable":
        return "No model currently has sufficient fresh, comparable data for this dimension; missing values are not treated as zero."
    if kind == "cost_performance_frontier":
        return f"{evidence['model_count']} model{'s' if evidence['model_count'] != 1 else ''} remain non-dominated across {evidence['cohort_count']} comparable cohort{'s' if evidence['cohort_count'] != 1 else ''} under the {evidence['workload']} workload profile."
    raise ValueError(f"unsupported model insight type: {kind}")


def model_insights(model: dict, models: list[dict], benchmarks: dict[str, dict], as_of_date: str) -> dict:
    candidates = []
    candidates.append(_candidate("model_profile", "catalog_scope", model["id"], model["openness"], {
        "openness": model["openness"], "distribution": ", ".join(value.replace("_", " ") for value in model["distribution_types"]),
    }, metric_id="catalog-taxonomy"))
    priced = sorted((item for item in models if item["blended_cost"] and item["ranking_eligibility"]["input_cost"]), key=lambda item: (item["blended_cost"]["value"], item["name"]))
    if model["blended_cost"] and model["ranking_eligibility"]["input_cost"]:
        position = 1 + sum(item["blended_cost"]["value"] < model["blended_cost"]["value"] for item in priced)
        candidates.append(_candidate("model_profile", "price_position", model["id"], position, {"position": position, "total": len(priced)}, metric_id="blended-cost"))
    contexts = sorted((item for item in models if item["context_window_tokens"] is not None), key=lambda item: (-item["context_window_tokens"], item["name"]))
    if model["context_window_tokens"] is not None:
        position = 1 + sum(item["context_window_tokens"] > model["context_window_tokens"] for item in contexts)
        candidates.append(_candidate("model_profile", "context_position", model["id"], position, {"position": position, "total": len(contexts)}, metric_id="context-window"))
    if model["release_date"]:
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
    if model_a["context_window_tokens"] is not None and model_b["context_window_tokens"] is not None and model_a["context_window_tokens"] != model_b["context_window_tokens"]:
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
            unit = first.get("unit")
            if metric in {"context", "context-window"}:
                return f"{int(value):,} tokens"
            if metric in {"input-cost", "output-cost"}:
                return f"${value:,.2f} per 1M tokens"
            if metric == "latency":
                return f"{value:,.3f} seconds to first token"
            if metric == "speed":
                return f"{value:,.2f} tokens per second"
            if metric == "value":
                return f"{value:,.2f} benchmark points per dollar"
            return f"{value:,.2f} {str(unit or 'points').replace('_', ' ')}"

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
    else:
        candidates.append(_candidate("model_ranking", "ranking_unavailable", metric, None, {"reason": "insufficient_fresh_comparable_data"}, metric_id=metric))
    return run_insight_pipeline(InsightContext("model_ranking", [], subject={"metric": metric}), candidates, INSIGHT_SCORES, INSIGHT_ORDER, _render, maximum=3)


def frontier_insights(rows: list[dict], workload: str) -> dict:
    candidates = []
    if rows:
        candidates.append(_candidate("model_ranking", "cost_performance_frontier", "price-performance-frontier", len(rows), {
            "model_count": len({row["model"]["id"] for row in rows}),
            "cohort_count": len({tuple(row["cohort"]) for row in rows}),
            "workload": workload,
            "model_ids": sorted({row["model"]["id"] for row in rows}),
        }, metric_id="performance-vs-cost"))
    else:
        candidates.append(_candidate("model_ranking", "ranking_unavailable", "price-performance-frontier", None, {"reason": "insufficient_fresh_comparable_data"}, metric_id="performance-vs-cost"))
    return run_insight_pipeline(InsightContext("model_ranking", [], subject={"metric": "price-performance-frontier"}), candidates, INSIGHT_SCORES, INSIGHT_ORDER, _render, maximum=2)
