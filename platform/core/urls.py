"""Stable URL and SEO path helpers."""

from __future__ import annotations

import posixpath
from urllib.parse import urljoin, urlparse


def canonical_url(base_url: str, page_path: str) -> str:
    return urljoin(base_url, page_path.lstrip("/"))


def relative_url(from_page: str, to_page: str) -> str:
    start = posixpath.dirname(from_page)
    target = to_page.rstrip("/") or "."
    result = posixpath.relpath(target, start=start or ".")
    return result + "/" if to_page.endswith("/") or to_page == "" else result


def base_path(base_url: str) -> str:
    path = urlparse(base_url).path
    return path if path.endswith("/") else path + "/"
