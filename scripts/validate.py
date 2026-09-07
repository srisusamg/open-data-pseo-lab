"""Validate generated pages, metadata, attribution, and internal links."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.comparison_metrics import comparison_path
from scripts.model import ROOT, canonical_url, load_comparisons, load_config, load_json
from scripts.build import DEFAULT_PATHS
from platform.providers.world_bank.validation import validate_snapshot


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


def expected_pages(generated_paths: list[str]) -> list[Path]:
    return [ROOT / "site" / "index.html", ROOT / "site" / "methodology" / "index.html"] + [ROOT / "site" / path / "index.html" for path in generated_paths]


def resolve_link(page: Path, href: str) -> Path | None:
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc or href.startswith(("#", "mailto:")):
        return None
    target = (page.parent / unquote(parsed.path)).resolve()
    if parsed.path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


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
    change_config = load_json(DEFAULT_PATHS.config / "change_windows.json")
    expected_recipes = {
        **{f"countries/{item['slug']}/": "country_profile" for item in countries},
        **{f"indicators/{item['slug']}/": "indicator_ranking" for item in indicators},
        **{comparison_path(a, b): "comparison" for a, b in comparisons},
        **{
            f"countries/{country['slug']}/change/{int(change_config['requested_end_year']) - int(window)}-{int(change_config['requested_end_year'])}/": "what_changed"
            for country in countries for window in change_config["windows"]
        },
    }
    report_by_url: dict[str, dict] = {}
    required_report_fields = {
        "url", "page_type", "status", "quality_score", "usable_facts", "usable_historical_metrics",
        "insight_candidate_count", "selected_insight_count", "source_freshness", "skip_reasons",
    }
    for index, row in enumerate(quality_rows, 1):
        if not isinstance(row, dict):
            errors.append(f"page quality report row {index} must be an object")
            continue
        missing = sorted(required_report_fields - row.keys())
        if missing:
            errors.append(f"page quality report row {index} missing fields: {', '.join(missing)}")
        url = row.get("url")
        if not isinstance(url, str):
            errors.append(f"page quality report row {index} has invalid URL")
            continue
        if url in report_by_url:
            errors.append(f"page quality report has duplicate URL: {url}")
        report_by_url[url] = row
        if row.get("status") not in {"generated", "skipped"}:
            errors.append(f"page quality report has invalid status for {url}")
        if not isinstance(row.get("quality_score"), int) or not 0 <= row.get("quality_score", -1) <= 100:
            errors.append(f"page quality report has invalid quality score for {url}")
        if not isinstance(row.get("skip_reasons"), list) or (row.get("status") == "generated") == bool(row.get("skip_reasons")):
            errors.append(f"page quality report has inconsistent skip reasons for {url}")
        if not isinstance(row.get("source_freshness"), dict):
            errors.append(f"page quality report has invalid source freshness for {url}")
    if set(report_by_url) != set(expected_recipes):
        for path in sorted(set(expected_recipes) - set(report_by_url)):
            errors.append(f"page quality report missing potential page: {path}")
        for path in sorted(set(report_by_url) - set(expected_recipes)):
            errors.append(f"page quality report contains unexpected page: {path}")
    for path, page_type in expected_recipes.items():
        if path in report_by_url and report_by_url[path].get("page_type") != page_type:
            errors.append(f"page quality report has wrong page type for {path}")

    generated_paths = [path for path, row in report_by_url.items() if row.get("status") == "generated"]
    skipped_paths = [path for path, row in report_by_url.items() if row.get("status") == "skipped"]
    site_root = (ROOT / "site").resolve()
    for required in [ROOT / "site" / "sitemap.xml", ROOT / "site" / "robots.txt"]:
        if not required.is_file():
            errors.append(f"missing required artifact: {required.relative_to(ROOT)}")
    country_pages = {ROOT / "site" / path / "index.html" for path, row in report_by_url.items() if row.get("page_type") == "country_profile" and row.get("status") == "generated"}
    titles: dict[str, Path] = {}
    comparison_pages = {ROOT / "site" / path / "index.html" for path, row in report_by_url.items() if row.get("page_type") == "comparison" and row.get("status") == "generated"}
    change_pages = {ROOT / "site" / path / "index.html" for path, row in report_by_url.items() if row.get("page_type") == "what_changed" and row.get("status") == "generated"}
    expected_files = set(expected_pages(generated_paths))
    actual_files = set((ROOT / "site").rglob("index.html")) if (ROOT / "site").is_dir() else set()
    for extra in sorted(actual_files - expected_files):
        errors.append(f"unexpected generated page: {extra.relative_to(ROOT)}")
    for page in expected_files:
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
            report_path = page.parent.relative_to(ROOT / "site").as_posix() + "/"
            minimum = report_by_url[report_path].get("usable_facts", 0)
            if parser.history_table_count < minimum:
                errors.append(f"country page has fewer historical tables than usable facts: {page.relative_to(ROOT)}")
            if parser.derived_block_count != parser.history_table_count:
                errors.append(f"expected one separate derived-metrics block per history table: {page.relative_to(ROOT)}")
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
        for path in generated_paths:
            url = canonical_url(site["base_url"], path)
            if f"<loc>{url}</loc>" not in sitemap:
                errors.append(f"sitemap missing generated URL: {url}")
        for path in skipped_paths:
            url = canonical_url(site["base_url"], path)
            if f"<loc>{url}</loc>" in sitemap:
                errors.append(f"sitemap contains skipped URL: {url}")
            if (ROOT / "site" / path / "index.html").is_file():
                errors.append(f"skipped page was published: {path}")
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
