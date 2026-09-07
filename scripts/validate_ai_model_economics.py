"""Validate the generated AI Model Economics artifact and its site boundary."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform.core.urls import canonical_url
from platform.providers.ai_models.curated import load_catalog
from scripts.validate import PageParser, resolve_link

_runtime = importlib.import_module("sites.ai-model-economics.runtime")
PATHS = _runtime.PATHS


def validate(paths=PATHS) -> list[str]:
    errors: list[str] = []
    try:
        config = json.loads((paths.config / "site.json").read_text(encoding="utf-8"))
        load_catalog(paths.config / "catalog.json")
    except (OSError, ValueError, TypeError) as exc:
        return [f"invalid source configuration: {exc}"]
    quality_path = paths.generated_data / "page_quality_report.json"
    urls_path = paths.generated_data / "generated_urls.json"
    for required in (quality_path, urls_path, paths.generated_data / "normalized_model_data.json", paths.generated_data / "derived_model_economics.json", paths.generated_data / "build_manifest.json", paths.output / "sitemap.xml", paths.output / "robots.txt"):
        if not required.is_file():
            errors.append(f"missing required artifact: {required}")
    if errors:
        return errors
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    generated = [row["url"] for row in quality if row.get("status") == "generated"]
    skipped = [row["url"] for row in quality if row.get("status") == "skipped"]
    for row in quality:
        if row.get("status") not in {"generated", "skipped"}:
            errors.append(f"invalid quality status: {row.get('url')}")
        if row.get("status") == "generated" and row.get("skip_reasons"):
            errors.append(f"generated row has skip reasons: {row.get('url')}")
        if row.get("status") == "skipped" and not row.get("skip_reasons"):
            errors.append(f"skipped row lacks reasons: {row.get('url')}")
    listed_urls = json.loads(urls_path.read_text(encoding="utf-8"))
    sitemap = (paths.output / "sitemap.xml").read_text(encoding="utf-8")
    site_root = paths.output.resolve()
    pages = list(paths.output.rglob("index.html"))
    titles: dict[str, Path] = {}
    for page in pages:
        text = page.read_text(encoding="utf-8")
        parser = PageParser()
        parser.feed(text)
        relative = page.parent.relative_to(paths.output).as_posix()
        relative_path = "" if relative == "." else relative + "/"
        expected = canonical_url(config["base_url"], relative_path)
        if len(parser.canonicals) != 1 or parser.canonicals[0] != expected:
            errors.append(f"invalid canonical URL: {page}")
        if parser.h1_count != 1:
            errors.append(f"expected one H1: {page}")
        title = parser.title.strip()
        if not title:
            errors.append(f"missing title: {page}")
        elif title in titles:
            errors.append(f"duplicate title: {page} and {titles[title]}")
        titles[title] = page
        if len(parser.descriptions) != 1 or not parser.descriptions[0].strip():
            errors.append(f"missing meta description: {page}")
        if len(text.strip()) < 300:
            errors.append(f"page appears incomplete: {page}")
        for href in parser.links:
            target = resolve_link(page, href)
            if target is None:
                continue
            try:
                target.relative_to(site_root)
            except ValueError:
                errors.append(f"link escapes site root in {page}: {href}")
                continue
            if not target.is_file():
                errors.append(f"broken link in {page}: {href}")
    actual_urls = {canonical_url(config["base_url"], "" if page.parent == paths.output else page.parent.relative_to(paths.output).as_posix() + "/") for page in pages}
    if set(listed_urls) != actual_urls:
        errors.append("generated URL report does not match rendered pages")
    for url in generated:
        if f"<loc>{canonical_url(config['base_url'], url)}</loc>" not in sitemap:
            errors.append(f"sitemap missing generated page: {url}")
    for url in skipped:
        if f"<loc>{canonical_url(config['base_url'], url)}</loc>" in sitemap:
            errors.append(f"sitemap includes skipped page: {url}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("AI Model Economics validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("AI Model Economics validation passed: catalog, quality report, pages, SEO metadata, sitemap, and internal links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
