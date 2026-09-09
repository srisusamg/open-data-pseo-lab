"""Deterministic field-level curation, merge, freshness, and reporting."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from copy import deepcopy
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

AUTOMATION_STATUSES = {"AUTOMATED", "PARTIALLY_AUTOMATED", "MANUAL_REQUIRED", "DERIVED"}
LOCK_MODES = {"NONE", "PREFERRED", "LOCKED"}
CONFIDENCE = {"low", "medium", "high"}
STATUSES = {"verified", "unverified", "provider_reported"}
CURATED_COLUMNS = ("model_id", "field_id", "value", "unit", "source_name", "source_url", "observed_at", "curated_at", "confidence", "status", "notes", "lock_mode")


def load_field_registry(path: Path) -> list[dict]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    ids = [item.get("field_id") for item in registry]
    if len(ids) != len(set(ids)):
        raise ValueError("field registry contains duplicate field_id values")
    required = {"field_id", "display_name", "category", "unit", "data_type", "automation_status", "priority"}
    for item in registry:
        if not required.issubset(item) or item["automation_status"] not in AUTOMATION_STATUSES or item["priority"] not in {"P0", "P1", "P2"}:
            raise ValueError(f"invalid field registry entry: {item.get('field_id')}")
    return registry


def load_freshness_policy(path: Path) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    for category, rule in policy.items():
        if not isinstance(rule.get("fresh_after_days"), int) or not isinstance(rule.get("stale_after_days"), int) or rule["fresh_after_days"] >= rule["stale_after_days"]:
            raise ValueError(f"invalid freshness policy for {category}")
    return policy


def _parse_value(raw: str, data_type: str):
    if raw == "":
        return None
    if data_type == "number":
        return float(raw)
    if data_type == "integer":
        value = float(raw)
        if not value.is_integer():
            raise ValueError("must be an integer")
        return int(value)
    if data_type == "boolean":
        if raw.strip().lower() not in {"true", "false"}:
            raise ValueError("must be true or false")
        return raw.strip().lower() == "true"
    if data_type == "date":
        date.fromisoformat(raw)
    return raw


def validate_curated_rows(rows: list[dict], registry: list[dict], model_ids: set[str]) -> list[str]:
    errors, seen = [], set()
    fields = {item["field_id"]: item for item in registry}
    for line, row in enumerate(rows, 2):
        key = (row.get("model_id", "").strip(), row.get("field_id", "").strip())
        if key in seen:
            errors.append(f"row {line}: duplicate fact {key[0]}/{key[1]}")
        seen.add(key)
        if key[0] not in model_ids:
            errors.append(f"row {line}: unknown model_id {key[0]}")
        field = fields.get(key[1])
        if not field:
            errors.append(f"row {line}: unknown field_id {key[1]}")
            continue
        if field["automation_status"] == "DERIVED":
            errors.append(f"row {line}: derived field {key[1]} cannot be curated")
        raw = row.get("value", "").strip()
        if raw:
            for column in ("source_name", "source_url", "observed_at", "curated_at", "confidence", "status"):
                if not row.get(column, "").strip():
                    errors.append(f"row {line}: populated fact requires {column}")
            try:
                _parse_value(raw, field["data_type"])
            except (ValueError, TypeError) as exc:
                errors.append(f"row {line}: invalid value for {key[1]} ({exc})")
            url = urlparse(row.get("source_url", ""))
            if url.scheme != "https" or not url.netloc:
                errors.append(f"row {line}: source_url must be HTTPS")
            for column in ("observed_at", "curated_at"):
                try:
                    date.fromisoformat(row.get(column, ""))
                except (TypeError, ValueError):
                    errors.append(f"row {line}: {column} must be ISO-8601")
            if row.get("confidence", "").lower() not in CONFIDENCE:
                errors.append(f"row {line}: invalid confidence")
            if row.get("status", "").lower() not in STATUSES:
                errors.append(f"row {line}: invalid status")
            if row.get("unit", "").strip() != field["unit"]:
                errors.append(f"row {line}: unit must be {field['unit']}")
        if (row.get("lock_mode") or "PREFERRED").upper() not in LOCK_MODES:
            errors.append(f"row {line}: invalid lock_mode")
        if (row.get("lock_mode") or "PREFERRED").upper() == "LOCKED" and row.get("status", "").lower() != "verified":
            errors.append(f"row {line}: locked facts must be verified")
    return errors


def load_curated_facts(path: Path, registry: list[dict], model_ids: set[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CURATED_COLUMNS:
            raise ValueError("curated CSV columns must exactly match the documented schema")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    errors = validate_curated_rows(rows, registry, model_ids)
    if errors:
        raise ValueError("invalid curated facts: " + "; ".join(errors))
    fields = {item["field_id"]: item for item in registry}
    return [{**row, "value": _parse_value(row["value"], fields[row["field_id"]]["data_type"]), "source_type": "human_curated", "lock_mode": (row["lock_mode"] or "PREFERRED").upper(), "confidence": row["confidence"].lower(), "status": row["status"].lower()} for row in rows if row["value"] != ""]


def _fact(model_id: str, field_id: str, value, unit: str, provenance: dict) -> dict:
    return {"model_id": model_id, "field_id": field_id, "value": value, "unit": unit, "source_type": "automated", "source_name": provenance["source_name"], "source_url": provenance["source_url"], "observed_at": provenance["observation_date"], "retrieved_at": provenance["retrieved_at"][:10], "confidence": provenance["confidence"], "status": provenance["status"]}


def automated_facts(dataset: dict, registry: list[dict]) -> list[dict]:
    facts = []
    for model in dataset["models"]:
        mid, provenance = model["id"], model["provenance"]
        direct = {"release_date": model.get("release_date"), "context_window_tokens": model.get("context_window_tokens"), "availability": model.get("status"), "open_weight": model.get("weights_available"), "modality": ", ".join(model.get("capabilities", [])) or None, "license_notes": model.get("license")}
        if model.get("open_model"):
            direct["parameter_count_billions"] = model["open_model"].get("parameter_count_billions")
        for field_id, value in direct.items():
            if value is not None:
                field = next(item for item in registry if item["field_id"] == field_id)
                facts.append(_fact(mid, field_id, value, field["unit"], model["fact_provenance"].get(field_id, provenance)))
    for item in dataset["pricing_observations"]:
        facts.extend((_fact(item["model_id"], "input_price_per_1m", item["input_price_per_million_tokens"], "USD_per_1M_tokens", item["provenance"]), _fact(item["model_id"], "output_price_per_1m", item["output_price_per_million_tokens"], "USD_per_1M_tokens", item["provenance"])))
    benchmark_fields = {item["benchmark_id"]: item for item in registry if item.get("benchmark_id")}
    for item in dataset["performance_observations"]:
        field = benchmark_fields.get(item["benchmark_id"])
        if field:
            facts.append(_fact(item["model_id"], field["field_id"], item["value"], item["unit"], item["provenance"]))
    operational_fields = {item["operational_metric"]: item for item in registry if item.get("operational_metric")}
    for item in dataset.get("operational_observations", []):
        field = operational_fields.get(item["metric"])
        if field:
            facts.append(_fact(item["model_id"], field["field_id"], item["value"], item["unit"], item["provenance"]))
    return sorted(facts, key=lambda item: (item["model_id"], item["field_id"], item["observed_at"], str(item["value"])))


def freshness_status(fact: dict, field: dict, policy: dict, as_of_date: str) -> str:
    observed = fact.get("observed_at")
    if not observed:
        return "STALE"
    age = max(0, (date.fromisoformat(as_of_date) - date.fromisoformat(observed)).days)
    rule = policy[field["category"]]
    if age <= rule["fresh_after_days"]:
        return "FRESH"
    if age <= rule["stale_after_days"]:
        return "AGING"
    return "STALE"


def _canonical_record(fact: dict, field: dict, policy: dict, as_of_date: str) -> dict:
    return {"value": fact["value"], "unit": fact.get("unit") or field["unit"], "selected_source_type": fact["source_type"], "source_name": fact["source_name"], "source_url": fact["source_url"], "observed_at": fact["observed_at"], "confidence": fact["confidence"], "status": fact["status"], "freshness": freshness_status(fact, field, policy, as_of_date), "lock_mode": fact.get("lock_mode", "NONE")}


def merge_facts(automated: list[dict], curated: list[dict], registry: list[dict], policy: dict, as_of_date: str) -> tuple[dict, list[dict]]:
    fields = {item["field_id"]: item for item in registry}
    auto_by_key, human_by_key = defaultdict(list), {}
    for fact in automated:
        auto_by_key[(fact["model_id"], fact["field_id"])].append(fact)
    for fact in curated:
        human_by_key[(fact["model_id"], fact["field_id"])] = fact
    canonical, conflicts = defaultdict(dict), []
    for key in sorted(set(auto_by_key) | set(human_by_key)):
        field = fields[key[1]]
        autos = sorted(auto_by_key.get(key, []), key=lambda item: ({"low": 0, "medium": 1, "high": 2}.get(item["confidence"], 0), item["observed_at"], str(item["value"])), reverse=True)
        auto, human = (autos[0] if autos else None), human_by_key.get(key)
        selected, reason = auto or human, "automated_only" if auto else "human_only"
        if human:
            human_fresh = freshness_status(human, field, policy, as_of_date) != "STALE"
            if human["lock_mode"] == "LOCKED":
                selected, reason = human, "human_locked"
            elif human["status"] == "verified" and human_fresh and human["lock_mode"] != "NONE":
                selected, reason = human, "human_verified_override" if auto else "human_only"
            elif auto:
                selected, reason = auto, "automated_preferred_or_human_stale"
            else:
                selected, reason = human, "human_only_stale"
        if not auto and human and human["status"] != "verified" and human["lock_mode"] != "LOCKED":
            continue
        canonical[key[0]][key[1]] = _canonical_record(selected, field, policy, as_of_date)
        if auto and human and auto["value"] != human["value"]:
            difference = None
            if isinstance(auto["value"], (int, float)) and isinstance(human["value"], (int, float)):
                difference = round(float(human["value"]) - float(auto["value"]), 8)
            conflicts.append({"model_id": key[0], "field_id": key[1], "automated_value": auto["value"], "automated_source": auto["source_name"], "human_value": human["value"], "human_source": human["source_name"], "selected_value": selected["value"], "selected_source": selected["source_type"], "reason": reason, "difference": difference})
    return dict(canonical), conflicts


def _provenance(record: dict, metric_id: str) -> dict:
    return {"source_name": record["source_name"], "source_url": record["source_url"], "source_metric_id": metric_id, "observation_date": record["observed_at"], "effective_date": record["observed_at"], "retrieved_at": record["observed_at"] + "T00:00:00Z", "source_type": record["selected_source_type"], "confidence": record["confidence"], "status": record["status"]}


def apply_canonical(dataset: dict, canonical: dict, registry: list[dict]) -> dict:
    result = deepcopy(dataset)
    benchmark_fields = {item["field_id"]: item for item in registry if item.get("benchmark_id")}
    operational_fields = {item["field_id"]: item for item in registry if item.get("operational_metric")}
    models = {item["id"]: item for item in result["models"]}
    for mid, facts in canonical.items():
        model = models[mid]
        model["canonical_facts"] = facts
        for field_id, target in (("release_date", "release_date"), ("context_window_tokens", "context_window_tokens"), ("availability", "status"), ("open_weight", "weights_available"), ("license_notes", "license")):
            if field_id in facts:
                model[target] = facts[field_id]["value"]
                model["fact_provenance"][target] = _provenance(facts[field_id], f"canonical:{mid}:{field_id}")
        if "parameter_count_billions" in facts:
            model.setdefault("open_model", {})["parameter_count_billions"] = facts["parameter_count_billions"]["value"]
    price_by_model = {item["model_id"]: item for item in result["pricing_observations"]}
    result["pricing_observations"] = []
    for mid, facts in canonical.items():
        if "input_price_per_1m" in facts and "output_price_per_1m" in facts:
            base = price_by_model.get(mid, {})
            first = facts["input_price_per_1m"]
            result["pricing_observations"].append({"model_id": mid, "input_price_per_million_tokens": facts["input_price_per_1m"]["value"], "output_price_per_million_tokens": facts["output_price_per_1m"]["value"], "cached_input_price_per_million_tokens": base.get("cached_input_price_per_million_tokens"), "unit": "usd_per_1m_tokens", "currency": "USD", "pricing_tier": base.get("pricing_tier", "curated"), "maximum_prompt_tokens_for_rate": base.get("maximum_prompt_tokens_for_rate"), "provenance": _provenance(first, f"canonical:{mid}:pricing")})
    perf_by_key = {(item["model_id"], item["benchmark_id"]): item for item in result["performance_observations"]}
    for mid, facts in canonical.items():
        for field_id, field in benchmark_fields.items():
            if field_id not in facts:
                continue
            record, key = facts[field_id], (mid, field["benchmark_id"])
            base = perf_by_key.get(key)
            if base:
                base.update(value=record["value"], unit=record["unit"], source=record["source_url"], evaluation_date=record["observed_at"], provenance=_provenance(record, f"canonical:{mid}:{field_id}"))
            else:
                benchmark = next(item for item in result["benchmarks"] if item["id"] == field["benchmark_id"])
                perf_by_key[key] = {"model_id": mid, "benchmark_id": benchmark["id"], "value": record["value"], "unit": record["unit"], "evaluation_configuration": "Human-curated published result; see source", "comparison_group": f"curated:{benchmark['id']}", "benchmark_name": benchmark["name"], "benchmark_version": benchmark["version"], "evaluation_date": record["observed_at"], "source": record["source_url"], "evaluator": benchmark["evaluator"], "metric_direction": "higher_is_better" if benchmark["higher_is_better"] else "lower_is_better", "normalization_method": benchmark["normalization_method"], "provenance": _provenance(record, f"canonical:{mid}:{field_id}")}
    result["performance_observations"] = sorted(perf_by_key.values(), key=lambda item: (item["model_id"], item["benchmark_id"]))
    operational_by_key = {(item["model_id"], item["metric"]): item for item in result.get("operational_observations", [])}
    for mid, facts in canonical.items():
        for field_id, field in operational_fields.items():
            if field_id in facts:
                record = facts[field_id]
                operational_by_key[(mid, field["operational_metric"])] = {"model_id": mid, "metric": field["operational_metric"], "value": record["value"], "unit": record["unit"], "evaluation_configuration": "Canonical sourced observation", "comparison_group": "canonical-curated", "provenance": _provenance(record, f"canonical:{mid}:{field_id}")}
    result["operational_observations"] = sorted(operational_by_key.values(), key=lambda item: (item["model_id"], item["metric"]))
    result["canonical_facts"] = canonical
    return result


def build_reports(dataset: dict, canonical: dict, conflicts: list[dict], registry: list[dict], as_of_date: str) -> dict:
    providers = {item["id"]: item["name"] for item in dataset["providers"]}
    conflicts_by_model = defaultdict(int)
    for item in conflicts:
        conflicts_by_model[item["model_id"]] += 1
    supported = [item for item in registry if item["automation_status"] != "DERIVED"]
    coverage, queue, workbook, template = [], [], [], []
    for importance, model in enumerate(dataset["models"]):
        facts = canonical.get(model["id"], {})
        populated = [field for field in supported if field["field_id"] in facts]
        stale = [field for field in populated if facts[field["field_id"]]["freshness"] == "STALE"]
        missing = [field for field in supported if field["field_id"] not in facts]
        sources = [facts[field["field_id"]]["selected_source_type"] for field in populated]
        required = {field["field_id"] for field in supported if field["priority"] == "P0"}
        eligibility = required.issubset(facts) and all(facts[key]["freshness"] != "STALE" for key in required)
        coverage.append({"model_id": model["id"], "model_name": model["name"], "provider": providers[model["provider_id"]], "total_supported_fields": len(supported), "fields_populated": len(populated), "fields_missing": len(missing), "coverage_percent": round(len(populated) / len(supported) * 100, 1), "automated_fields": sources.count("automated"), "human_curated_fields": sources.count("human_curated"), "derived_fields": 0, "stale_fields": len(stale), "conflicting_fields": conflicts_by_model[model["id"]], "ranking_eligible": eligibility, "ranking_ineligible_reason": "" if eligibility else "missing or stale P0 facts", "last_updated": max((fact["observed_at"] for fact in facts.values()), default="")})
        for field in missing + stale:
            current = facts.get(field["field_id"], {})
            row = {"model_id": model["id"], "model_name": model["name"], "provider": providers[model["provider_id"]], "field_id": field["field_id"], "field_name": field["display_name"], "automation_status": field["automation_status"], "current_value": current.get("value", ""), "current_source": current.get("source_name", ""), "missing_or_stale": "STALE" if current else "MISSING", "suggested_source_type": field.get("preferred_source", "manual_research"), "priority": field["priority"], "notes": ""}
            row["_importance"] = importance
            queue.append(row)
        def cell(field_id, key="value"):
            return facts.get(field_id, {}).get(key, "")
        workbook.append({"model_id": model["id"], "model_name": model["name"], "provider": providers[model["provider_id"]], "release_date": cell("release_date"), "release_date_source": cell("release_date", "source_name"), "input_price": cell("input_price_per_1m"), "input_price_source": cell("input_price_per_1m", "source_name"), "input_price_status": cell("input_price_per_1m", "freshness"), "output_price": cell("output_price_per_1m"), "output_price_source": cell("output_price_per_1m", "source_name"), "output_price_status": cell("output_price_per_1m", "freshness"), "intelligence_score": cell("intelligence_score"), "intelligence_source": cell("intelligence_score", "source_name"), "intelligence_status": cell("intelligence_score", "freshness"), "reasoning_score": cell("reasoning_score"), "reasoning_source": cell("reasoning_score", "source_name"), "reasoning_status": cell("reasoning_score", "freshness"), "coding_score": cell("coding_score"), "coding_source": cell("coding_score", "source_name"), "coding_status": cell("coding_score", "freshness"), "tokens_per_second": cell("tokens_per_second"), "speed_source": cell("tokens_per_second", "source_name"), "speed_status": cell("tokens_per_second", "freshness"), "latency": cell("latency_seconds"), "latency_source": cell("latency_seconds", "source_name"), "latency_status": cell("latency_seconds", "freshness"), "context_window": cell("context_window_tokens"), "context_source": cell("context_window_tokens", "source_name"), "context_status": cell("context_window_tokens", "freshness"), "open_weight": cell("open_weight"), "open_weight_source": cell("open_weight", "source_name"), "parameter_count": cell("parameter_count_billions"), "parameter_count_source": cell("parameter_count_billions", "source_name"), "overall_coverage": coverage[-1]["coverage_percent"], "manual_research_needed": len(missing) + len(stale)})
    queue.sort(key=lambda row: (row["priority"], row["_importance"], row["model_name"], row["field_id"]))
    for row in queue:
        row.pop("_importance")
        template.append({key: row.get(key, "") for key in ("model_id", "field_id")} | {"value": "", "unit": next(item["unit"] for item in registry if item["field_id"] == row["field_id"]), "source_name": "", "source_url": "", "observed_at": "", "curated_at": as_of_date, "confidence": "", "status": "verified", "notes": row["missing_or_stale"], "lock_mode": "PREFERRED"})
    return {"coverage": coverage, "queue": queue, "workbook": workbook, "template": template}


def csv_text(rows: list[dict], columns: tuple[str, ...] | None = None) -> str:
    if columns is None:
        columns = tuple(rows[0]) if rows else tuple()
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
