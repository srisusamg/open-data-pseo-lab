"""Refresh World Bank data, evaluate every page recipe, and render eligible pages."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.change_metrics import change_path, derive_change_metric
from scripts.comparison_metrics import build_comparison
from scripts.fetch_world_bank import SCHEMA_VERSION, fetch_snapshot
from scripts.insights import generate_insights
from scripts.model import ROOT, calculate_derived_metrics, canonical_url, format_change, format_difference, format_value, load_comparisons, load_config, load_json, rank_observations, relative_url
from scripts.page_quality import complete_provenance, duplicate_intents, evaluate_page_quality, quality_report_row
from scripts.summary_rules import render_summary, select_insights as select_comparison_insights

GENERATOR_VERSION = "4.0.0"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _close(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-6)


def _unsupported_comparison_calculations(metrics: list[dict]) -> int:
    invalid = 0
    for metric in metrics:
        a, b = metric.get("country_a"), metric.get("country_b")
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


def render_site(snapshot: dict) -> int:
    site_config, configured_countries, configured_indicators = load_config()
    configured_pairs = load_comparisons(configured_countries)
    change_config = load_json(ROOT / "config" / "change_windows.json")
    output = ROOT / "site"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(("html", "xml")), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(value=format_value, change=format_change, difference=format_difference)

    series = snapshot["series"]
    series_by_key = {(item["country_code"], item["indicator_code"]): item for item in series}
    as_of_year = int(snapshot["retrieved_at"][:4])
    permanent_urls = {"", "methodology/"}
    country_urls = {country["code"]: f"countries/{country['slug']}/" for country in configured_countries}
    indicator_urls = {indicator["code"]: f"indicators/{indicator['slug']}/" for indicator in configured_indicators}
    country_duplicates = duplicate_intents([f"country:{country['code']}" for country in configured_countries])
    indicator_duplicates = duplicate_intents([f"indicator:{indicator['code']}" for indicator in configured_indicators])

    # Country and indicator pages depend on one another. Resolve their eligibility
    # to a fixed point so neither can link to a page removed by the other.
    available_base = permanent_urls | set(country_urls.values()) | set(indicator_urls.values())
    base_results: dict[str, tuple[dict, dict, dict]] = {}
    for _ in range(len(available_base) + 1):
        current: dict[str, tuple[dict, dict, dict]] = {}
        for country in configured_countries:
            values = [series_by_key[(country["code"], indicator["code"])] for indicator in configured_indicators if indicator_urls[indicator["code"]] in available_base]
            usable = [item for item in values if item.get("latest_observation")]
            path = country_urls[country["code"]]
            context = {
                "url": path, "page_type": "country_profile", "as_of_year": as_of_year,
                "usable_facts": len(usable),
                "usable_historical_metrics": sum(any(item.get("derived_metrics", {}).get(period) for period in ("five_year", "ten_year")) for item in usable),
                "source_years": [item["latest_observation"]["year"] for item in usable],
                "provenance_complete": complete_provenance(usable, ("source_url", "indicator_code")),
                "differentiated_content_count": len({item["indicator_code"] for item in usable}),
                "duplicate_intent": f"country:{country['code']}" in country_duplicates,
                "required_internal_links": ["methodology/"] + [indicator_urls[item["indicator_code"]] for item in usable],
                "available_internal_links": available_base,
                "canonical_url": canonical_url(site_config["base_url"], path),
                "expected_canonical_url": canonical_url(site_config["base_url"], path),
                "unsupported_calculations": sum(item.get("derived_metrics") != calculate_derived_metrics(item.get("observations", [])) for item in usable),
            }
            result, report = _evaluated(context)
            current[path] = (result, report, {"country": country, "values": values})
        for indicator in configured_indicators:
            values = [series_by_key[(country["code"], indicator["code"])] for country in configured_countries if country_urls[country["code"]] in available_base]
            ranking = rank_observations([{**item, "year": item["latest_observation"]["year"] if item.get("latest_observation") else None, "value": item["latest_observation"]["value"] if item.get("latest_observation") else None} for item in values])
            path = indicator_urls[indicator["code"]]
            context = {
                "url": path, "page_type": "indicator_ranking", "as_of_year": as_of_year,
                "usable_facts": len(ranking),
                "usable_historical_metrics": sum(any(item.get("derived_metrics", {}).get(period) for period in ("five_year", "ten_year")) for item in values),
                "source_years": [item["year"] for item in ranking],
                "provenance_complete": complete_provenance(values, ("source_url", "indicator_code")),
                "differentiated_content_count": len({item["value"] for item in ranking}),
                "duplicate_intent": f"indicator:{indicator['code']}" in indicator_duplicates,
                "required_internal_links": ["methodology/"] + [country_urls[item["country_code"]] for item in ranking],
                "available_internal_links": available_base,
                "canonical_url": canonical_url(site_config["base_url"], path),
                "expected_canonical_url": canonical_url(site_config["base_url"], path),
                "unsupported_calculations": 0,
            }
            result, report = _evaluated(context)
            current[path] = (result, report, {"indicator": indicator, "ranking": ranking})
        next_available = permanent_urls | {path for path, (result, _, _) in current.items() if result["status"] == "generated"}
        base_results = current
        if next_available == available_base:
            break
        available_base = next_available

    countries = [country for country in configured_countries if base_results[country_urls[country["code"]]][0]["status"] == "generated"]
    indicators = [indicator for indicator in configured_indicators if base_results[indicator_urls[indicator["code"]]][0]["status"] == "generated"]
    available_urls = permanent_urls | {country_urls[c["code"]] for c in countries} | {indicator_urls[i["code"]] for i in indicators}

    comparisons: list[dict] = []
    comparison_reports: list[dict] = []
    comparison_intents = ["comparison:" + ":".join(sorted((a["code"], b["code"]))) for a, b in configured_pairs]
    duplicate_comparisons = duplicate_intents(comparison_intents)
    for country_a, country_b in configured_pairs:
        comparison = build_comparison(country_a, country_b, [series_by_key[(country_a["code"], i["code"])] for i in indicators], [series_by_key[(country_b["code"], i["code"])] for i in indicators])
        insights = select_comparison_insights(comparison)
        comparison["summary"] = render_summary(comparison, insights)
        usable = [metric for metric in comparison["metrics"] if metric.get("country_a") and metric.get("country_b")]
        historical = sum(any(period["country_a"] and period["country_b"] for period in metric["periods"].values()) for metric in usable)
        key = "comparison:" + ":".join(sorted((country_a["code"], country_b["code"])))
        context = {
            "url": comparison["path"], "page_type": "comparison", "as_of_year": as_of_year,
            "usable_facts": len(usable), "usable_historical_metrics": historical,
            "insight_candidate_count": len(insights), "selected_insight_count": len(insights),
            "source_years": [fact["year"] for metric in usable for fact in (metric["country_a"], metric["country_b"])],
            "provenance_complete": bool(usable) and all(len(metric.get("source_urls", [])) == 2 and all(metric["source_urls"]) for metric in usable),
            "differentiated_content_count": sum(not _close(metric["absolute_difference"], 0) for metric in usable),
            "duplicate_intent": key in duplicate_comparisons,
            "required_internal_links": [country_urls[country_a["code"]], country_urls[country_b["code"]], "methodology/"] + [indicator_urls[metric["indicator_code"]] for metric in usable],
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
    for country in configured_countries:
        for window in sorted(change_config["windows"]):
            requested_start = requested_end - int(window)
            path = change_path(country, requested_start, requested_end)
            metrics = []
            if country_urls[country["code"]] in available_urls:
                for indicator in indicators:
                    metric = derive_change_metric(series_by_key[(country["code"], indicator["code"])], requested_start, requested_end, tolerance_years=int(change_config["observation_tolerance_years"]), minimum_span_years=int(change_config["minimum_span_by_window"][str(window)]), acceleration_minimum_observations=int(change_config["acceleration_minimum_observations"]))
                    if metric:
                        metrics.append(metric)
            insight_result = generate_insights({"type": "change", "metrics": metrics, "config": change_config}) if metrics else {"candidates": [], "selected": [], "summary": ""}
            context = {
                "url": path, "page_type": "what_changed", "as_of_year": as_of_year,
                "usable_facts": len(metrics), "usable_historical_metrics": len(metrics),
                "insight_candidate_count": len(insight_result["candidates"]), "selected_insight_count": len(insight_result["selected"]),
                "source_years": [metric["actual_end_year"] for metric in metrics],
                "provenance_complete": bool(metrics) and all(metric.get("source_url") and len(metric.get("source_facts", [])) == 2 for metric in metrics),
                "differentiated_content_count": len({metric["metric_id"] for metric in metrics}), "duplicate_intent": False,
                "required_internal_links": [country_urls[country["code"]], "methodology/"] + [indicator_urls[metric["metric_id"]] for metric in metrics],
                "available_internal_links": available_urls,
                "canonical_url": canonical_url(site_config["base_url"], path), "expected_canonical_url": canonical_url(site_config["base_url"], path),
                "unsupported_calculations": _unsupported_change_calculations(metrics),
                "policy_overrides": {"minimum_usable_facts": int(change_config["minimum_usable_metrics"]), "minimum_historical_metrics": int(change_config["minimum_usable_metrics"]), "minimum_insight_candidates": int(change_config["minimum_insight_candidates"]), "minimum_selected_insights": int(change_config["minimum_selected_insights"])},
            }
            result, report = _evaluated(context)
            change_reports.append(report)
            if result["status"] == "generated":
                change_pages.append({"country": country, "path": path, "requested_start_year": requested_start, "requested_end_year": requested_end, "window_years": int(window), "metrics": metrics, "insight_candidates": insight_result["candidates"], "selected_insights": insight_result["selected"], "summary": insight_result["summary"]})

    quality_report = [base_results[country_urls[c["code"]]][1] for c in configured_countries] + [base_results[indicator_urls[i["code"]]][1] for i in configured_indicators] + comparison_reports + change_reports
    comparisons_by_country = {country["code"]: [] for country in countries}
    for comparison in comparisons:
        comparisons_by_country[comparison["country_a"]["code"]].append(comparison)
        comparisons_by_country[comparison["country_b"]["code"]].append(comparison)
    changes_by_country = {country["code"]: [] for country in countries}
    for page in change_pages:
        changes_by_country[page["country"]["code"]].append(page)

    page_paths = [""]
    common = {"site": site_config, "countries": countries, "indicators": indicators, "retrieved_at": snapshot["retrieved_at"], "comparisons": comparisons, "change_pages": change_pages, "canonical_url": canonical_url}

    def render(template: str, page_path: str, destination: Path, **context: object) -> None:
        html = env.get_template(template).render(**common, page_path=page_path, link=lambda target: relative_url(page_path, target), **context)
        write_text(destination, html)

    render("home.html", "", output / "index.html")
    for country in countries:
        page_path = country_urls[country["code"]]
        page_paths.append(page_path)
        values = base_results[page_path][2]["values"]
        render("country.html", page_path, output / page_path / "index.html", country=country, values=values, country_comparisons=comparisons_by_country[country["code"]], country_change_pages=changes_by_country[country["code"]])
    for indicator in indicators:
        page_path = indicator_urls[indicator["code"]]
        page_paths.append(page_path)
        render("indicator.html", page_path, output / page_path / "index.html", indicator=indicator, ranking=base_results[page_path][2]["ranking"])
    for comparison in comparisons:
        page_paths.append(comparison["path"])
        render("comparison.html", comparison["path"], output / comparison["path"] / "index.html", comparison=comparison)
    for change_page in change_pages:
        page_paths.append(change_page["path"])
        siblings = [page for page in changes_by_country[change_page["country"]["code"]] if page["path"] != change_page["path"]]
        render("what_changed.html", change_page["path"], output / change_page["path"] / "index.html", change=change_page, sibling_pages=siblings)
    page_paths.append("methodology/")
    render("methodology.html", "methodology/", output / "methodology" / "index.html")

    shutil.copy2(ROOT / "static" / "styles.css", output / "styles.css")
    write_text(output / ".nojekyll", "")
    write_text(output / "sitemap.xml", env.get_template("sitemap.xml").render(site=site_config, page_paths=page_paths, canonical_url=canonical_url))
    write_text(output / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {canonical_url(site_config['base_url'], 'sitemap.xml')}")
    manifest = {
        "build_timestamp": snapshot["retrieved_at"], "source_name": snapshot["source"]["name"],
        "countries_count": len(countries), "indicators_count": len(indicators), "comparisons_count": len(comparisons),
        "what_changed_generated_count": len(change_pages), "what_changed_skipped_count": sum(row["status"] == "skipped" for row in change_reports),
        "eligible_generated_page_count": sum(row["status"] == "generated" for row in quality_report),
        "eligible_skipped_page_count": sum(row["status"] == "skipped" for row in quality_report),
        "generated_page_count": len(page_paths), "generator_version": GENERATOR_VERSION, "schema_version": SCHEMA_VERSION,
    }
    write_text(ROOT / "data" / "generated" / "build_manifest.json", json.dumps(manifest, indent=2))
    write_text(ROOT / "data" / "generated" / "page_quality_report.json", json.dumps(quality_report, indent=2))
    return len(page_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Render the existing snapshot without a network request")
    args = parser.parse_args()
    snapshot_path = ROOT / "data" / "generated" / "world_bank_snapshot.json"
    try:
        snapshot = load_json(snapshot_path) if args.offline else fetch_snapshot(snapshot_path)
        count = render_site(snapshot)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"error: build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {count} HTML pages in {ROOT / 'site'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
