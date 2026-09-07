"""Validate generated pages, metadata, attribution, and internal links."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_world_bank import HISTORY_OBSERVATIONS, SCHEMA_VERSION
from scripts.model import ROOT, calculate_derived_metrics, load_config, load_json


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


def expected_pages(countries: list[dict], indicators: list[dict]) -> list[Path]:
    pages = [ROOT / "site" / "index.html", ROOT / "site" / "methodology" / "index.html"]
    pages += [ROOT / "site" / "countries" / item["slug"] / "index.html" for item in countries]
    pages += [ROOT / "site" / "indicators" / item["slug"] / "index.html" for item in indicators]
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
    _, countries, indicators = load_config()
    errors: list[str] = []
    snapshot_path = ROOT / "data" / "generated" / "world_bank_snapshot.json"
    if not snapshot_path.is_file():
        errors.append("missing required artifact: data/generated/world_bank_snapshot.json")
    else:
        try:
            errors.extend(validate_snapshot(load_json(snapshot_path), countries, indicators))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"invalid generated snapshot: {exc}")
    site_root = (ROOT / "site").resolve()
    for required in [ROOT / "site" / "sitemap.xml", ROOT / "site" / "robots.txt"]:
        if not required.is_file():
            errors.append(f"missing required artifact: {required.relative_to(ROOT)}")
    country_pages = {ROOT / "site" / "countries" / item["slug"] / "index.html" for item in countries}
    titles: dict[str, Path] = {}
    for page in expected_pages(countries, indicators):
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
