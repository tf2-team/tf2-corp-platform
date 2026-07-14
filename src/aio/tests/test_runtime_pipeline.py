import unittest

from aiops.config import Settings
from aiops.detectors import DependencyDetector, NoDataDetector, ThresholdDetector
from aiops.schemas import Observation, SignalQuality
from aiops.pipeline import AiopsPipeline
from aiops.remediation import PolicyEngine
from aiops.storage import InMemoryIncidentStore
from tests.helpers import StaticCollector


def policy(settings: Settings) -> PolicyEngine:
    return PolicyEngine(
        mode=settings.policy_mode,
        protected_targets=settings.protected_targets,
        stateful_kinds=settings.stateful_kinds,
        non_actionable_flows=settings.non_actionable_flows,
        action_type=settings.action_type_restart,
        target_kind=settings.action_target_kind_deployment,
        default_replicas=settings.default_action_replicas,
    )


def no_data_detector(settings: Settings) -> NoDataDetector:
    return NoDataDetector(
        settings.no_data_required_signal_ids,
        detector_id=settings.no_data_detector_id,
        flow=settings.no_data_flow,
        service=settings.no_data_service,
        severity=settings.no_data_severity,
        runbook_id=settings.no_data_runbook_id,
    )


class RuntimePipelineTest(unittest.TestCase):
    def test_pipeline_runs_detect_to_incident_notify_and_dry_run(self):
        settings = Settings()
        pipeline = AiopsPipeline(
            collector=StaticCollector(
                [
                    Observation(
                        signal_id="checkout_bad_ratio_24h",
                        value=0.02,
                        unit="ratio",
                        window="24h",
                        quality=SignalQuality.VERIFIED,
                    ),
                    Observation(
                        signal_id="checkout_payment_error_rate_5m",
                        value=0.13,
                        unit="ratio",
                        window="5m",
                        quality=SignalQuality.VERIFIED,
                    ),
                ]
            ),
            detectors=[
                ThresholdDetector(
                    detector_id="ops01_checkout_slo",
                    signal_id="checkout_bad_ratio_24h",
                    threshold=0.01,
                    flow="checkout",
                    service="checkout",
                    severity="SEV1",
                    runbook_id="RB-CHECKOUT-SLO",
                ),
                DependencyDetector(
                    detector_id="ops03_checkout_payment_dependency",
                    signal_id="checkout_payment_error_rate_5m",
                    threshold=0.05,
                    flow="checkout",
                    service="checkout",
                    dependency="payment",
                    runbook_id="RB-CHECKOUT-DEPENDENCY",
                    severity=settings.dependency_default_severity,
                    confidence=settings.dependency_default_confidence,
                ),
            ],
            store=InMemoryIncidentStore(environment=settings.environment),
            policy=policy(settings),
        )

        result = pipeline.run_once()

        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.incidents[0].likely_dependency, "payment")
        self.assertEqual(result.candidates[0].evidence[0].source, "feature")
        self.assertEqual(result.notifications[0].runbook_id, "RB-CHECKOUT-DEPENDENCY")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")
        self.assertEqual(result.verification_results[0].status, "not_recovered")

    def test_pipeline_opens_monitoring_incident_for_stale_signal(self):
        settings = Settings()
        pipeline = AiopsPipeline(
            collector=StaticCollector(
                [
                    Observation(
                        signal_id="checkout_bad_ratio_24h",
                        value=None,
                        unit="ratio",
                        window="24h",
                        quality=SignalQuality.STALE,
                    )
                ]
            ),
            detectors=[no_data_detector(settings)],
            store=InMemoryIncidentStore(environment=settings.environment),
            policy=policy(settings),
        )

        result = pipeline.run_once()

        self.assertEqual(result.incidents[0].flow, "monitoring")
        self.assertEqual(result.incidents[0].state, "open")


if __name__ == "__main__":
    unittest.main()
