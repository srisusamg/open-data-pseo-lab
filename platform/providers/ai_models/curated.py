"""Load and validate a configuration-driven, official-source catalog snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import date
from urllib.parse import urlparse

SCHEMA_VERSION = "3.0"
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
    operational = catalog.get("operational_observations", [])
    provider_ids = {item.get("id") for item in providers}
    model_ids = {item.get("id") for item in models}
    benchmark_ids = {item.get("id") for item in benchmarks}
    distribution_types = {"api", "hosted", "open_weight", "local", "product_only", "preview"}
    for label, records in (
        ("provider", providers), ("model", models), ("benchmark", benchmarks),
        ("pricing observation", prices), ("performance observation", performance),
        ("operational observation", operational),
    ):
        for index, record in enumerate(records, 1):
            if not _official_https(record, allowed_hosts):
                errors.append(f"{label} {index} lacks complete provenance or an allow-listed official HTTPS source")
    for model in models:
        if model.get("provider_id") not in provider_ids:
            errors.append(f"model {model.get('id')} references an unknown provider")
        context_window = model.get("context_window_tokens")
        if context_window is not None and (not isinstance(context_window, int) or context_window <= 0):
            errors.append(f"model {model.get('id')} context window must be null or a positive integer")
        if model.get("release_date") is not None:
            try:
                date.fromisoformat(model["release_date"])
            except (TypeError, ValueError):
                errors.append(f"model {model.get('id')} release date must be null or ISO-8601")
        if model.get("status") not in {"active", "legacy", "deprecated", "retired", "preview"}:
            errors.append(f"model {model.get('id')} has an invalid status")
        if model.get("openness") not in {"open", "closed"}:
            errors.append(f"model {model.get('id')} has an invalid openness value")
        distributions = model.get("distribution_types")
        if not isinstance(distributions, list) or not distributions or any(value not in distribution_types for value in distributions):
            errors.append(f"model {model.get('id')} has invalid distribution types")
        for key in ("weights_available", "api_available", "product_available", "pricing_available"):
            if not isinstance(model.get(key), bool):
                errors.append(f"model {model.get('id')} needs explicit boolean {key}")
        for key in ("reasoning_capability", "multimodal_capability", "tool_use_capability", "coding_capability"):
            if model.get(key) is not None and not isinstance(model.get(key), bool):
                errors.append(f"model {model.get('id')} {key} must be boolean or null")
        if model.get("weights_available") and "open_weight" not in (distributions or []):
            errors.append(f"model {model.get('id')} exposes weights but is not open_weight")
        if model.get("openness") == "open" and not model.get("weights_available"):
            errors.append(f"open model {model.get('id')} must expose weights")
        if "product_only" in (distributions or []) and model.get("api_available"):
            errors.append(f"product-only model {model.get('id')} cannot claim API availability")
        if model.get("weights_available"):
            open_model = model.get("open_model")
            if not isinstance(open_model, dict) or not str(open_model.get("weights_url", "")).startswith("https://"):
                errors.append(f"open model {model.get('id')} needs an HTTPS weights URL")
        for field, field_source in model.get("fact_provenance", {}).items():
            if not _official_https({"provenance": field_source}, allowed_hosts):
                errors.append(f"model {model.get('id')} fact {field} lacks complete provenance or an allow-listed official HTTPS source")
    priced_model_ids = {item.get("model_id") for item in prices}
    for model in models:
        if bool(model.get("pricing_available")) != (model.get("id") in priced_model_ids):
            errors.append(f"model {model.get('id')} pricing_available does not match pricing observations")
    for price in prices:
        if price.get("model_id") not in model_ids:
            errors.append(f"pricing observation references unknown model {price.get('model_id')}")
        if price.get("currency") != "USD":
            errors.append(f"pricing observation for {price.get('model_id')} must use USD")
        if price.get("unit") not in {"usd_per_token", "usd_per_1k_tokens", "usd_per_1m_tokens"}:
            errors.append(f"pricing observation for {price.get('model_id')} has an unsupported unit")
        if any(not isinstance(price.get(key), (int, float)) or price[key] < 0 for key in ("input_price", "output_price")):
            errors.append(f"pricing observation for {price.get('model_id')} needs non-negative numeric prices")
        if price.get("cached_input_price") is not None and (not isinstance(price["cached_input_price"], (int, float)) or price["cached_input_price"] < 0):
            errors.append(f"pricing observation for {price.get('model_id')} has an invalid cached-input price")
    for observation in performance:
        if observation.get("model_id") not in model_ids:
            errors.append(f"performance observation references unknown model {observation.get('model_id')}")
        if observation.get("benchmark_id") not in benchmark_ids:
            errors.append(f"performance observation references unknown benchmark {observation.get('benchmark_id')}")
        if not observation.get("evaluation_configuration") or not observation.get("comparison_group"):
            errors.append(f"performance observation for {observation.get('model_id')} lacks comparability metadata")
    benchmark_groups = {"general_intelligence", "reasoning", "coding", "multimodal"}
    for benchmark in benchmarks:
        if benchmark.get("group") not in benchmark_groups:
            errors.append(f"benchmark {benchmark.get('id')} has an invalid benchmark group")
        if not benchmark.get("evaluator"):
            errors.append(f"benchmark {benchmark.get('id')} lacks an evaluator")
        if not isinstance(benchmark.get("higher_is_better"), bool):
            errors.append(f"benchmark {benchmark.get('id')} lacks metric direction")
        if "normalization_method" not in benchmark:
            errors.append(f"benchmark {benchmark.get('id')} lacks a normalization method declaration")
    expected_units = {"latency": "seconds_to_first_token", "throughput": "tokens_per_second"}
    for observation in operational:
        metric = observation.get("metric")
        if observation.get("model_id") not in model_ids:
            errors.append(f"operational observation references unknown model {observation.get('model_id')}")
        if metric not in expected_units or observation.get("unit") != expected_units.get(metric):
            errors.append(f"operational observation for {observation.get('model_id')} has an incompatible metric unit")
        if not isinstance(observation.get("value"), (int, float)) or observation.get("value", 0) < 0:
            errors.append(f"operational observation for {observation.get('model_id')} needs a non-negative numeric value")
        if not observation.get("evaluation_configuration") or not observation.get("comparison_group"):
            errors.append(f"operational observation for {observation.get('model_id')} lacks comparability metadata")
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
