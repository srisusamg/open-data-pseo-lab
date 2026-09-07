"""Validate generated pages, metadata, attribution, and internal links."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.model import ROOT, load_config


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title = ""
        self.h1_count = 0
        self.links: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []

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


def validate() -> list[str]:
    _, countries, indicators = load_config()
    errors: list[str] = []
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
    print("Validation passed: required pages, metadata, attribution, and internal links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
