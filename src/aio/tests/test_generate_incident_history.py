#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.remediation.catalog import ActionCatalog
from scripts.generate_incident_history import generate


def test_generate_incident_history_seed_passes_contract() -> None:
    root = Path(__file__).resolve().parents[1]

    records, errors, valid_actions = generate(
        root / "config" / "incidents_history.seed.json",
        root / "config" / "actions.json",
    )

    assert errors == []
    assert valid_actions == 7
    assert [record["incident_id"] for record in records] == sorted(record["incident_id"] for record in records)
    assert any(record["actions_taken"][0]["action_id"] == "scale_product_catalog" for record in records)

def test_actions_catalog_metadata_passes_schema() -> None:
    root = Path(__file__).resolve().parents[1]

    catalog = ActionCatalog(root / "config" / "actions.json").load()

    assert catalog["scale_product_catalog"].executor_supported is True
    assert catalog["scale_product_catalog"].live_execute_supported is True
    assert catalog["scale_product_catalog"].verification_query_id == "product-catalog.cpu_millicores"
    assert catalog["scale_product_catalog"].verification_signal_id == "product_catalog_cpu_millicores"
    assert catalog["scale_product_catalog"].rollback_action_id == "restore_deployment_replicas"
    assert catalog["scale_product_catalog"].verification_max_ratio == 0.9
    for action_id, signal_id, threshold in (
        ("scale_checkout", "checkout_p95_latency_5m", 2.0),
        ("scale_cart", "cart_error_rate_5m", 0.005),
        ("scale_frontend", "frontend_p95_latency_5m", 1.0),
        ("scale_frontend_proxy", "frontend_proxy_p95_latency_5m", 1.5),
    ):
        action = catalog[action_id]
        assert action.live_execute_supported is True
        assert action.verification_signal_id == signal_id
        assert action.verification_threshold == threshold
    assert catalog["restart_payment"].protected is True
    assert catalog["restart_payment"].blocked is True


def test_scale_action_and_executor_catalogs_share_verification_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    actions = ActionCatalog(root / "config" / "actions.json").load()
    executor_actions = {
        item["action_id"]: item
        for item in json.loads((root / "config" / "executor_supported_actions.json").read_text(encoding="utf-8"))
    }

    for action_id, action in actions.items():
        if not action_id.startswith("scale_"):
            continue
        executor_action = executor_actions[action_id]
        assert executor_action["live_execute_supported"] is True
        assert executor_action["verification_query_id"] == action.verification_query_id
        assert executor_action["verification_signal_id"] == action.verification_signal_id
        assert executor_action.get("verification_threshold") == action.verification_threshold
        assert executor_action.get("verification_max_ratio") == action.verification_max_ratio
        assert executor_action["rollback_action_id"] == action.rollback_action_id


def test_scale_action_verification_queries_exist_in_runtime_registry() -> None:
    root = Path(__file__).resolve().parents[1]
    actions = ActionCatalog(root / "config" / "actions.json").load()
    runtime = load_runtime_config(
        root / "config" / "runtime.json",
        root / "config" / "prometheus_queries.json",
    )

    for action_id, action in actions.items():
        if not action_id.startswith("scale_"):
            continue
        query = runtime.prometheus_query_specs[action.verification_query_id]
        assert query.signal_id == action.verification_signal_id


def test_generate_incident_history_rejects_unknown_action(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    actions = tmp_path / "actions.json"
    actions.write_text(
        json.dumps(
            [
                {
                    "action_id": "page_oncall",
                    "action_type": "page",
                    "target": "platform-team",
                    "target_kind": "OnCall",
                    "cost_min": 1.0,
                    "downtime_min": 0.0,
                    "blast_radius_services": [],
                    "replicas": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    seed.write_text(
        json.dumps(
            [
                {
                    "incident_id": "seed-bad-action-001",
                    "affected_services": ["cart"],
                    "log_signatures": ["container_oom_detected"],
                    "trace_signatures": [],
                    "metric_ratios": {"cart_memory_usage_bytes": 2.0},
                    "actions_taken": [
                        {"action_id": "restart_cart", "target": "cart", "outcome": "success"}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    records, errors, valid_actions = generate(seed, actions)

    assert len(records) == 1
    assert valid_actions == 0
    assert any("does not exist" in error for error in errors)
