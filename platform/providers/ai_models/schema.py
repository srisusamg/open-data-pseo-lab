"""Canonical AI model economics records exposed by the provider boundary."""

from __future__ import annotations

from typing import Literal, TypedDict

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
    release_date: str
    status: Literal["active", "legacy", "deprecated", "retired", "preview"]
    openness: Literal["open", "closed"]
    context_window_tokens: int
    capabilities: list[str]
    external_ids: dict[str, str]
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
