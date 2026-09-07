"""Canonical source provenance carried by every normalized fact."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class Provenance(TypedDict):
    source_name: str
    source_url: str
    source_metric_id: str
    observation_date: NotRequired[str]
    effective_date: NotRequired[str]
    retrieved_at: NotRequired[str]
    source_type: NotRequired[str]
    confidence: NotRequired[str]
    status: NotRequired[str]


def provenance(source_name: str, source_url: str, source_metric_id: str) -> Provenance:
    if not source_name or not source_url or not source_metric_id:
        raise ValueError("provenance requires source name, URL, and source metric id")
    return {
        "source_name": source_name,
        "source_url": source_url,
        "source_metric_id": source_metric_id,
    }


def dated_provenance(
    source_name: str, source_url: str, source_metric_id: str, *,
    observation_date: str, effective_date: str, retrieved_at: str,
    source_type: str, confidence: str = "high", status: str = "verified",
) -> Provenance:
    """Create the richer provenance required by point-in-time catalog facts."""
    result = provenance(source_name, source_url, source_metric_id)
    result.update({
        "observation_date": observation_date,
        "effective_date": effective_date,
        "retrieved_at": retrieved_at,
        "source_type": source_type,
        "confidence": confidence,
        "status": status,
    })
    return result


def complete_provenance(records: list[dict], required_fields: tuple[str, ...] = ()) -> bool:
    """Accept canonical fact provenance or an explicit compatibility field list."""
    if not records:
        return False
    if required_fields:
        return all(all(record.get(field) not in (None, "") for field in required_fields) for record in records)
    return all(
        isinstance(record.get("provenance"), dict)
        and all(record["provenance"].get(field) not in (None, "")
                for field in ("source_name", "source_url", "source_metric_id"))
        for record in records
    )
