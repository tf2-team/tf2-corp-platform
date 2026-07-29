#!/usr/bin/env python3
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALLOWED_OUTCOMES = {"success", "partial", "failed"}
RUNTIME_FIELDS = (
    "incident_id",
    "affected_services",
    "log_signatures",
    "trace_signatures",
    "metric_ratios",
    "actions_taken",
)
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(secret|token|password|passwd|api[_-]?key|authorization)\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?i)\bcustomer[_-]?id\b"),
]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_action_catalog(path: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    catalog: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}] must be an object")
        action_id = item.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ValueError(f"{path}[{index}] has invalid action_id")
        if action_id in catalog:
            raise ValueError(f"duplicate action_id in catalog: {action_id}")
        catalog[action_id] = item
    return catalog


def _contains_sensitive_text(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _canonical_record_key(record: dict[str, Any]) -> tuple[Any, ...]:
    metric_items = tuple(sorted((record.get("metric_ratios") or {}).items()))
    return (
        tuple(sorted(record.get("affected_services") or [])),
        tuple(sorted(record.get("log_signatures") or [])),
        tuple(sorted(record.get("trace_signatures") or [])),
        metric_items,
    )


def _runtime_record(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record[field] for field in RUNTIME_FIELDS}


def _validate_record(
    record: Any,
    index: int,
    action_catalog: dict[str, dict[str, Any]],
    seen_ids: set[str],
    seen_fingerprints: dict[tuple[Any, ...], str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"record[{index}] must be an object"]

    incident_id = record.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        errors.append(f"record[{index}] incident_id is required")
    elif incident_id in seen_ids:
        errors.append(f"{incident_id}: duplicate incident_id")
    else:
        seen_ids.add(incident_id)

    affected = record.get("affected_services")
    if not isinstance(affected, list) or not affected:
        errors.append(f"{incident_id}: affected_services must be a non-empty array")
    elif len(set(affected)) != len(affected) or not all(isinstance(item, str) and item for item in affected):
        errors.append(f"{incident_id}: affected_services must contain unique non-empty strings")

    for field in ("log_signatures", "trace_signatures"):
        signatures = record.get(field)
        if not isinstance(signatures, list):
            errors.append(f"{incident_id}: {field} must be an array")
            continue
        if len(set(signatures)) != len(signatures) or not all(isinstance(item, str) and item for item in signatures):
            errors.append(f"{incident_id}: {field} must contain unique non-empty strings")
            continue
        for signature in signatures:
            if len(signature) > 128:
                errors.append(f"{incident_id}: {field} value exceeds 128 chars: {signature}")
            if _contains_sensitive_text(signature):
                errors.append(f"{incident_id}: {field} contains sensitive-looking text: {signature}")

    metric_ratios = record.get("metric_ratios")
    if not isinstance(metric_ratios, dict) or not metric_ratios:
        errors.append(f"{incident_id}: metric_ratios must be a non-empty object")
    else:
        for metric, value in metric_ratios.items():
            if not isinstance(metric, str) or not metric:
                errors.append(f"{incident_id}: metric_ratios contains an invalid metric name")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                errors.append(f"{incident_id}: metric ratio for {metric!r} must be finite and positive")

    actions = record.get("actions_taken")
    if not isinstance(actions, list) or not actions:
        errors.append(f"{incident_id}: actions_taken must be a non-empty array")
    else:
        for action_index, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"{incident_id}: actions_taken[{action_index}] must be an object")
                continue
            action_id = action.get("action_id")
            target = action.get("target")
            outcome = action.get("outcome")
            catalog_action = action_catalog.get(action_id)
            if catalog_action is None:
                errors.append(f"{incident_id}: action_id {action_id!r} does not exist in actions catalog")
            elif target != catalog_action.get("target"):
                errors.append(
                    f"{incident_id}: target {target!r} does not match catalog target {catalog_action.get('target')!r}"
                )
            if outcome not in ALLOWED_OUTCOMES:
                errors.append(f"{incident_id}: outcome {outcome!r} must be one of {sorted(ALLOWED_OUTCOMES)}")

    if all(field in record for field in RUNTIME_FIELDS):
        fingerprint = _canonical_record_key(record)
        previous_id = seen_fingerprints.get(fingerprint)
        if previous_id is not None:
            errors.append(f"{incident_id}: duplicates service/signatures/metric ratios with {previous_id}")
        else:
            seen_fingerprints[fingerprint] = str(incident_id)

    return errors


def _validate_runtime_schema(records: list[dict[str, Any]]) -> list[str]:
    try:
        from aiops.schemas import IncidentHistoryRecord
    except Exception as exc:
        return [f"could not import IncidentHistoryRecord: {exc}"]

    errors: list[str] = []
    for record in records:
        try:
            IncidentHistoryRecord.model_validate(record)
        except Exception as exc:
            errors.append(f"{record.get('incident_id')}: runtime schema validation failed: {exc}")
    return errors


def _print_summary(records: list[dict[str, Any]], valid_actions: int, errors: list[str]) -> None:
    case_counts = Counter(str(record.get("case", "uncategorized")) for record in records)
    print(f"records={len(records)}")
    print(f"valid_actions={valid_actions}")
    print("scenarios:")
    for case, count in sorted(case_counts.items()):
        print(f"  {case}: {count}")
    if errors:
        print("errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("errors=0")


def generate(seed_path: Path, actions_path: Path) -> tuple[list[dict[str, Any]], list[str], int]:
    action_catalog = _load_action_catalog(actions_path)
    raw = _load_json(seed_path)
    if not isinstance(raw, list):
        raise ValueError(f"{seed_path} must contain a JSON array")

    seen_ids: set[str] = set()
    seen_fingerprints: dict[tuple[Any, ...], str] = {}
    errors: list[str] = []
    valid_actions = 0

    for index, record in enumerate(raw):
        record_errors = _validate_record(record, index, action_catalog, seen_ids, seen_fingerprints)
        errors.extend(record_errors)
        if isinstance(record, dict):
            for action in record.get("actions_taken") or []:
                if isinstance(action, dict) and action.get("action_id") in action_catalog:
                    valid_actions += 1

    runtime_records = [_runtime_record(record) for record in raw if isinstance(record, dict) and all(field in record for field in RUNTIME_FIELDS)]
    runtime_records.sort(key=lambda item: item["incident_id"])
    errors.extend(_validate_runtime_schema(runtime_records))
    return runtime_records, errors, valid_actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and validate AIOps incident history from CDO seed data.")
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "config" / "incidents_history.json")
    parser.add_argument("--check", action="store_true", help="Validate only; do not write output.")
    args = parser.parse_args(argv)

    records, errors, valid_actions = generate(args.seed, args.actions)
    _print_summary(_load_json(args.seed), valid_actions, errors)
    if errors:
        return 1
    if not args.check:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
