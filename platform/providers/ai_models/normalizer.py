"""Normalize curated provider records into canonical economics observations."""

from __future__ import annotations

from copy import deepcopy

from platform.core.provenance import dated_provenance
from platform.providers.ai_models.schema import (
    Benchmark, Model, PerformanceObservation, PricingObservation, Provider,
)


def _provenance(item: dict) -> dict:
    value = item["provenance"]
    return dated_provenance(
        value["source_name"], value["source_url"], value["source_metric_id"],
        observation_date=value["observation_date"], effective_date=value["effective_date"],
        retrieved_at=value["retrieved_at"], source_type=value["source_type"],
        confidence=value["confidence"], status=value["status"],
    )


def normalize_price(value: int | float, unit: str) -> float:
    """Convert an explicitly supported token price into USD per 1M tokens."""
    multipliers = {
        "usd_per_token": 1_000_000,
        "usd_per_1k_tokens": 1_000,
        "usd_per_1m_tokens": 1,
    }
    if unit not in multipliers:
        raise ValueError(f"incompatible pricing unit: {unit}")
    return round(float(value) * multipliers[unit], 8)


def normalize_catalog(catalog: dict) -> dict:
    providers: list[Provider] = []
    for item in catalog["providers"]:
        providers.append({**{key: item[key] for key in ("id", "slug", "name")}, "provenance": _provenance(item)})
    models: list[Model] = []
    for item in catalog["models"]:
        provenance = _provenance(item)
        fields = (
            "id", "slug", "name", "provider_id", "family", "release_date", "status",
            "distribution_types", "openness", "license", "weights_available",
            "context_window_tokens", "reasoning_capability", "multimodal_capability",
            "tool_use_capability", "coding_capability", "api_available", "product_available",
            "product_availability", "pricing_available", "capabilities", "external_ids",
        )
        model = {**{key: deepcopy(item[key]) for key in fields}, "provenance": provenance}
        if "open_model" in item:
            model["open_model"] = deepcopy(item["open_model"])
        model["fact_provenance"] = {key: deepcopy(provenance) for key in fields if key not in {"id", "slug"}}
        if "open_model" in item:
            model["fact_provenance"]["open_model"] = deepcopy(provenance)
        for key, value in item.get("fact_provenance", {}).items():
            model["fact_provenance"][key] = dated_provenance(
                value["source_name"], value["source_url"], value["source_metric_id"],
                observation_date=value["observation_date"], effective_date=value["effective_date"],
                retrieved_at=value["retrieved_at"], source_type=value["source_type"],
                confidence=value["confidence"], status=value["status"],
            )
        models.append(model)
    benchmarks: list[Benchmark] = []
    for item in catalog["benchmarks"]:
        benchmarks.append({
            **{key: item[key] for key in ("id", "slug", "name", "version", "unit", "higher_is_better", "description")},
            "provenance": _provenance(item),
        })
    pricing: list[PricingObservation] = []
    for item in catalog["pricing_observations"]:
        pricing.append({
            "model_id": item["model_id"],
            "input_price_per_million_tokens": normalize_price(item["input_price"], item["unit"]),
            "output_price_per_million_tokens": normalize_price(item["output_price"], item["unit"]),
            "cached_input_price_per_million_tokens": normalize_price(item["cached_input_price"], item["unit"]) if item.get("cached_input_price") is not None else None,
            "unit": "usd_per_1m_tokens", "currency": item["currency"], "pricing_tier": item["pricing_tier"],
            "maximum_prompt_tokens_for_rate": item.get("maximum_prompt_tokens_for_rate"),
            "provenance": _provenance(item),
        })
    performance: list[PerformanceObservation] = []
    for item in catalog["performance_observations"]:
        performance.append({
            **{key: item[key] for key in (
                "model_id", "benchmark_id", "value", "unit", "evaluation_configuration", "comparison_group",
            )},
            "provenance": _provenance(item),
        })
    return {
        "schema_version": catalog["schema_version"], "retrieved_at": catalog["retrieved_at"],
        "providers": providers, "models": models, "benchmarks": benchmarks,
        "pricing_observations": pricing, "performance_observations": performance,
    }
