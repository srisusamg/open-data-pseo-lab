"""Fetch and normalize the configured World Bank indicator observations."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.model import ROOT, latest_non_null, load_config, source_url

API_WINDOW_YEARS = 10
SCHEMA_VERSION = "1.0"


class WorldBankError(RuntimeError):
    pass


def session_with_retries() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.headers["User-Agent"] = "OpenData-Atlas/1.0 (+https://github.com/srisusamg/open-data-pseo-lab)"
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_indicator(session: requests.Session, country: dict, indicator: dict, start_year: int, end_year: int) -> dict:
    url = source_url(country["code"], indicator["code"])
    params = {"format": "json", "date": f"{start_year}:{end_year}", "per_page": 100}
    try:
        response = session.get(url.split("?", 1)[0], params=params, timeout=(5, 30))
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WorldBankError(f"Failed to fetch {country['code']} / {indicator['code']}: {exc}") from exc
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise WorldBankError(f"Malformed World Bank response for {country['code']} / {indicator['code']}")
    selected = latest_non_null(payload[1])
    return {
        "country_code": country["code"],
        "country_slug": country["slug"],
        "country_name": country["name"],
        "indicator_code": indicator["code"],
        "indicator_slug": indicator["slug"],
        "indicator_name": indicator["name"],
        "unit": indicator["unit"],
        "format": indicator["format"],
        "year": int(selected["date"]) if selected else None,
        "value": selected["value"] if selected else None,
        "source_url": response.url,
    }


def fetch_snapshot(output: Path) -> dict:
    site, countries, indicators = load_config()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    end_year = now.year
    start_year = end_year - API_WINDOW_YEARS + 1
    session = session_with_retries()
    observations = [
        fetch_indicator(session, country, indicator, start_year, end_year)
        for country in countries
        for indicator in indicators
    ]
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source": {"name": "World Bank", "api": "World Bank Indicators API v2"},
        "retrieved_at": now.isoformat().replace("+00:00", "Z"),
        "window": {"start_year": start_year, "end_year": end_year},
        "observations": observations,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "generated" / "world_bank_snapshot.json")
    args = parser.parse_args()
    try:
        snapshot = fetch_snapshot(args.output)
    except (WorldBankError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Fetched {len(snapshot['observations'])} observations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
