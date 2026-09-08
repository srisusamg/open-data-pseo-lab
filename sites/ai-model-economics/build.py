"""Build the AI Model Economics site from the curated provider adapter."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from platform.core.configuration import SitePaths, load_json
from platform.core.quality import duplicate_intents, evaluate_page_quality, quality_report_row
from platform.core.rendering import template_environment, write_text
from platform.core.urls import canonical_url, relative_url
from platform.providers.ai_models.curated import SCHEMA_VERSION, load_catalog
from platform.providers.ai_models.normalizer import normalize_catalog
from platform.recipes.model_economics import (
    benchmark_data_is_compatible, comparison_insights, comparison_path, comparable_performance,
    complete_dated_provenance, enrich_models, frontier_insights, frontier_path, model_insights, model_path,
    order_releases, price_performance_frontier, pricing_is_fresh, provider_path, rank_models,
    ranking_insights, ranking_path, relative_price_difference, release_path, RANKING_DEFINITIONS,
    value_ranking_path,
)

GENERATOR_VERSION = "3.0.0"


def _evaluated(context: dict) -> tuple[dict, dict]:
    result = evaluate_page_quality(context)
    return result, quality_report_row(context, result)


def _load_comparisons(path: Path, models: dict[str, dict]) -> list[tuple[dict, dict]]:
    configured = load_json(path)
    resolved, seen = [], set()
    for index, pair in enumerate(configured, 1):
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
            raise ValueError(f"comparison {index} must be a two-item model-id list")
        if pair[0] == pair[1]:
            raise ValueError(f"comparison {index} cannot compare a model with itself")
        missing = [item for item in pair if item not in models]
        if missing:
            raise ValueError(f"comparison {index} references unknown model(s): {', '.join(missing)}")
        key = frozenset(pair)
        if key in seen:
            raise ValueError(f"comparison {index} duplicates a configured pair, including reversed order")
        seen.add(key)
        resolved.append((models[pair[0]], models[pair[1]]))
    return resolved


def _ranking(metric: str, models: list[dict]) -> list[dict]:
    """Backward-compatible adapter for the original three ranking tests."""
    canonical = "context" if metric == "context-window" else metric
    if canonical not in {"input-cost", "output-cost", "context"}:
        raise ValueError(f"unknown legacy ranking metric: {metric}")
    definition = RANKING_DEFINITIONS[canonical]
    if canonical == "context":
        rows = [{"model": item, "value": item[definition["field"]]} for item in models if item["ranking_eligibility"]["context_window"]]
    else:
        key = canonical.replace("-", "_")
        rows = [{"model": item, "value": item["pricing"][definition["field"]]} for item in models if item["ranking_eligibility"][key] and item.get("pricing")]
    descending = definition["direction"] == "desc"
    rows.sort(key=lambda row: (-row["value"] if descending else row["value"], row["model"]["name"], row["model"]["id"]))
    for row in rows:
        row["rank"] = 1 + sum(other["value"] > row["value"] if descending else other["value"] < row["value"] for other in rows)
    return rows


def render_site(paths: SitePaths) -> int:
    config = load_json(paths.config / "site.json")
    base_url = config.get("base_url", "")
    if not base_url.startswith("https://") or not base_url.endswith("/"):
        raise ValueError("site base_url must be an https URL ending in '/'")
    catalog = load_catalog(paths.config / "catalog.json")
    dataset = normalize_catalog(catalog)
    models = enrich_models(dataset, config)
    models_by_id = {item["id"]: item for item in models}
    providers_by_id = {item["id"]: item for item in dataset["providers"]}
    benchmarks_by_id = {item["id"]: item for item in dataset["benchmarks"]}
    configured_pairs = _load_comparisons(paths.config / "comparisons.json", models_by_id)
    as_of_year = int(config["as_of_date"][:4])

    output = paths.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    env = template_environment(paths.templates)
    env.filters.update(money=lambda value: f"${float(value):,.2f}", tokens=lambda value: f"{int(value):,}")

    permanent_urls = {"", "methodology/"}
    model_urls = {item["id"]: model_path(item) for item in models}
    provider_urls = {item["id"]: provider_path(item) for item in dataset["providers"]}
    ranking_urls = {metric: ranking_path(metric) for metric in RANKING_DEFINITIONS}
    workload_ranking_urls = {slug: value_ranking_path(slug) for slug in config["workload_profiles"]}
    price_frontier_url = frontier_path()
    years = sorted({int(item["release_date"][:4]) for item in models if item["release_date"]}, reverse=True)
    release_urls = {year: release_path(year) for year in years}
    all_base_urls = permanent_urls | set(model_urls.values()) | set(provider_urls.values()) | set(ranking_urls.values()) | set(workload_ranking_urls.values()) | {price_frontier_url} | set(release_urls.values())

    model_results: dict[str, tuple[dict, dict, dict]] = {}
    model_intents = duplicate_intents([f"model:{item['id']}" for item in models])
    for model in models:
        path = model_urls[model["id"]]
        insights = model_insights(model, models, benchmarks_by_id, config["as_of_date"])
        pricing = model["pricing"]
        taxonomy_fields = (
            "provider_id", "family", "release_date", "status", "distribution_types", "openness",
            "weights_available", "reasoning_capability", "multimodal_capability", "tool_use_capability",
            "coding_capability", "api_available", "product_available",
        )
        facts = sum(model.get(key) is not None for key in taxonomy_fields)
        facts += int(model["context_window_tokens"] is not None) + (3 if pricing else 0) + len(model["performance"])
        years_used = [int(model["provenance"]["observation_date"][:4])]
        if pricing:
            years_used.append(int(pricing["provenance"]["observation_date"][:4]))
        years_used.extend(int(item["provenance"]["observation_date"][:4]) for item in model["performance"])
        context = {
            "url": path, "page_type": "model_profile", "as_of_year": as_of_year,
            "usable_facts": facts, "usable_historical_metrics": 0,
            "insight_candidate_count": len(insights["candidates"]), "selected_insight_count": len(insights["selected"]),
            "source_years": years_used,
            "provenance_complete": complete_dated_provenance(model) and all(complete_dated_provenance(value) for value in model["fact_provenance"].values()) and (pricing is None or complete_dated_provenance(pricing)) and all(complete_dated_provenance(item) for item in model["performance"]),
            "differentiated_content_count": facts, "duplicate_intent": f"model:{model['id']}" in model_intents,
            "required_internal_links": [provider_urls[model["provider_id"]], "methodology/"], "available_internal_links": all_base_urls,
            "canonical_url": canonical_url(base_url, path), "expected_canonical_url": canonical_url(base_url, path),
            "unsupported_calculations": 0, "policy_overrides": {"minimum_usable_facts": 6, "minimum_insight_candidates": 1, "minimum_selected_insights": 1},
        }
        result, report = _evaluated(context)
        model_results[path] = (result, report, insights)

    eligible_models = [item for item in models if model_results[model_urls[item["id"]]][0]["status"] == "generated"]
    available_urls = permanent_urls | {model_urls[item["id"]] for item in eligible_models} | set(provider_urls.values()) | set(ranking_urls.values()) | set(workload_ranking_urls.values()) | {price_frontier_url} | set(release_urls.values())
    quality_reports = [model_results[model_urls[item["id"]]][1] for item in models]

    providers = []
    provider_reports = []
    for provider in dataset["providers"]:
        provider_models = [item for item in eligible_models if item["provider_id"] == provider["id"]]
        path = provider_urls[provider["id"]]
        context = {
            "url": path, "page_type": "provider_profile", "as_of_year": as_of_year,
            "usable_facts": len(provider_models), "usable_historical_metrics": 0,
            "insight_candidate_count": 0, "selected_insight_count": 0,
            "source_years": [int(item["provenance"]["observation_date"][:4]) for item in provider_models],
            "provenance_complete": complete_dated_provenance(provider) and bool(provider_models) and all(complete_dated_provenance(item) for item in provider_models),
            "differentiated_content_count": len(provider_models), "duplicate_intent": False,
            "required_internal_links": ["methodology/"] + [model_urls[item["id"]] for item in provider_models], "available_internal_links": available_urls,
            "canonical_url": canonical_url(base_url, path), "expected_canonical_url": canonical_url(base_url, path), "unsupported_calculations": 0,
        }
        result, report = _evaluated(context)
        provider_reports.append(report)
        if result["status"] == "generated":
            providers.append({**provider, "models": provider_models, "path": path})
    quality_reports.extend(provider_reports)

    rankings = []
    ranking_specs = [(metric, path, None) for metric, path in ranking_urls.items()]
    ranking_specs += [("value", path, workload) for workload, path in workload_ranking_urls.items()]
    for metric, path, workload in ranking_specs:
        rows = rank_models(metric, eligible_models, benchmarks_by_id, config, workload=workload)
        insights = ranking_insights(metric, rows)
        source_years = [int(row["observed"][:4]) for row in rows]
        evidence_rows = [row.get("observation") or (row["model"]["pricing"] if metric in {"input-cost", "output-cost", "value"} else row["model"]) for row in rows]
        context = {
            "url": path, "page_type": "model_ranking", "as_of_year": as_of_year,
            "usable_facts": len(rows), "usable_historical_metrics": 0,
            "insight_candidate_count": len(insights["candidates"]), "selected_insight_count": len(insights["selected"]),
            "source_years": source_years or [as_of_year], "provenance_complete": all(complete_dated_provenance(item) for item in evidence_rows),
            "differentiated_content_count": len({row["value"] for row in rows}), "duplicate_intent": False,
            "required_internal_links": ["methodology/"] + [model_urls[row["model"]["id"]] for row in rows], "available_internal_links": available_urls,
            "canonical_url": canonical_url(base_url, path), "expected_canonical_url": canonical_url(base_url, path), "unsupported_calculations": 0,
            "policy_overrides": {"minimum_usable_facts": 0, "minimum_differentiated_content": 0, "minimum_insight_candidates": 0, "minimum_selected_insights": 0, "minimum_required_internal_links": 1},
        }
        result, report = _evaluated(context)
        quality_reports.append(report)
        if result["status"] == "generated":
            rankings.append({"metric": metric, "title": RANKING_DEFINITIONS[metric]["title"], "path": path, "rows": rows, "insights": insights, "workload": workload, "definition": RANKING_DEFINITIONS[metric]})

    frontier_rows = price_performance_frontier(eligible_models, benchmarks_by_id, config)
    frontier_insight_result = frontier_insights(frontier_rows, config["default_workload_profile"])
    frontier = {"metric": "price-performance-frontier", "title": "Price-performance frontier", "path": price_frontier_url, "rows": frontier_rows, "insights": frontier_insight_result, "workload": config["default_workload_profile"], "definition": {"kind": "frontier", "direction": "none"}}
    frontier_context = {
        "url": price_frontier_url, "page_type": "model_ranking", "as_of_year": as_of_year,
        "usable_facts": len(frontier_rows), "usable_historical_metrics": 0,
        "insight_candidate_count": len(frontier_insight_result["candidates"]), "selected_insight_count": len(frontier_insight_result["selected"]),
        "source_years": [as_of_year], "provenance_complete": True,
        "differentiated_content_count": len(frontier_rows), "duplicate_intent": False,
        "required_internal_links": ["methodology/"] + [model_urls[row["model"]["id"]] for row in frontier_rows], "available_internal_links": available_urls,
        "canonical_url": canonical_url(base_url, price_frontier_url), "expected_canonical_url": canonical_url(base_url, price_frontier_url), "unsupported_calculations": 0,
        "policy_overrides": {"minimum_usable_facts": 0, "minimum_differentiated_content": 0, "minimum_insight_candidates": 0, "minimum_selected_insights": 0, "minimum_required_internal_links": 1},
    }
    frontier_result, frontier_report = _evaluated(frontier_context)
    quality_reports.append(frontier_report)

    comparisons = []
    comparison_intents = duplicate_intents(["comparison:" + ":".join(sorted((a["id"], b["id"]))) for a, b in configured_pairs])
    for model_a, model_b in configured_pairs:
        path = comparison_path(model_a, model_b)
        performance_pairs = comparable_performance(model_a["id"], model_b["id"], dataset["performance_observations"])
        fresh = all(pricing_is_fresh(model["pricing"], config["as_of_date"], int(config["maximum_pricing_age_days"])) for model in (model_a, model_b))
        benchmarks_compatible = benchmark_data_is_compatible(model_a["id"], model_b["id"], dataset["performance_observations"])
        comparable = bool(model_a["pricing"] and model_b["pricing"] and fresh and benchmarks_compatible)
        insights = comparison_insights(model_a, model_b, performance_pairs, benchmarks_by_id) if comparable else {"candidates": [], "selected": [], "summary": ""}
        derived = {
            "input_price_difference_percent_a_vs_b": relative_price_difference(model_a["pricing"]["input_price_per_million_tokens"], model_b["pricing"]["input_price_per_million_tokens"]) if comparable else None,
            "output_price_difference_percent_a_vs_b": relative_price_difference(model_a["pricing"]["output_price_per_million_tokens"], model_b["pricing"]["output_price_per_million_tokens"]) if comparable else None,
            "blended_cost_difference_percent_a_vs_b": relative_price_difference(model_a["blended_cost"]["value"], model_b["blended_cost"]["value"]) if comparable else None,
        }
        facts = 6 + len(performance_pairs) * 2 if comparable else 0
        context = {
            "url": path, "page_type": "model_comparison", "as_of_year": as_of_year,
            "usable_facts": facts, "usable_historical_metrics": 0,
            "insight_candidate_count": len(insights["candidates"]), "selected_insight_count": len(insights["selected"]),
            "source_years": [int(item["pricing"]["provenance"]["observation_date"][:4]) for item in (model_a, model_b)] if comparable else [],
            "provenance_complete": comparable and all(complete_dated_provenance(item) for pair in performance_pairs for item in pair),
            "differentiated_content_count": sum(value not in (None, 0) for value in derived.values()) + int(model_a["context_window_tokens"] is not None and model_b["context_window_tokens"] is not None and model_a["context_window_tokens"] != model_b["context_window_tokens"]),
            "duplicate_intent": "comparison:" + ":".join(sorted((model_a["id"], model_b["id"]))) in comparison_intents,
            "required_internal_links": [model_urls[model_a["id"]], model_urls[model_b["id"]], "methodology/"], "available_internal_links": available_urls,
            "canonical_url": canonical_url(base_url, path), "expected_canonical_url": canonical_url(base_url, path), "unsupported_calculations": 0,
        }
        result, report = _evaluated(context)
        quality_reports.append(report)
        if result["status"] == "generated":
            comparisons.append({"model_a": model_a, "model_b": model_b, "path": path, "performance_pairs": performance_pairs, "derived": derived, "insights": insights})

    releases = []
    for year in years:
        year_models = order_releases(eligible_models, year)
        path = release_urls[year]
        context = {
            "url": path, "page_type": "release_timeline", "as_of_year": as_of_year,
            "usable_facts": len(year_models), "usable_historical_metrics": 0, "insight_candidate_count": 0, "selected_insight_count": 0,
            "source_years": [year] * len(year_models), "provenance_complete": bool(year_models) and all(complete_dated_provenance(item) for item in year_models),
            "differentiated_content_count": len({item["release_date"] for item in year_models}), "duplicate_intent": False,
            "required_internal_links": ["methodology/"] + [model_urls[item["id"]] for item in year_models], "available_internal_links": available_urls,
            "canonical_url": canonical_url(base_url, path), "expected_canonical_url": canonical_url(base_url, path), "unsupported_calculations": 0,
        }
        result, report = _evaluated(context)
        quality_reports.append(report)
        if result["status"] == "generated":
            releases.append({"year": year, "models": year_models, "path": path})

    providers_by_model = defaultdict(list)
    for comparison in comparisons:
        providers_by_model[comparison["model_a"]["id"]].append(comparison)
        providers_by_model[comparison["model_b"]["id"]].append(comparison)
    page_paths = [""] + [model_urls[item["id"]] for item in eligible_models] + [item["path"] for item in providers] + [item["path"] for item in rankings] + [price_frontier_url] + [item["path"] for item in comparisons] + [item["path"] for item in releases] + ["methodology/"]
    common = {
        "site": config, "models": eligible_models, "providers": providers, "rankings": rankings,
        "comparisons": comparisons, "releases": releases, "frontier": frontier, "retrieved_at": dataset["retrieved_at"],
        "canonical_url": canonical_url,
        "families": sorted({item["family"] for item in eligible_models}),
    }

    def render(template: str, page_path: str, destination: Path, **context: object) -> None:
        html = env.get_template(template).render(**common, page_path=page_path, link=lambda target: relative_url(page_path, target), **context)
        write_text(destination, html)

    render("home.html", "", output / "index.html")
    for model in eligible_models:
        path = model_urls[model["id"]]
        render("model.html", path, output / path / "index.html", model=model, insights=model_results[path][2], model_comparisons=providers_by_model[model["id"]], benchmarks_by_id=benchmarks_by_id)
    for provider in providers:
        render("provider.html", provider["path"], output / provider["path"] / "index.html", provider=provider)
    for ranking in rankings:
        render("ranking.html", ranking["path"], output / ranking["path"] / "index.html", ranking=ranking)
    render("frontier.html", frontier["path"], output / frontier["path"] / "index.html", ranking=frontier)
    for comparison in comparisons:
        render("comparison.html", comparison["path"], output / comparison["path"] / "index.html", comparison=comparison, benchmarks_by_id=benchmarks_by_id)
    for release in releases:
        render("releases.html", release["path"], output / release["path"] / "index.html", release=release)
    render("methodology.html", "methodology/", output / "methodology" / "index.html", benchmarks=dataset["benchmarks"])
    shutil.copy2(paths.static / "styles.css", output / "styles.css")
    write_text(output / ".nojekyll", "")
    write_text(output / "sitemap.xml", env.get_template("sitemap.xml").render(site=config, page_paths=page_paths, canonical_url=canonical_url))
    write_text(output / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {canonical_url(base_url, 'sitemap.xml')}")

    paths.generated_data.mkdir(parents=True, exist_ok=True)
    write_text(paths.generated_data / "normalized_model_data.json", json.dumps(dataset, indent=2))
    write_text(paths.generated_data / "page_quality_report.json", json.dumps(quality_reports, indent=2))
    write_text(paths.generated_data / "generated_urls.json", json.dumps([canonical_url(base_url, path) for path in page_paths], indent=2))
    derived_output = {
        "as_of_date": config["as_of_date"],
        "formulas": {
            "workload_profiles": config["workload_profiles"],
            "intelligence_per_dollar": config["intelligence_per_dollar"],
            "relative_price_difference": {"version": "relative-price-difference-v1", "formula": "(model_a_price - model_b_price) / model_b_price * 100"},
        },
        "models": [{
            "model_id": item["id"], "pricing": item["pricing"], "workload_costs": item["workload_costs"],
            "value_metrics": item["value_metrics"], "ranking_eligibility": item["ranking_eligibility"],
        } for item in eligible_models],
        "comparisons": [{
            "path": item["path"], "model_a_id": item["model_a"]["id"], "model_b_id": item["model_b"]["id"],
            "relative_price_differences": item["derived"],
            "comparable_benchmarks": [pair[0]["benchmark_id"] for pair in item["performance_pairs"]],
        } for item in comparisons],
        "rankings": [{
            "metric": item["metric"], "workload": item["workload"],
            "rows": [{"rank": row["rank"], "model_id": row["model"]["id"], "value": row["value"], "cohort": list(row.get("cohort", ())), "age_days": row.get("age_days")} for row in item["rows"]],
        } for item in rankings],
        "price_performance_frontier": [{"model_id": row["model"]["id"], "performance": row["display_performance"], "cost": row["cost"], "cohort": list(row["cohort"]), "workload": row["workload"]} for row in frontier_rows],
    }
    write_text(paths.generated_data / "derived_model_economics.json", json.dumps(derived_output, indent=2))
    example_models = [models_by_id[item] for item in ("openai:gpt-5.6-sol", "openai:gpt-5.6-luna", "google:gemini-3.8-flash")]
    insight_examples = [
        {"url": canonical_url(base_url, model_urls[item["id"]]), "summary": model_results[model_urls[item["id"]]][2]["summary"]}
        for item in example_models if item in eligible_models
    ] + [{"url": canonical_url(base_url, item["path"]), "summary": item["insights"]["summary"]} for item in comparisons[:2]]
    write_text(paths.generated_data / "insight_examples.json", json.dumps(insight_examples, indent=2))
    manifest = {
        "build_timestamp": dataset["retrieved_at"], "generator_version": GENERATOR_VERSION, "schema_version": SCHEMA_VERSION,
        "provider_count": len(providers), "model_count": len(eligible_models), "comparison_count": len(comparisons),
        "ranking_count": len(rankings) + 1, "release_timeline_count": len(releases), "generated_page_count": len(page_paths),
        "quality_generated_count": sum(item["status"] == "generated" for item in quality_reports),
        "quality_skipped_count": sum(item["status"] == "skipped" for item in quality_reports),
    }
    write_text(paths.generated_data / "build_manifest.json", json.dumps(manifest, indent=2))
    return len(page_paths)
