"""Map the World Bank snapshot schema into provider-neutral platform series."""

from __future__ import annotations

from platform.core.derivations import calculate_derived_metrics
from platform.core.entities import entity_from_config, metric_from_config
from platform.core.provenance import provenance


def normalize_snapshot(snapshot: dict, entities: list[dict], metrics: list[dict]) -> dict:
    """Return canonical entities, metrics, facts, and series for standard recipes."""
    canonical_entities = [entity_from_config(item) for item in entities]
    canonical_metrics = [metric_from_config(item) for item in metrics]
    entities_by_id = {item["id"]: item for item in canonical_entities}
    metrics_by_id = {item["id"]: item for item in canonical_metrics}
    normalized_series = []
    facts = []
    for source_series in snapshot["series"]:
        entity_id = source_series["country_code"]
        metric_id = source_series["indicator_code"]
        source = provenance(snapshot["source"]["name"], source_series["source_url"], metric_id)
        observations = list(source_series.get("observations", []))
        series = {
            "entity": entities_by_id[entity_id], "metric": metrics_by_id[metric_id],
            "observations": observations,
            "latest_observation": observations[0] if observations else None,
            "derived_metrics": calculate_derived_metrics(observations),
            "provenance": source,
        }
        normalized_series.append(series)
        facts.extend({
            "entity_id": entity_id, "metric_id": metric_id, "value": row["value"],
            "unit": metrics_by_id[metric_id]["unit"], "observation_year": row["year"],
            "provenance": source,
        } for row in observations)
    return {
        "retrieved_at": snapshot["retrieved_at"], "source": snapshot["source"],
        "entities": canonical_entities, "metrics": canonical_metrics,
        "series": normalized_series, "facts": facts,
    }
