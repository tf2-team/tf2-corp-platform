import unittest

from pydantic import ValidationError

from aiops.config import Settings
from aiops.deduplication import IncidentManager
from aiops.detectors import DetectorEngine, NoDataDetector, ThresholdDetector
from aiops.features import FeatureBuilder
from aiops.schemas import ActionProposal, Observation, SignalQuality
from aiops.remediation import PolicyEngine


def policy(settings: Settings | None = None, mode: str | None = None) -> PolicyEngine:
    settings = settings or Settings()
    return PolicyEngine(
        mode=mode or settings.policy_mode,
        protected_targets=settings.protected_targets,
        stateful_kinds=settings.stateful_kinds,
        non_actionable_flows=settings.non_actionable_flows,
        action_type=settings.action_type_restart,
        target_kind=settings.action_target_kind_deployment,
        default_replicas=settings.default_action_replicas,
    )


def no_data_detector(settings: Settings | None = None) -> NoDataDetector:
    settings = settings or Settings()
    return NoDataDetector(
        settings.no_data_required_signal_ids,
        detector_id=settings.no_data_detector_id,
        flow=settings.no_data_flow,
        service=settings.no_data_service,
        severity=settings.no_data_severity,
        runbook_id=settings.no_data_runbook_id,
    )


class PydanticModelTest(unittest.TestCase):
    def test_observation_is_pydantic_validated_model(self):
        observation = Observation(signal_id="checkout_slo", value="0.2", unit="ratio", window="24h", quality="verified")

        self.assertEqual(observation.value, 0.2)
        self.assertEqual(observation.quality, SignalQuality.VERIFIED)

        with self.assertRaises(ValidationError):
            Observation(signal_id="checkout_slo", value=0.2, unit="ratio", window="24h", quality="bad")


class FeatureBuilderTest(unittest.TestCase):
    def test_missing_signal_stays_unknown_not_zero(self):
        feature = FeatureBuilder().build(
            [Observation(signal_id="checkout_slo", value=None, unit="ratio", window="24h", quality=SignalQuality.MISSING)]
        )[0]

        self.assertEqual(feature.status, "unknown")
        self.assertIsNone(feature.value)


class DetectorEngineTest(unittest.TestCase):
    def test_threshold_detector_fires_from_verified_feature(self):
        features = FeatureBuilder().build(
            [Observation(signal_id="checkout_bad_ratio_24h", value=0.017, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
        )
        candidates = DetectorEngine(
            [
                ThresholdDetector(
                    detector_id="ops01_checkout_slo",
                    signal_id="checkout_bad_ratio_24h",
                    threshold=0.01,
                    flow="checkout",
                    service="checkout",
                    severity="SEV1",
                    runbook_id="RB-CHECKOUT-SLO",
                )
            ]
        ).evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].detector_id, "ops01_checkout_slo")
        self.assertEqual(candidates[0].likely_dependency, "unknown")

    def test_no_data_detector_opens_monitoring_loss_candidate(self):
        features = FeatureBuilder().build(
            [Observation(signal_id="checkout_bad_ratio_24h", value=None, unit="ratio", window="24h", quality=SignalQuality.STALE)]
        )
        candidates = DetectorEngine([no_data_detector()]).evaluate(features)

        self.assertEqual(candidates[0].detector_id, "ops02_monitoring_loss")
        self.assertEqual(candidates[0].flow, "monitoring")


class IncidentManagerTest(unittest.TestCase):
    def test_deduplicates_by_stable_fingerprint_not_metric_value(self):
        manager = IncidentManager(environment="tf2")
        detector = ThresholdDetector(
            detector_id="ops01_checkout_slo",
            signal_id="checkout_bad_ratio_24h",
            threshold=0.01,
            flow="checkout",
            service="checkout",
            severity="SEV1",
            runbook_id="RB-CHECKOUT-SLO",
        )

        first = detector.evaluate(
            FeatureBuilder().build(
                [Observation(signal_id="checkout_bad_ratio_24h", value=0.017, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
            )
        )[0]
        second = detector.evaluate(
            FeatureBuilder().build(
                [Observation(signal_id="checkout_bad_ratio_24h", value=0.021, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
            )
        )[0]

        incident = manager.upsert(first)
        same_incident = manager.upsert(second)

        self.assertEqual(incident.incident_id, same_incident.incident_id)
        self.assertEqual(same_incident.occurrence_count, 2)


class PolicyEngineTest(unittest.TestCase):
    def test_blocks_stateful_or_single_replica_mutation(self):
        decision = policy(mode="dry-run").evaluate(
            ActionProposal(
                action_type="restart",
                target="postgresql",
                target_kind="StatefulSet",
                replicas=1,
                mutating=True,
                verification_defined=True,
                rollback_defined=True,
            )
        )

        self.assertFalse(decision.allowed)
        self.assertIn("stateful_target", decision.reasons)
        self.assertIn("single_replica_target", decision.reasons)

    def test_dry_run_records_safe_recommendation_without_execution(self):
        decision = policy(mode="dry-run").evaluate(
            ActionProposal(
                action_type="restart",
                target="payment",
                target_kind="Deployment",
                replicas=3,
                mutating=True,
                verification_defined=True,
                rollback_defined=True,
            )
        )

        self.assertFalse(decision.executed)
        self.assertEqual(decision.result, "dry-run-recorded")

    def test_live_approved_allows_exact_approved_safe_action(self):
        decision = policy(mode="live-approved").evaluate(
            ActionProposal(
                action_type="restart",
                target="payment",
                target_kind="Deployment",
                replicas=3,
                mutating=True,
                verification_defined=True,
                rollback_defined=True,
                approved=True,
            )
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.result, "allowed")


if __name__ == "__main__":
    unittest.main()
