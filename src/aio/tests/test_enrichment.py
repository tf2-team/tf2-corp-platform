#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.enrichment import Enricher
from aiops.schemas import AnomalyFinding, CandidateEvent, Feature, SignalQuality


class FakeJaeger:
    def __init__(self):
        self.calls: list[dict] = []

    def search_traces(self, service: str, limit: int = 20, start: int | None = None, end: int | None = None) -> dict:
        self.calls.append({"service": service, "limit": limit, "start": start, "end": end})
        return {
            "data": [
                {
                    "traceID": "trace-1",
                    "processes": {"p1": {"serviceName": service}},
                    "spans": [
                        {
                            "processID": "p1",
                            "operationName": "charge",
                            "duration": 12000,
                            "tags": [{"key": "error", "value": True}],
                        }
                    ],
                }
            ]
        }

    def trace_ui_url(self, trace_id: str) -> str:
        return f"https://jaeger/trace/{trace_id}"


class FakeOpenSearch:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append((index, body))
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_index": "otel-logs-2026.07.23",
                        "_id": "log-1",
                        "_source": {"@timestamp": "1970-01-01T00:15:00Z", "message": "payment failed token=abc user@example.com"},
                    }
                ],
            }
        }


class FakeKubernetes:
    def __init__(self):
        self.deployment_calls: list[tuple[str, str]] = []
        self.pod_calls: list[str] = []

    def get_deployment(self, namespace: str, name: str) -> dict:
        self.deployment_calls.append((namespace, name))
        return {"spec": {"replicas": 2}, "status": {"availableReplicas": 1}}

    def list_pods(self, namespace: str) -> dict:
        self.pod_calls.append(namespace)
        return {
            "items": [
                {
                    "metadata": {"name": "payment-abc"},
                    "status": {
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "containerStatuses": [{"restartCount": 3}],
                    },
                }
            ]
        }


class FailingClient:
    def search_traces(self, service: str, limit: int = 20) -> dict:
        raise RuntimeError("down")

    def trace_ui_url(self, trace_id: str) -> str:
        return trace_id


class EnricherTest(unittest.TestCase):
    def finding(self) -> AnomalyFinding:
        return AnomalyFinding(
            algorithm="weighted_sum",
            service="checkout",
            metric="cpu_millicores",
            signal_id="checkout_cpu_millicores",
            score=0.5,
            timestamp=1000,
        )

    def candidate(self) -> CandidateEvent:
        return CandidateEvent(
            detector_id="ops03_checkout_payment_dependency",
            flow="checkout",
            service="checkout",
            severity="SEV2",
            signal_id="checkout_payment_error_rate_5m",
            value=0.2,
            unit="ratio",
            window="5m",
            threshold=0.05,
            quality=SignalQuality.VERIFIED,
            reason="dependency_signal_breached",
            runbook_id="RB-CHECKOUT-DEPENDENCY",
            likely_dependency="payment",
            contributing_signals=("checkout_payment_error_rate_5m",),
            timestamp=1000,
        )

    def test_enriches_candidate_with_on_demand_integration_evidence(self):
        jaeger = FakeJaeger()
        opensearch = FakeOpenSearch()
        kubernetes = FakeKubernetes()
        enricher = Enricher(
            runtime_config=load_runtime_config(Path("config/runtime.json")),
            jaeger=jaeger,
            opensearch=opensearch,
            kubernetes=kubernetes,
        )
        result = enricher.enrich(
            [self.candidate()],
            [
                Feature(
                    signal_id="checkout_payment_error_rate_5m",
                    value=0.2,
                    unit="ratio",
                    window="5m",
                    quality=SignalQuality.VERIFIED,
                    status="ready",
                )
            ],
        )[0]

        by_source = {item.source: item for item in result.evidence}
        self.assertIn("feature", by_source)
        self.assertIn("trace", by_source)
        self.assertIn("log", by_source)
        self.assertIn("kubernetes", by_source)
        self.assertIn("[REDACTED]", by_source["log"].summary)
        self.assertIn("[REDACTED_EMAIL]", by_source["log"].summary)
        self.assertIn("pod_restarts=3", by_source["kubernetes"].summary)
        self.assertEqual(jaeger.calls, [{"service": "payment", "limit": 1, "start": 700000000, "end": 1000000000}])
        self.assertEqual(opensearch.calls[0][1]["query"]["bool"]["must"][1]["range"]["@timestamp"], {"gte": "1970-01-01T00:11:40Z", "lte": "1970-01-01T00:16:40Z"})
        self.assertEqual(kubernetes.deployment_calls, [("techx-corp-prod", "payment")])

    def test_external_clients_are_only_called_when_candidate_exists(self):
        jaeger = FakeJaeger()
        opensearch = FakeOpenSearch()
        kubernetes = FakeKubernetes()

        result = Enricher(
            runtime_config=load_runtime_config(Path("config/runtime.json")),
            jaeger=jaeger,
            opensearch=opensearch,
            kubernetes=kubernetes,
        ).enrich([], [])

        self.assertEqual(result, [])
        self.assertEqual(jaeger.calls, [])
        self.assertEqual(opensearch.calls, [])
        self.assertEqual(kubernetes.deployment_calls, [])

    def test_enrichment_failure_is_evidence_not_pipeline_failure(self):
        result = Enricher(jaeger=FailingClient()).enrich([self.candidate()], [])[0]

        self.assertEqual(result.evidence[0].source, "enrichment_failure")
        self.assertEqual(result.evidence[0].reference, "jaeger")

    def test_corroboration_queries_tail_and_returns_earliest_trace_failure(self):
        jaeger = FakeJaeger()
        jaeger.search_traces = lambda service, limit=20, start=None, end=None: {
            "data": [
                {
                    "traceID": "trace-1",
                    "processes": {"p1": {"serviceName": "checkout"}, "p2": {"serviceName": "payment"}},
                    "spans": [
                        {"processID": "p1", "operationName": "checkout", "startTime": 950_000_000, "tags": [{"key": "error", "value": True}]},
                        {"processID": "p2", "operationName": "charge", "startTime": 900_000_000, "duration": 12_000, "tags": [{"key": "otel.status_code", "value": "ERROR"}]},
                    ],
                }
            ]
        }
        opensearch = FakeOpenSearch()
        result = Enricher(jaeger=jaeger, opensearch=opensearch).corroborate([self.finding()], window_seconds=900)["checkout"]

        self.assertEqual(result.available_sources, {"log", "trace"})
        self.assertTrue(result.log_failure)
        self.assertEqual(result.log_classification, "hard_failure")
        self.assertEqual(result.log_failure_count, 1)
        self.assertEqual(result.log_failure_timestamp, 900)
        self.assertEqual(result.log_reference, "otel-logs-2026.07.23/log-1")
        self.assertIn("payment failed", result.log_excerpt)
        self.assertTrue(result.trace_failure)
        self.assertEqual(result.trace_root_service, "payment")
        self.assertEqual(result.trace_failure_timestamp, 900)
        self.assertEqual(result.trace_id, "trace-1")
        self.assertEqual(result.trace_operation, "charge")
        self.assertEqual(result.trace_status, "ERROR")
        self.assertEqual(result.trace_duration_ms, 12.0)
        query = opensearch.calls[0][1]
        self.assertEqual(query["query"]["bool"]["filter"][0]["range"]["@timestamp"], {"gte": "1970-01-01T00:01:40Z", "lte": "1970-01-01T00:16:40Z"})
        self.assertIn("exception", str(query).lower())

    def test_latency_only_trace_is_available_but_not_failure(self):
        jaeger = FakeJaeger()
        jaeger.search_traces = lambda service, limit=20, start=None, end=None: {
            "data": [{"traceID": "slow", "processes": {"p1": {"serviceName": service}}, "spans": [{"processID": "p1", "duration": 9_000_000, "tags": []}]}]
        }

        result = Enricher(jaeger=jaeger).corroborate([self.finding()], window_seconds=900)["checkout"]

        self.assertEqual(result.available_sources, {"trace"})
        self.assertFalse(result.trace_failure)
        self.assertIsNone(result.trace_root_service)

    def test_failed_corroboration_source_is_unavailable(self):
        result = Enricher(jaeger=FailingClient()).corroborate([self.finding()], window_seconds=900)["checkout"]

        self.assertEqual(result.available_sources, set())


if __name__ == "__main__":
    unittest.main()
