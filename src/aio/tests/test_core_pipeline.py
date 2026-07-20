#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

from pydantic import ValidationError

from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.correlation import Correlator
from aiops.deduplication import IncidentManager
from aiops.detectors import DependencyDetector, DetectorEngine, NoDataDetector, ThresholdDetector
from aiops.features import FeatureBuilder
from aiops.schemas import ActionCatalogItem, ActionProposal, CandidateEvent, EvidenceItem, Feature, HistoryAction, IncidentFeatures, IncidentHistoryRecord, Observation, SignalQuality
from aiops.remediation import HistoryRetriever, PolicyEngine, RemediationDecisionEngine


def policy(settings: Settings | None = None, mode: str | None = None) -> PolicyEngine:
    settings = settings or Settings()
    runtime_config = load_runtime_config(settings.runtime_config_path)
    return PolicyEngine(
        mode=mode or settings.policy_mode,
        protected_targets=runtime_config.policy.protected_targets,
        stateful_kinds=runtime_config.policy.stateful_kinds,
        non_actionable_flows=runtime_config.policy.non_actionable_flows,
        action_type=settings.action_type_restart,
        target_kind=settings.action_target_kind_deployment,
        default_replicas=settings.default_action_replicas,
    )


def no_data_detector(settings: Settings | None = None) -> NoDataDetector:
    settings = settings or Settings()
    no_data = load_hyperparameters(settings.hyperparameters_path)["no_data"]
    runtime_config = load_runtime_config(settings.runtime_config_path)
    detector = next(item for item in runtime_config.detectors if item.type == "no-data")
    return NoDataDetector(
        detector.signal_ids,
        detector_id=detector.id,
        flow=detector.flow,
        service=detector.service,
        severity=detector.severity,
        runbook_id=detector.runbook_id,
        missing_confidence=no_data["missing_confidence"],
        unknown_confidence=no_data["unknown_confidence"],
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

    def test_feature_role_comes_from_runtime_signal_registry(self):
        feature = FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
            [Observation(signal_id="checkout_bad_ratio_24h", value=0.02, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
        )[0]

        self.assertEqual(feature.feature_role, "official_slo")


class DetectorEngineTest(unittest.TestCase):
    def test_threshold_detector_fires_from_verified_feature(self):
        features = FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
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
        self.assertEqual(candidates[0].unit, "ratio")
        self.assertEqual(candidates[0].window, "24h")
        self.assertEqual(candidates[0].likely_dependency, "unknown")

    def test_threshold_detector_ignores_diagnostic_feature(self):
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
        ).evaluate(
            [
                Feature(
                    signal_id="checkout_bad_ratio_24h",
                    value=0.017,
                    unit="ratio",
                    window="24h",
                    quality=SignalQuality.VERIFIED,
                    status="ready",
                    feature_role="diagnostic",
                )
            ]
        )

        self.assertEqual(candidates, [])

    def test_threshold_detector_fires_from_anomaly_input_feature(self):
        features = FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
            [Observation(signal_id="payment_error_rate_5m", value=0.2, unit="ratio", window="5m", quality=SignalQuality.VERIFIED)]
        )
        candidates = DetectorEngine(
            [
                ThresholdDetector(
                    detector_id="auto_payment_error_rate",
                    signal_id="payment_error_rate_5m",
                    threshold=0.05,
                    flow="checkout",
                    service="payment",
                    severity="SEV2",
                    runbook_id="RB-SERVICE-ERROR-RATE",
                )
            ]
        ).evaluate(features)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].detector_id, "auto_payment_error_rate")
        self.assertEqual(candidates[0].service, "payment")

    def test_dependency_detector_ignores_official_slo_feature(self):
        detector = DependencyDetector(
            detector_id="ops03_checkout_payment_dependency",
            signal_id="checkout_payment_error_rate_5m",
            threshold=0.05,
            flow="checkout",
            service="checkout",
            dependency="payment",
            runbook_id="RB-CHECKOUT-DEPENDENCY",
            severity="SEV2",
            confidence=0.8,
        )

        candidates = detector.evaluate(
            [
                Feature(
                    signal_id="checkout_payment_error_rate_5m",
                    value=0.2,
                    unit="ratio",
                    window="5m",
                    quality=SignalQuality.VERIFIED,
                    status="ready",
                    feature_role="official_slo",
                )
            ]
        )

        self.assertEqual(candidates, [])

    def test_no_data_detector_opens_monitoring_loss_candidate(self):
        features = FeatureBuilder().build(
            [Observation(signal_id="checkout_bad_ratio_24h", value=None, unit="ratio", window="24h", quality=SignalQuality.STALE)]
        )
        candidates = DetectorEngine([no_data_detector()]).evaluate(features)

        self.assertEqual(candidates[0].detector_id, "ops02_monitoring_loss")
        self.assertEqual(candidates[0].unit, "ratio")
        self.assertEqual(candidates[0].window, "24h")
        self.assertEqual(candidates[0].flow, "monitoring")

    def test_correlator_ranks_dependency_with_transparent_components(self):
        primary = CandidateEvent(
            environment="tf2",
            timestamp=100,
            detector_id="ops01_checkout_slo",
            flow="checkout",
            service="checkout",
            severity="SEV1",
            signal_id="checkout_bad_ratio_24h",
            value=0.02,
            unit="ratio",
            window="24h",
            threshold=0.01,
            quality=SignalQuality.VERIFIED,
            reason="threshold_breached",
            runbook_id="RB-CHECKOUT-SLO",
            confidence=1.0,
            contributing_signals=("checkout_bad_ratio_24h",),
        )
        dependency = CandidateEvent(
            environment="tf2",
            timestamp=95,
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
            confidence=0.1,
            contributing_signals=("checkout_payment_error_rate_5m",),
            labels={"operation": "charge"},
            evidence=(EvidenceItem(source="trace", reference="trace-1", summary="payment timeout"),),
        )

        hyperparameters = load_hyperparameters(Path("config/hyperparameters.json"))
        candidates = Correlator(load_runtime_config(Path("config/runtime.json")), **hyperparameters["correlation"]).correlate([primary, dependency])

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].likely_dependency, "payment")
        self.assertEqual(candidates[0].confidence, 1.0)
        self.assertEqual(candidates[0].severity, "SEV1")
        self.assertEqual(candidates[0].contributing_signals, ("checkout_bad_ratio_24h", "checkout_payment_error_rate_5m"))
        self.assertEqual(
            set(candidates[0].correlation_components),
            {"verified_primary_signal", "temporal_precedence", "topology_path", "operation_specificity", "trace_log_kubernetes_corroboration"},
        )

    def test_correlator_keeps_independent_same_service_candidates(self):
        slo = CandidateEvent(
            environment="tf2",
            timestamp=100,
            detector_id="ops01_checkout_slo",
            flow="checkout",
            service="checkout",
            severity="SEV1",
            signal_id="checkout_bad_ratio_24h",
            value=0.02,
            unit="ratio",
            window="24h",
            threshold=0.01,
            quality=SignalQuality.VERIFIED,
            reason="threshold_breached",
            runbook_id="RB-CHECKOUT-SLO",
            confidence=1.0,
            contributing_signals=("checkout_bad_ratio_24h",),
        )
        latency = slo.model_copy(
            update={
                "detector_id": "ops04_checkout_latency_p95",
                "signal_id": "checkout_p95_latency_5m",
                "value": 0.6,
                "unit": "seconds",
                "window": "5m",
                "threshold": 0.5,
                "runbook_id": "RB-CHECKOUT-LATENCY",
                "contributing_signals": ("checkout_p95_latency_5m",),
            }
        )

        candidates = Correlator(load_runtime_config(Path("config/runtime.json"))).correlate([slo, latency])

        self.assertEqual([candidate.signal_id for candidate in candidates], ["checkout_bad_ratio_24h", "checkout_p95_latency_5m"])


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
            FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
                [Observation(signal_id="checkout_bad_ratio_24h", value=0.017, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
            )
        )[0]
        second = detector.evaluate(
            FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
                [Observation(signal_id="checkout_bad_ratio_24h", value=0.021, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
            )
        )[0]

        incident = manager.upsert(first)
        same_incident = manager.upsert(second)

        self.assertEqual(incident.incident_id, same_incident.incident_id)
        self.assertEqual(same_incident.occurrence_count, 2)

    def test_rca_root_cause_fingerprint_includes_primary_metric(self):
        manager = IncidentManager(environment="tf2")
        latency = CandidateEvent(
            detector_id="rca_root_cause",
            flow="checkout",
            service="payment",
            severity="SEV2",
            signal_id="p95_latency_5m",
            value=1.0,
            unit="score",
            window="rca",
            threshold=None,
            quality=SignalQuality.VERIFIED,
            reason="rca_root_cause",
            runbook_id="RB-SERVICE-ERROR-RATE",
        )
        errors = latency.model_copy(update={"signal_id": "error_rate_5m"})

        first = manager.upsert(latency)
        second = manager.upsert(errors)

        self.assertNotEqual(first.incident_id, second.incident_id)


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

    def test_blocks_external_and_stateful_protected_targets(self):
        cases = [
            ("postgresql", "Database", "stateful_target"),
            ("valkey-cart", "Database", "stateful_target"),
            ("opensearch", "StatefulSet", "stateful_target"),
        ]
        for target, target_kind, expected_reason in cases:
            with self.subTest(target=target):
                decision = policy(mode="dry-run").evaluate(
                    ActionProposal(
                        action_type="restart",
                        target=target,
                        target_kind=target_kind,
                        replicas=3,
                        mutating=True,
                        verification_defined=True,
                        rollback_defined=True,
                    )
                )

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.result, "blocked")
                self.assertIn("protected_target", decision.reasons)
                self.assertIn(expected_reason, decision.reasons)

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


class RemediationEngineTest(unittest.TestCase):
    def test_deadlock_guard_matches_substring_log_signature(self):
        decision = RemediationDecisionEngine(ood_threshold=0.1, cost_page=20.0, blast_radius_limit=3, confidence_threshold=0.7).decide(
            "inc-1",
            IncidentFeatures(affected_services={"postgresql"}, log_signatures={"database deadlock detected"}),
            [
                (
                    IncidentHistoryRecord(
                        incident_id="hist-1",
                        affected_services={"postgresql"},
                        log_signatures={"database deadlock detected"},
                        actions_taken=[HistoryAction(action_id="increase_pool_postgresql", target="postgresql", outcome="success")],
                    ),
                    1.0,
                )
            ],
            {
                "increase_pool_postgresql": ActionCatalogItem(
                    action_id="increase_pool_postgresql",
                    action_type="increase_pool_size",
                    target="postgresql",
                    target_kind="Deployment",
                    cost_min=1.0,
                    downtime_min=0.0,
                )
            },
        )

        self.assertEqual(decision.selected_action, "page_oncall")
        self.assertIn("deadlock_pool_size_forbidden", decision.reasons)

    def test_retrieval_scores_trace_signatures(self):
        retriever = HistoryRetriever({"service": 0.0, "log": 0.0, "trace": 1.0, "metric": 0.0}, top_k=1)

        matches = retriever.top_matches(
            IncidentFeatures(trace_signatures={"checkout->payment:5xx"}),
            [
                IncidentHistoryRecord(incident_id="hist-trace", trace_signatures={"checkout->payment:5xx"}),
                IncidentHistoryRecord(incident_id="hist-other", trace_signatures={"checkout->cart:5xx"}),
            ],
        )

        self.assertEqual(matches[0][0].incident_id, "hist-trace")

    def test_translates_historical_action_to_current_affected_target(self):
        decision = RemediationDecisionEngine(ood_threshold=0.1, cost_page=20.0, blast_radius_limit=3, confidence_threshold=0.7).decide(
            "inc-1",
            IncidentFeatures(affected_services={"payment-v2"}),
            [
                (
                    IncidentHistoryRecord(
                        incident_id="hist-1",
                        affected_services={"payment"},
                        actions_taken=[HistoryAction(action_id="restart_payment", target="payment", outcome="success")],
                    ),
                    1.0,
                )
            ],
            {
                "restart_payment_v2": ActionCatalogItem(
                    action_id="restart_payment_v2",
                    action_type="restart",
                    target="payment-v2",
                    target_kind="Deployment",
                    cost_min=1.0,
                    downtime_min=0.0,
                )
            },
        )

        self.assertEqual(decision.selected_action, "restart_payment_v2")
        self.assertFalse(decision.fallback)


if __name__ == "__main__":
    unittest.main()
