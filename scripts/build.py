"""Refresh World Bank data and render the complete static site."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_world_bank import SCHEMA_VERSION, fetch_snapshot
from scripts.model import ROOT, canonical_url, format_value, load_config, load_json, rank_observations, relative_url

GENERATOR_VERSION = "1.0.0"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_site(snapshot: dict) -> int:
    site_config, countries, indicators = load_config()
    output = ROOT / "site"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["value"] = format_value

    observations = snapshot["observations"]
    by_country = {country["slug"]: [] for country in countries}
    by_indicator = {indicator["slug"]: [] for indicator in indicators}
    for item in observations:
        by_country[item["country_slug"]].append(item)
        by_indicator[item["indicator_slug"]].append(item)

    page_paths = [""]
    common = {
        "site": site_config,
        "countries": countries,
        "indicators": indicators,
        "retrieved_at": snapshot["retrieved_at"],
        "canonical_url": canonical_url,
    }

    def render(template: str, page_path: str, destination: Path, **context: object) -> None:
        link = lambda target: relative_url(page_path, target)
        html = env.get_template(template).render(**common, page_path=page_path, link=link, **context)
        write_text(destination, html)

    render("home.html", "", output / "index.html")
    for country in countries:
        page_path = f"countries/{country['slug']}/"
        page_paths.append(page_path)
        values = sorted(by_country[country["slug"]], key=lambda x: [i["slug"] for i in indicators].index(x["indicator_slug"]))
        render("country.html", page_path, output / page_path / "index.html", country=country, values=values)
    for indicator in indicators:
        page_path = f"indicators/{indicator['slug']}/"
        page_paths.append(page_path)
        ranking = rank_observations(by_indicator[indicator["slug"]])
        render("indicator.html", page_path, output / page_path / "index.html", indicator=indicator, ranking=ranking)
    page_paths.append("methodology/")
    render("methodology.html", "methodology/", output / "methodology" / "index.html")

    shutil.copy2(ROOT / "static" / "styles.css", output / "styles.css")
    write_text(output / ".nojekyll", "")
    sitemap = env.get_template("sitemap.xml").render(site=site_config, page_paths=page_paths, canonical_url=canonical_url)
    write_text(output / "sitemap.xml", sitemap)
    write_text(output / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {canonical_url(site_config['base_url'], 'sitemap.xml')}")

    manifest = {
        "build_timestamp": snapshot["retrieved_at"],
        "source_name": snapshot["source"]["name"],
        "countries_count": len(countries),
        "indicators_count": len(indicators),
        "generated_page_count": len(page_paths),
        "generator_version": GENERATOR_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    write_text(ROOT / "data" / "generated" / "build_manifest.json", json.dumps(manifest, indent=2))
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

