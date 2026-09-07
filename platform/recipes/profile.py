"""Profile page recipe over one canonical entity's normalized metric series."""

from __future__ import annotations

from platform.core.derivations import calculate_derived_metrics
from platform.core.provenance import complete_provenance
from platform.core.urls import canonical_url


def profile_path(entity: dict, prefix: str = "countries") -> str:
    return f"{prefix}/{entity['slug']}/"


def prepare_profile(
    entity: dict, series: list[dict], *, path: str, as_of_year: int,
    base_url: str, metric_urls: dict[str, str], available_urls: set[str],
    duplicate_intent: bool,
) -> tuple[dict, dict]:
    values = [item for item in series if metric_urls[item["metric_id"]] in available_urls]
    usable = [item for item in values if item.get("latest_observation")]
    context = {
        "url": path, "page_type": "country_profile", "as_of_year": as_of_year,
        "usable_facts": len(usable),
        "usable_historical_metrics": sum(
            any(item.get("derived_metrics", {}).get(period) for period in ("five_year", "ten_year"))
            for item in usable
        ),
        "source_years": [item["latest_observation"]["year"] for item in usable],
        "provenance_complete": complete_provenance(usable),
        "differentiated_content_count": len({item["metric_id"] for item in usable}),
        "duplicate_intent": duplicate_intent,
        "required_internal_links": ["methodology/"] + [metric_urls[item["metric_id"]] for item in usable],
        "available_internal_links": available_urls,
        "canonical_url": canonical_url(base_url, path),
        "expected_canonical_url": canonical_url(base_url, path),
        "unsupported_calculations": sum(
            item.get("derived_metrics") != calculate_derived_metrics(item.get("observations", []))
            for item in usable
        ),
    }
    return context, {"entity": entity, "values": values}
