"""Build a configured site from provider-normalized data and reusable recipes."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform.core.configuration import SitePaths, load_comparisons, load_json, load_site_config
from platform.core.facts import series_value
from platform.core.insights import InsightContext, generate_insights
from platform.core.quality import duplicate_intents, evaluate_page_quality, quality_report_row
from platform.core.rendering import template_environment, write_text
from platform.core.urls import canonical_url, relative_url
from platform.recipes.change import change_path, derive_change_metric
from platform.recipes.comparison import build_comparison
from platform.recipes.profile import prepare_profile, profile_path
from platform.recipes.ranking import prepare_ranking, ranking_path

GENERATOR_VERSION = "4.0.0"


def _close(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-6)


def _unsupported_comparison_calculations(metrics: list[dict]) -> int:
    invalid = 0
    for metric in metrics:
        a, b = metric.get("entity_a"), metric.get("entity_b")
        if not a or not b:
            invalid += any(metric.get(key) is not None for key in ("absolute_difference", "percentage_difference", "leader"))
            continue
        expected_absolute = float(a["value"]) - float(b["value"])
        expected_percentage = None if float(b["value"]) == 0 else expected_absolute / abs(float(b["value"])) * 100
        invalid += not _close(metric.get("absolute_difference"), expected_absolute)
        invalid += not _close(metric.get("percentage_difference"), expected_percentage)
    return int(invalid)


def _unsupported_change_calculations(metrics: list[dict]) -> int:
    invalid = 0
    for metric in metrics:
        start, end, span = float(metric["start_value"]), float(metric["end_value"]), int(metric["span_years"])
        difference = end - start
        percent = None if start == 0 else difference / abs(start) * 100
        cagr = ((end / start) ** (1 / span) - 1) * 100 if start > 0 and end > 0 else None
        invalid += not _close(metric.get("absolute_change"), difference)
        invalid += not _close(metric.get("percent_change"), percent)
        invalid += not _close(metric.get("cagr"), cagr)
        expected_points = difference if metric.get("format") == "percentage" else None
        invalid += not _close(metric.get("percentage_point_change"), expected_points)
    return int(invalid)


def _evaluated(context: dict) -> tuple[dict, dict]:
    result = evaluate_page_quality(context)
    return result, quality_report_row(context, result)


def render_site(
    snapshot: dict, paths: SitePaths,
    snapshot_normalizer: Callable[[dict, list[dict], list[dict]], dict],
    schema_version: str,
) -> int:
    site_config, source_entities, source_metrics = load_site_config(paths)
    dataset = snapshot_normalizer(snapshot, source_entities, source_metrics)
    configured_entities = dataset["entities"]
    configured_metrics = dataset["metrics"]
    configured_pairs = load_comparisons(paths, configured_entities)
    change_config = load_json(paths.config / "change_windows.json")
    output = paths.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    env = template_environment(paths.templates)

    series = [series_value(item) for item in dataset["series"]]
    series_by_key = {(item["entity_id"], item["metric_id"]): item for item in series}
    as_of_year = int(snapshot["retrieved_at"][:4])
    permanent_urls = {"", "methodology/"}
    country_urls = {entity["id"]: profile_path(entity) for entity in configured_entities}
    indicator_urls = {metric["id"]: ranking_path(metric) for metric in configured_metrics}
    country_duplicates = duplicate_intents([f"country:{entity['id']}" for entity in configured_entities])
    indicator_duplicates = duplicate_intents([f"indicator:{metric['id']}" for metric in configured_metrics])

    # Country and indicator pages depend on one another. Resolve their eligibility
    # to a fixed point so neither can link to a page removed by the other.
    available_base = permanent_urls | set(country_urls.values()) | set(indicator_urls.values())
    base_results: dict[str, tuple[dict, dict, dict]] = {}
    for _ in range(len(available_base) + 1):
        current: dict[str, tuple[dict, dict, dict]] = {}
        for entity in configured_entities:
            path = country_urls[entity["id"]]
            context, view = prepare_profile(
                entity,
                [series_by_key[(entity["id"], metric["id"])] for metric in configured_metrics],
                path=path, as_of_year=as_of_year, base_url=site_config["base_url"],
                metric_urls=indicator_urls, available_urls=available_base,
                duplicate_intent=f"country:{entity['id']}" in country_duplicates,
            )
            result, report = _evaluated(context)
            current[path] = (result, report, view)
        for metric in configured_metrics:
            path = indicator_urls[metric["id"]]
            context, view = prepare_ranking(
                metric,
                [series_by_key[(entity["id"], metric["id"])] for entity in configured_entities],
                path=path, as_of_year=as_of_year, base_url=site_config["base_url"],
                entity_urls=country_urls, available_urls=available_base,
                duplicate_intent=f"indicator:{metric['id']}" in indicator_duplicates,
            )
            result, report = _evaluated(context)
            current[path] = (result, report, view)
        next_available = permanent_urls | {path for path, (result, _, _) in current.items() if result["status"] == "generated"}
        base_results = current
        if next_available == available_base:
            break
        available_base = next_available

    countries = [entity for entity in configured_entities if base_results[country_urls[entity["id"]]][0]["status"] == "generated"]
    indicators = [metric for metric in configured_metrics if base_results[indicator_urls[metric["id"]]][0]["status"] == "generated"]
    available_urls = permanent_urls | {country_urls[item["id"]] for item in countries} | {indicator_urls[item["id"]] for item in indicators}

    comparisons: list[dict] = []
    comparison_reports: list[dict] = []
    comparison_intents = ["comparison:" + ":".join(sorted((a["id"], b["id"]))) for a, b in configured_pairs]
    duplicate_comparisons = duplicate_intents(comparison_intents)
    for entity_a, entity_b in configured_pairs:
        comparison = build_comparison(
            entity_a, entity_b,
            [series_by_key[(entity_a["id"], metric["id"])] for metric in indicators],
            [series_by_key[(entity_b["id"], metric["id"])] for metric in indicators],
        )
        insight_result = generate_insights(InsightContext(
            context_type="comparison", metrics=comparison["metrics"], subject=comparison,
        ))
        comparison["insight_candidates"] = insight_result["candidates"]
        comparison["selected_insights"] = insight_result["selected"]
        comparison["summary"] = insight_result["summary"]
        usable = [metric for metric in comparison["metrics"] if metric.get("entity_a") and metric.get("entity_b")]
        historical = sum(any(period["entity_a"] and period["entity_b"] for period in metric["periods"].values()) for metric in usable)
        key = "comparison:" + ":".join(sorted((entity_a["id"], entity_b["id"])))
        context = {
            "url": comparison["path"], "page_type": "comparison", "as_of_year": as_of_year,
            "usable_facts": len(usable), "usable_historical_metrics": historical,
            "insight_candidate_count": len(insight_result["candidates"]),
            "selected_insight_count": len(insight_result["selected"]),
            "source_years": [fact["year"] for metric in usable for fact in (metric["entity_a"], metric["entity_b"])],
            "provenance_complete": bool(usable) and all(
                len(metric.get("provenance", [])) == 2
                and all(source.get("source_url") for source in metric["provenance"])
                for metric in usable
            ),
            "differentiated_content_count": sum(not _close(metric["absolute_difference"], 0) for metric in usable),
            "duplicate_intent": key in duplicate_comparisons,
            "required_internal_links": [country_urls[entity_a["id"]], country_urls[entity_b["id"]], "methodology/"] + [indicator_urls[metric["metric_id"]] for metric in usable],
            "available_internal_links": available_urls,
            "canonical_url": canonical_url(site_config["base_url"], comparison["path"]), "expected_canonical_url": canonical_url(site_config["base_url"], comparison["path"]),
            "unsupported_calculations": _unsupported_comparison_calculations(comparison["metrics"]),
        }
        result, report = _evaluated(context)
        comparison_reports.append(report)
        if result["status"] == "generated":
            comparisons.append(comparison)

    change_pages: list[dict] = []
    change_reports: list[dict] = []
    requested_end = int(change_config["requested_end_year"])
    for entity in configured_entities:
        for window in sorted(change_config["windows"]):
            requested_start = requested_end - int(window)
            path = change_path(entity, requested_start, requested_end)
            metrics = []
            if country_urls[entity["id"]] in available_urls:
                for configured_metric in indicators:
                    derived = derive_change_metric(
                        series_by_key[(entity["id"], configured_metric["id"])],
                        requested_start, requested_end,
                        tolerance_years=int(change_config["observation_tolerance_years"]),
                        minimum_span_years=int(change_config["minimum_span_by_window"][str(window)]),
                        acceleration_minimum_observations=int(change_config["acceleration_minimum_observations"]),
                    )
                    if derived:
                        metrics.append(derived)
            insight_result = generate_insights(InsightContext(
                context_type="change", metrics=metrics, config=change_config,
                subject={"entity": entity},
            )) if metrics else {"candidates": [], "selected": [], "summary": ""}
            context = {
                "url": path, "page_type": "what_changed", "as_of_year": as_of_year,
                "usable_facts": len(metrics), "usable_historical_metrics": len(metrics),
                "insight_candidate_count": len(insight_result["candidates"]), "selected_insight_count": len(insight_result["selected"]),
                "source_years": [metric["actual_end_year"] for metric in metrics],
                "provenance_complete": bool(metrics) and all(metric.get("source_url") and len(metric.get("source_facts", [])) == 2 for metric in metrics),
                "differentiated_content_count": len({metric["metric_id"] for metric in metrics}), "duplicate_intent": False,
                "required_internal_links": [country_urls[entity["id"]], "methodology/"] + [indicator_urls[metric["metric_id"]] for metric in metrics],
                "available_internal_links": available_urls,
                "canonical_url": canonical_url(site_config["base_url"], path), "expected_canonical_url": canonical_url(site_config["base_url"], path),
                "unsupported_calculations": _unsupported_change_calculations(metrics),
                "policy_overrides": {"minimum_usable_facts": int(change_config["minimum_usable_metrics"]), "minimum_historical_metrics": int(change_config["minimum_usable_metrics"]), "minimum_insight_candidates": int(change_config["minimum_insight_candidates"]), "minimum_selected_insights": int(change_config["minimum_selected_insights"])},
            }
            result, report = _evaluated(context)
            change_reports.append(report)
            if result["status"] == "generated":
                change_pages.append({"entity": entity, "path": path, "requested_start_year": requested_start, "requested_end_year": requested_end, "window_years": int(window), "metrics": metrics, "insight_candidates": insight_result["candidates"], "selected_insights": insight_result["selected"], "summary": insight_result["summary"]})

    quality_report = [base_results[country_urls[item["id"]]][1] for item in configured_entities] + [base_results[indicator_urls[item["id"]]][1] for item in configured_metrics] + comparison_reports + change_reports
    comparisons_by_country = {entity["id"]: [] for entity in countries}
    for comparison in comparisons:
        comparisons_by_country[comparison["entity_a"]["id"]].append(comparison)
        comparisons_by_country[comparison["entity_b"]["id"]].append(comparison)
    changes_by_country = {entity["id"]: [] for entity in countries}
    for page in change_pages:
        changes_by_country[page["entity"]["id"]].append(page)

    page_paths = [""]
    common = {"site": site_config, "countries": countries, "indicators": indicators, "retrieved_at": snapshot["retrieved_at"], "comparisons": comparisons, "change_pages": change_pages, "canonical_url": canonical_url}

    def render(template: str, page_path: str, destination: Path, **context: object) -> None:
        html = env.get_template(template).render(**common, page_path=page_path, link=lambda target: relative_url(page_path, target), **context)
        write_text(destination, html)

    render("home.html", "", output / "index.html")
    for country in countries:
        page_path = country_urls[country["id"]]
        page_paths.append(page_path)
        values = base_results[page_path][2]["values"]
        render("country.html", page_path, output / page_path / "index.html", country=country, values=values, country_comparisons=comparisons_by_country[country["id"]], country_change_pages=changes_by_country[country["id"]])
    for indicator in indicators:
        page_path = indicator_urls[indicator["id"]]
        page_paths.append(page_path)
        render("indicator.html", page_path, output / page_path / "index.html", indicator=indicator, ranking=base_results[page_path][2]["ranking"])
    for comparison in comparisons:
        page_paths.append(comparison["path"])
        render("comparison.html", comparison["path"], output / comparison["path"] / "index.html", comparison=comparison)
    for change_page in change_pages:
        page_paths.append(change_page["path"])
        siblings = [page for page in changes_by_country[change_page["entity"]["id"]] if page["path"] != change_page["path"]]
        render("what_changed.html", change_page["path"], output / change_page["path"] / "index.html", change=change_page, sibling_pages=siblings)
    page_paths.append("methodology/")
    render("methodology.html", "methodology/", output / "methodology" / "index.html")

    shutil.copy2(paths.static / "styles.css", output / "styles.css")
    write_text(output / ".nojekyll", "")
    write_text(output / "sitemap.xml", env.get_template("sitemap.xml").render(site=site_config, page_paths=page_paths, canonical_url=canonical_url))
    write_text(output / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {canonical_url(site_config['base_url'], 'sitemap.xml')}")
    manifest = {
        "build_timestamp": snapshot["retrieved_at"], "source_name": snapshot["source"]["name"],
        "countries_count": len(countries), "indicators_count": len(indicators), "comparisons_count": len(comparisons),
        "what_changed_generated_count": len(change_pages), "what_changed_skipped_count": sum(row["status"] == "skipped" for row in change_reports),
        "eligible_generated_page_count": sum(row["status"] == "generated" for row in quality_report),
        "eligible_skipped_page_count": sum(row["status"] == "skipped" for row in quality_report),
        "generated_page_count": len(page_paths), "generator_version": GENERATOR_VERSION, "schema_version": schema_version,
    }
    write_text(paths.generated_data / "build_manifest.json", json.dumps(manifest, indent=2))
    write_text(paths.generated_data / "page_quality_report.json", json.dumps(quality_report, indent=2))
    return len(page_paths)


def main(
    paths: SitePaths,
    snapshot_fetcher: Callable[[Path, dict, list[dict], list[dict]], dict],
    snapshot_normalizer: Callable[[dict, list[dict], list[dict]], dict],
    schema_version: str,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Render the existing snapshot without a network request")
    args = parser.parse_args()
    snapshot_path = paths.generated_data / "world_bank_snapshot.json"
    try:
        if args.offline:
            snapshot = load_json(snapshot_path)
        else:
            site, entities, metrics = load_site_config(paths)
            snapshot = snapshot_fetcher(snapshot_path, site, entities, metrics)
        count = render_site(snapshot, paths, snapshot_normalizer, schema_version)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"error: build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {count} HTML pages in {paths.output}")
    return 0


__all__ = ["GENERATOR_VERSION", "main", "render_site"]
