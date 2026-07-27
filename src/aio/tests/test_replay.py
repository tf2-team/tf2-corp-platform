#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json

from aiops.replay import replay


def _write_case(root, name, label, series):
    case_dir = root / name
    case_dir.mkdir(parents=True)
    (case_dir / "label.json").write_text(json.dumps(label), encoding="utf-8")
    (case_dir / "metric_series.json").write_text(json.dumps(series), encoding="utf-8")


def _series(service, metric, values, start=0):
    return {
        "service": service,
        "metric": metric,
        "signal_id": f"{service}_{metric}".replace("-", "_"),
        "points": [
            {"timestamp": start + index, "value": value}
            for index, value in enumerate(values)
        ],
    }


def test_replay_distinguishes_high_load_from_error_incident(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    _write_case(
        dataset,
        "checkout_high_load_healthy",
        {"scenario_type": "high_load_healthy", "expected_incident": False, "incident_start_ts": None},
        [
            _series("checkout", "request_rate_5m", [10, 11, 10, 12, 50, 75, 100]),
            _series("checkout", "p99_latency_5m", [0.20, 0.21, 0.20, 0.22, 0.35, 0.40, 0.45]),
            _series("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0]),
        ],
    )

    _write_case(
        dataset,
        "checkout_real_incident",
        {"scenario_type": "real_incident", "expected_incident": True, "incident_start_ts": 5},
        [
            _series("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 11, 11]),
            _series("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0.02, 0.03]),
        ],
    )

    report = replay(dataset, threshold=3.0, critical_multiplier=2.0)

    by_case = {case["case_id"]: case for case in report["cases"]}
    assert by_case["checkout_high_load_healthy"]["fired"] is False
    assert by_case["checkout_real_incident"]["fired"] is True
    assert report["metrics"]["precision"] == 1.0
    assert report["metrics"]["recall"] == 1.0
    assert report["metrics"]["false_positive_count"] == 0
