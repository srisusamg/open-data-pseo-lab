"""Validate the provider-owned World Bank snapshot contract."""

from __future__ import annotations

from platform.core.derivations import calculate_derived_metrics
from platform.providers.world_bank.client import HISTORY_OBSERVATIONS, SCHEMA_VERSION


def validate_snapshot(snapshot: dict, entities: list[dict], metrics: list[dict]) -> list[str]:
    errors: list[str] = []
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"snapshot schema_version must be {SCHEMA_VERSION}")
    series = snapshot.get("series")
    if not isinstance(series, list):
        return errors + ["snapshot series must be a list"]
    expected_pairs = {(entity["code"], metric["code"]) for entity in entities for metric in metrics}
    actual_pairs = {(item.get("country_code"), item.get("indicator_code")) for item in series}
    if actual_pairs != expected_pairs or len(series) != len(expected_pairs):
        errors.append("snapshot must contain exactly one series for every configured country/indicator pair")
    for item in series:
        label = f"{item.get('country_code')} / {item.get('indicator_code')}"
        observations = item.get("observations")
        if not isinstance(observations, list):
            errors.append(f"{label}: observations must be a list")
            continue
        if len(observations) > HISTORY_OBSERVATIONS:
            errors.append(f"{label}: expected no more than {HISTORY_OBSERVATIONS} normalized observations")
        years = [row.get("year") for row in observations]
        if any(not isinstance(year, int) for year in years):
            errors.append(f"{label}: every observation year must be an integer")
        elif years != sorted(years, reverse=True) or len(years) != len(set(years)):
            errors.append(f"{label}: observation years must be unique and newest first")
        if any(not isinstance(row.get("value"), (int, float)) or isinstance(row.get("value"), bool) for row in observations):
            errors.append(f"{label}: every observation value must be numeric")
        expected_latest = observations[0] if observations else None
        if item.get("latest_observation") != expected_latest:
            errors.append(f"{label}: latest_observation must match the newest historical observation")
        if item.get("derived_metrics") != calculate_derived_metrics(observations):
            errors.append(f"{label}: derived_metrics do not match deterministic recalculation")
    return errors
