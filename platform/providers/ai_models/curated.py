"""Load and validate a configuration-driven, official-source catalog snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_VERSION = "1.0"
PROVENANCE_FIELDS = (
    "source_name", "source_url", "source_metric_id", "observation_date",
    "effective_date", "retrieved_at", "source_type", "confidence", "status",
)


def _complete_provenance(record: dict) -> bool:
    provenance = record.get("provenance")
    return isinstance(provenance, dict) and all(provenance.get(key) not in (None, "") for key in PROVENANCE_FIELDS)


def _official_https(record: dict, allowed_hosts: set[str]) -> bool:
    if not _complete_provenance(record):
        return False
    parsed = urlparse(record["provenance"]["source_url"])
    return parsed.scheme == "https" and parsed.hostname in allowed_hosts


def validate_catalog(catalog: dict) -> list[str]:
    """Return stable validation errors; curated input is never silently repaired."""
    errors: list[str] = []
    if catalog.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    allowed_hosts = set(catalog.get("allowed_source_hosts", []))
    providers = catalog.get("providers", [])
    models = catalog.get("models", [])
    benchmarks = catalog.get("benchmarks", [])
    prices = catalog.get("pricing_observations", [])
    performance = catalog.get("performance_observations", [])
    provider_ids = {item.get("id") for item in providers}
    model_ids = {item.get("id") for item in models}
    benchmark_ids = {item.get("id") for item in benchmarks}
    for label, records in (
        ("provider", providers), ("model", models), ("benchmark", benchmarks),
        ("pricing observation", prices), ("performance observation", performance),
    ):
        for index, record in enumerate(records, 1):
            if not _official_https(record, allowed_hosts):
                errors.append(f"{label} {index} lacks complete provenance or an allow-listed official HTTPS source")
    for model in models:
        if model.get("provider_id") not in provider_ids:
            errors.append(f"model {model.get('id')} references an unknown provider")
        if not isinstance(model.get("context_window_tokens"), int) or model.get("context_window_tokens", 0) <= 0:
            errors.append(f"model {model.get('id')} needs a positive context window")
        if model.get("status") not in {"active", "legacy", "deprecated", "retired", "preview"}:
            errors.append(f"model {model.get('id')} has an invalid status")
        if model.get("openness") not in {"open", "closed"}:
            errors.append(f"model {model.get('id')} has an invalid openness value")
    for price in prices:
        if price.get("model_id") not in model_ids:
            errors.append(f"pricing observation references unknown model {price.get('model_id')}")
        if price.get("currency") != "USD":
            errors.append(f"pricing observation for {price.get('model_id')} must use USD")
        if price.get("unit") not in {"usd_per_token", "usd_per_1k_tokens", "usd_per_1m_tokens"}:
            errors.append(f"pricing observation for {price.get('model_id')} has an unsupported unit")
        if any(not isinstance(price.get(key), (int, float)) or price[key] < 0 for key in ("input_price", "output_price")):
            errors.append(f"pricing observation for {price.get('model_id')} needs non-negative numeric prices")
    for observation in performance:
        if observation.get("model_id") not in model_ids:
            errors.append(f"performance observation references unknown model {observation.get('model_id')}")
        if observation.get("benchmark_id") not in benchmark_ids:
            errors.append(f"performance observation references unknown benchmark {observation.get('benchmark_id')}")
        if not observation.get("evaluation_configuration") or not observation.get("comparison_group"):
            errors.append(f"performance observation for {observation.get('model_id')} lacks comparability metadata")
    for label, records in (("provider", providers), ("model", models), ("benchmark", benchmarks)):
        ids = [item.get("id") for item in records]
        slugs = [item.get("slug") for item in records]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate {label} ids")
        if len(slugs) != len(set(slugs)):
            errors.append(f"duplicate {label} slugs")
    return errors


def load_catalog(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    errors = validate_catalog(catalog)
    if errors:
        raise ValueError("invalid AI model catalog: " + "; ".join(errors))
    return catalog

