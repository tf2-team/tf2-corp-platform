#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

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
