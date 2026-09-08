"""Canonical AI model economics records exposed by the provider boundary."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from platform.core.provenance import Provenance


class Provider(TypedDict):
    id: str
    slug: str
    name: str
    provenance: Provenance


class Model(TypedDict):
    id: str
    slug: str
    name: str
    provider_id: str
    family: str
    release_date: str | None
    status: Literal["active", "legacy", "deprecated", "retired", "preview"]
    openness: Literal["open", "closed"]
    distribution_types: list[Literal["api", "hosted", "open_weight", "local", "product_only", "preview"]]
    license: str | None
    weights_available: bool
    context_window_tokens: int | None
    reasoning_capability: bool | None
    multimodal_capability: bool | None
    tool_use_capability: bool | None
    coding_capability: bool | None
    api_available: bool
    product_available: bool
    product_availability: list[str]
    pricing_available: bool
    capabilities: list[str]
    external_ids: dict[str, str]
    open_model: NotRequired[dict]
    fact_provenance: dict[str, Provenance]
    provenance: Provenance


class Benchmark(TypedDict):
    id: str
    slug: str
    name: str
    version: str
    unit: str
    higher_is_better: bool
    description: str
    provenance: Provenance


class PricingObservation(TypedDict):
    model_id: str
    input_price_per_million_tokens: float
    output_price_per_million_tokens: float
    cached_input_price_per_million_tokens: float | None
    unit: Literal["usd_per_1m_tokens"]
    currency: str
    pricing_tier: str
    maximum_prompt_tokens_for_rate: int | None
    provenance: Provenance


class PerformanceObservation(TypedDict):
    model_id: str
    benchmark_id: str
    value: float
    unit: str
    evaluation_configuration: str
    comparison_group: str
    provenance: Provenance
