"""Validate generated pages, metadata, attribution, and internal links."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_world_bank import HISTORY_OBSERVATIONS, SCHEMA_VERSION
from scripts.comparison_metrics import comparison_path
from scripts.model import ROOT, calculate_derived_metrics, canonical_url, load_comparisons, load_config, load_json


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title = ""
        self.h1_count = 0
        self.links: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []
        self.history_table_count = 0
        self.derived_block_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")
        elif tag == "meta" and values.get("name", "").lower() == "description":
            self.descriptions.append(values.get("content") or "")
        elif tag == "link" and values.get("rel", "").lower() == "canonical":
            self.canonicals.append(values.get("href") or "")
        elif tag == "div":
            classes = set((values.get("class") or "").split())
            self.history_table_count += "history-table" in classes
            self.derived_block_count += "derived" in classes

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data


def expected_pages(countries: list[dict], indicators: list[dict], comparisons: list[tuple[dict, dict]], change_paths: list[str] | None = None) -> list[Path]:
    pages = [ROOT / "site" / "index.html", ROOT / "site" / "methodology" / "index.html"]
    pages += [ROOT / "site" / "countries" / item["slug"] / "index.html" for item in countries]
    pages += [ROOT / "site" / "indicators" / item["slug"] / "index.html" for item in indicators]
    pages += [ROOT / "site" / comparison_path(country_a, country_b) / "index.html" for country_a, country_b in comparisons]
    pages += [ROOT / "site" / path / "index.html" for path in (change_paths or [])]
    return pages


def resolve_link(page: Path, href: str) -> Path | None:
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc or href.startswith(("#", "mailto:")):
        return None
    target = (page.parent / unquote(parsed.path)).resolve()
    if parsed.path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def validate_snapshot(snapshot: dict, countries: list[dict], indicators: list[dict]) -> list[str]:
    errors: list[str] = []
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"snapshot schema_version must be {SCHEMA_VERSION}")
    series = snapshot.get("series")
    if not isinstance(series, list):
        return errors + ["snapshot series must be a list"]
    expected_pairs = {(country["code"], indicator["code"]) for country in countries for indicator in indicators}
    actual_pairs = {(item.get("country_code"), item.get("indicator_code")) for item in series}
    if actual_pairs != expected_pairs or len(series) != len(expected_pairs):
        errors.append("snapshot must contain exactly one series for every configured country/indicator pair")
    for item in series:
        label = f"{item.get('country_code')} / {item.get('indicator_code')}"
        observations = item.get("observations")
        if not isinstance(observations, list):
            errors.append(f"{label}: observations must be a list")
            continue
        if len(observations) < HISTORY_OBSERVATIONS:
            errors.append(f"{label}: expected at least {HISTORY_OBSERVATIONS} available observations")
        years = [row.get("year") for row in observations]
        if any(not isinstance(year, int) for year in years):
            errors.append(f"{label}: every observation year must be an integer")
        elif years != sorted(years, reverse=True) or len(years) != len(set(years)):
            errors.append(f"{label}: observation years must be unique and newest first")
        if any(not isinstance(row.get("value"), (int, float)) or isinstance(row.get("value"), bool) for row in observations):
            errors.append(f"{label}: every observation value must be numeric")
        expected_latest = observations[0] if observations else None
        if item.get("latest_observation") != expected_latest:
            errors.append(f"{label}: latest_observation must match the newest historical observation")
        expected_derived = calculate_derived_metrics(observations)
        if item.get("derived_metrics") != expected_derived:
            errors.append(f"{label}: derived_metrics do not match deterministic recalculation")
    return errors


def validate() -> list[str]:
    site, countries, indicators = load_config()
    errors: list[str] = []
    try:
        comparisons = load_comparisons(countries)
    except (OSError, ValueError, TypeError) as exc:
        return [f"invalid comparison configuration: {exc}"]
    snapshot_path = ROOT / "data" / "generated" / "world_bank_snapshot.json"
    if not snapshot_path.is_file():
        errors.append("missing required artifact: data/generated/world_bank_snapshot.json")
    else:
        try:
            errors.extend(validate_snapshot(load_json(snapshot_path), countries, indicators))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"invalid generated snapshot: {exc}")
    quality_path = ROOT / "data" / "generated" / "page_quality_report.json"
    quality_rows: list[dict] = []
    if not quality_path.is_file():
        errors.append("missing required artifact: data/generated/page_quality_report.json")
    else:
        try:
            quality_rows = load_json(quality_path)
            if not isinstance(quality_rows, list):
                errors.append("page quality report must be a list")
                quality_rows = []
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"invalid page quality report: {exc}")
    generated_changes = [row.get("url") for row in quality_rows if row.get("status") == "generated" and isinstance(row.get("url"), str)]
    skipped_changes = [row.get("url") for row in quality_rows if row.get("status") == "skipped" and isinstance(row.get("url"), str)]
    site_root = (ROOT / "site").resolve()
    for required in [ROOT / "site" / "sitemap.xml", ROOT / "site" / "robots.txt"]:
        if not required.is_file():
            errors.append(f"missing required artifact: {required.relative_to(ROOT)}")
    country_pages = {ROOT / "site" / "countries" / item["slug"] / "index.html" for item in countries}
    titles: dict[str, Path] = {}
    comparison_pages = {ROOT / "site" / comparison_path(a, b) / "index.html" for a, b in comparisons}
    change_pages = {ROOT / "site" / path / "index.html" for path in generated_changes}
    for page in expected_pages(countries, indicators, comparisons, generated_changes):
        if not page.is_file():
            errors.append(f"missing page: {page.relative_to(ROOT)}")
            continue
        text = page.read_text(encoding="utf-8")
        if len(text.strip()) < 200:
            errors.append(f"page appears empty: {page.relative_to(ROOT)}")
        parser = PageParser()
        parser.feed(text)
        if not parser.title.strip():
            errors.append(f"missing title: {page.relative_to(ROOT)}")
        elif parser.title.strip() in titles:
            errors.append(f"duplicate title in {page.relative_to(ROOT)} and {titles[parser.title.strip()].relative_to(ROOT)}")
        else:
            titles[parser.title.strip()] = page
        if parser.h1_count != 1:
            errors.append(f"expected one H1 in {page.relative_to(ROOT)}, found {parser.h1_count}")
        if len(parser.descriptions) != 1 or not parser.descriptions[0].strip():
            errors.append(f"expected one non-empty meta description: {page.relative_to(ROOT)}")
        if len(parser.canonicals) != 1 or not parser.canonicals[0].startswith("https://"):
            errors.append(f"expected one absolute canonical URL: {page.relative_to(ROOT)}")
        if page in country_pages and "World Bank" not in text:
            errors.append(f"missing World Bank attribution: {page.relative_to(ROOT)}")
        if page in comparison_pages and "World Bank" not in text:
            errors.append(f"missing World Bank attribution: {page.relative_to(ROOT)}")
        if page in change_pages and "World Bank" not in text:
            errors.append(f"missing World Bank attribution: {page.relative_to(ROOT)}")
        if page in country_pages:
            if parser.history_table_count != len(indicators):
                errors.append(f"expected one historical table per indicator: {page.relative_to(ROOT)}")
            if parser.derived_block_count != len(indicators):
                errors.append(f"expected one separate derived-metrics block per indicator: {page.relative_to(ROOT)}")
        for href in parser.links:
            target = resolve_link(page, href)
            if target is None:
                continue
            try:
                target.relative_to(site_root)
            except ValueError:
                errors.append(f"link escapes site root in {page.relative_to(ROOT)}: {href}")
                continue
            if not target.is_file():
                errors.append(f"broken link in {page.relative_to(ROOT)}: {href}")
    sitemap_path = ROOT / "site" / "sitemap.xml"
    if sitemap_path.is_file():
        sitemap = sitemap_path.read_text(encoding="utf-8")
        for country_a, country_b in comparisons:
            url = canonical_url(site["base_url"], comparison_path(country_a, country_b))
            if f"<loc>{url}</loc>" not in sitemap:
                errors.append(f"sitemap missing comparison URL: {url}")
        for path in generated_changes:
            url = canonical_url(site["base_url"], path)
            if f"<loc>{url}</loc>" not in sitemap:
                errors.append(f"sitemap missing generated change URL: {url}")
        for path in skipped_changes:
            url = canonical_url(site["base_url"], path)
            if f"<loc>{url}</loc>" in sitemap:
                errors.append(f"sitemap contains skipped change URL: {url}")
            if (ROOT / "site" / path / "index.html").is_file():
                errors.append(f"skipped change page was published: {path}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Validation passed: snapshot history, derived metrics, pages, metadata, attribution, and links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
