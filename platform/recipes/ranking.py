"""Ranking page recipe over normalized facts for one canonical metric."""

from __future__ import annotations

from platform.core.provenance import complete_provenance
from platform.core.rendering import rank_observations
from platform.core.urls import canonical_url


def ranking_path(metric: dict, prefix: str = "indicators") -> str:
    return f"{prefix}/{metric['slug']}/"


def prepare_ranking(
    metric: dict, series: list[dict], *, path: str, as_of_year: int,
    base_url: str, entity_urls: dict[str, str], available_urls: set[str],
    duplicate_intent: bool,
) -> tuple[dict, dict]:
    values = [item for item in series if entity_urls[item["entity_id"]] in available_urls]
    ranking = rank_observations([
        {
            **item,
            "year": item["latest_observation"]["year"] if item.get("latest_observation") else None,
            "value": item["latest_observation"]["value"] if item.get("latest_observation") else None,
        }
        for item in values
    ])
    context = {
        "url": path, "page_type": "indicator_ranking", "as_of_year": as_of_year,
        "usable_facts": len(ranking),
        "usable_historical_metrics": sum(
            any(item.get("derived_metrics", {}).get(period) for period in ("five_year", "ten_year"))
            for item in values
        ),
        "source_years": [item["year"] for item in ranking],
        "provenance_complete": complete_provenance(values),
        "differentiated_content_count": len({item["value"] for item in ranking}),
        "duplicate_intent": duplicate_intent,
        "required_internal_links": ["methodology/"] + [entity_urls[item["entity_id"]] for item in ranking],
        "available_internal_links": available_urls,
        "canonical_url": canonical_url(base_url, path),
        "expected_canonical_url": canonical_url(base_url, path),
        "unsupported_calculations": 0,
    }
    return context, {"metric": metric, "ranking": ranking}
