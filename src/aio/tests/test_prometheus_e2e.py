#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from aiops.collectors import PrometheusCollector, load_prometheus_collection_plan
from aiops.config import Settings
from aiops.e2e import execute_prometheus_e2e
from aiops.integrations import PrometheusClient
from aiops.schemas import AnomalyFinding, RcaResult, RootCauseCandidate, SignalQuality


ROOT = Path(__file__).resolve().parents[1]
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class FakeAnomalyEngine:
    def __init__(self, **_: object):
        self.last_algorithm_findings = {}

    def evaluate(self, _series):
        return [
            AnomalyFinding(
                algorithm="test",
                service="payment",
                metric="error_ratio_5m",
                signal_id="payment_error_ratio_5m",
                score=8.0,
                timestamp=int(CAPTURED_AT.timestamp()),
            )
        ]


class FakeRcaEngine:
    def __init__(self, *_: object, **__: object):
        pass

    def rank(self, findings, _series, top_k, corroboration=None):
        return RcaResult(
            anomalies=findings,
            root_causes=[
                RootCauseCandidate(
                    service="payment",
                    score=8.0,
                    root_cause_metrics=["error_ratio_5m"],
                    evidence=["test real-series bridge"],
                )
            ][:top_k],
        )


def _settings_for_test(root: Path, policy_mode: str = "dry-run") -> Settings:
    return Settings().model_copy(
        update={
            "policy_mode": policy_mode,
            "prometheus_base_url": "http://prometheus.example",
            "state_store_path": root / "state" / "aiops.sqlite3",
            "runtime_config_path": ROOT / "config" / "runtime.json",
            "actions_catalog_path": ROOT / "config" / "actions.json",
            "incidents_history_path": ROOT / "config" / "incidents_history.json",
            "remediation_audit_path": root / "state" / "remediation_audit.jsonl",
            "evidence_dir": root / "evidence",
        }
    )


def prometheus_transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = request.url.params.get("query", "")
        if request.url.path.endswith("/query"):
            value = "0.20" if "status_code" in query else "250.0"
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, value]}]},
                },
            )

        base = 0.0 if "ratio" in request.url.params.get("query", "") else 100.0
        values = [[index, str(base + (20.0 if index == 7 else index / 100))] for index in range(8)]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
            },
        )

    return httpx.MockTransport(handler)


class PrometheusCollectorTest(unittest.TestCase):
    def test_collects_verified_observations_and_rca_series(self):
        requests: list[httpx.Request] = []
        settings = Settings().model_copy(update={"prometheus_base_url": "http://prometheus.example"})
        client = PrometheusClient(settings, transport=prometheus_transport(requests))
        plan = load_prometheus_collection_plan(ROOT / "config" / "prometheus_e2e.json")

        collector = PrometheusCollector(client, plan, captured_at=CAPTURED_AT)
        observations = collector.collect()
        series = collector.collect_metric_series()

        self.assertEqual(len(observations), 2)
        self.assertTrue(all(item.quality == SignalQuality.VERIFIED for item in observations))
        self.assertEqual(observations[1].labels["dependency"], "payment")
        self.assertEqual(len(series), 9)
        self.assertTrue(all(len(item.points) == 8 for item in series))
        self.assertTrue(all(item.step_seconds == 1 for item in series))
        instant_requests = [request for request in requests if request.url.path.endswith("/query")]
        self.assertTrue(all(request.url.params.get("time") == str(int(CAPTURED_AT.timestamp())) for request in instant_requests))


class PrometheusE2ETest(unittest.TestCase):
    def test_real_metric_bridge_writes_passing_full_pipeline_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_for_test(root)
            requests: list[httpx.Request] = []
            client = PrometheusClient(settings, transport=prometheus_transport(requests))

            with patch("aiops.pipeline.runtime.build_v001_anomaly_engine", return_value=FakeAnomalyEngine()), patch(
                "aiops.pipeline.runtime.V001RcaEngine", FakeRcaEngine
            ):
                report = execute_prometheus_e2e(
                    settings,
                    ROOT / "config" / "prometheus_e2e.json",
                    root / "evidence" / "e2e",
                    client=client,
                    captured_at=CAPTURED_AT,
                )

            report_path = Path(report["artifact"]["path"])
            stored = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(item["passed"] for item in report["acceptance_criteria"].values()))
        self.assertEqual(stored["run_id"], report["run_id"])
        self.assertEqual(stored["source"]["type"], "prometheus")
        self.assertTrue(stored["pipeline_result"]["incidents"])
        self.assertEqual(stored["pipeline_result"]["rca_result"]["root_causes"][0]["service"], "payment")
        self.assertIn(
            stored["pipeline_result"]["remediation_decisions"][0]["decision"],
            {"dry-run-recorded", "fallback-page-oncall"},
        )
        self.assertFalse(stored["safety"]["live_executor_called"])

    def test_non_dry_run_mode_is_blocked_before_prometheus_call_and_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_for_test(root, policy_mode="live-approved")
            requests: list[httpx.Request] = []
            client = PrometheusClient(settings, transport=prometheus_transport(requests))

            report = execute_prometheus_e2e(
                settings,
                ROOT / "config" / "prometheus_e2e.json",
                root / "evidence" / "e2e",
                client=client,
                captured_at=CAPTURED_AT,
            )

            stored = json.loads(Path(report["artifact"]["path"]).read_text(encoding="utf-8"))

        self.assertEqual(requests, [])
        self.assertEqual(report["status"], "error")
        self.assertEqual(stored["error"]["type"], "DryRunSafetyError")
        self.assertTrue(stored["acceptance_criteria"]["report_exists_for_run"]["passed"])


if __name__ == "__main__":
    unittest.main()
