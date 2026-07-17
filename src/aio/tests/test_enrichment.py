import unittest
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.enrichment import Enricher
from aiops.schemas import CandidateEvent, Feature, SignalQuality


class FakeJaeger:
    def search_traces(self, service: str, limit: int = 20) -> dict:
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
    def search(self, index: str, body: dict) -> dict:
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_source": {"message": "payment failed token=abc user@example.com"}}],
            }
        }


class FakeKubernetes:
    def get_deployment(self, namespace: str, name: str) -> dict:
        return {"spec": {"replicas": 2}, "status": {"availableReplicas": 1}}

    def list_pods(self, namespace: str) -> dict:
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
        )

    def test_enriches_candidate_with_on_demand_integration_evidence(self):
        enricher = Enricher(
            runtime_config=load_runtime_config(Path("config/runtime.json")),
            jaeger=FakeJaeger(),
            opensearch=FakeOpenSearch(),
            kubernetes=FakeKubernetes(),
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

    def test_enrichment_failure_is_evidence_not_pipeline_failure(self):
        result = Enricher(jaeger=FailingClient()).enrich([self.candidate()], [])[0]

        self.assertEqual(result.evidence[0].source, "enrichment_failure")
        self.assertEqual(result.evidence[0].reference, "jaeger")


if __name__ == "__main__":
    unittest.main()
