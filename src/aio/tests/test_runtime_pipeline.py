import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.collectors import StaticCollector
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.normalization import load_normalization_schema
from aiops.qualification import load_qualification_schema
from aiops.schemas import CandidateEvent, Feature, Observation, SignalQuality
from aiops.pipeline import AiopsPipeline
from aiops.remediation import (
    ActionCatalog,
    HistoryRetriever,
    IncidentHistoryStore,
    PolicyEngine,
    RemediationAuditLog,
    RemediationDecisionEngine,
    RemediationFeatureExtractor,
)
from aiops.storage import SQLiteIncidentStore


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
    no_data = load_hyperparameters(settings.hyperparameters_path)["no_data"]
    return NoDataDetector(
        settings.no_data_required_signal_ids,
        detector_id=settings.no_data_detector_id,
        flow=settings.no_data_flow,
        service=settings.no_data_service,
        severity=settings.no_data_severity,
        runbook_id=settings.no_data_runbook_id,
        missing_confidence=no_data["missing_confidence"],
        unknown_confidence=no_data["unknown_confidence"],
    )


def runtime_kwargs(settings: Settings) -> dict:
    runtime_config = load_runtime_config(settings.runtime_config_path)
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    return {
        "runtime_config": runtime_config,
        "qualification_schema": load_qualification_schema(settings.qualification_schema_path),
        "normalization_schema": load_normalization_schema(settings.normalization_schema_path),
        "qualification_dev": settings.qualification_gate_dev,
        "qualification_max_sample_age_seconds": settings.qualification_max_sample_age_seconds,
        "correlation_hyperparameters": hyperparameters["correlation"],
    }


class RecoveredDependencyDetector(Detector):
    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        return [
            CandidateEvent(
                detector_id="test_dependency",
                flow="checkout",
                service="checkout",
                severity="SEV1",
                signal_id="checkout_payment_error_rate_5m",
                value=0.2,
                unit="ratio",
                window="5m",
                threshold=0.5,
                quality=SignalQuality.VERIFIED,
                reason="dependency_signal_breached",
                runbook_id="RB-CHECKOUT-DEPENDENCY",
                likely_dependency="payment",
                confidence=0.8,
            )
        ]


class RuntimePipelineTest(unittest.TestCase):
    def test_pipeline_runs_detect_to_incident_notify_and_dry_run(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
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
                            labels={"service": "checkout", "dependency": "payment"},
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
                        confidence=0.8,
                    ),
                ],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.incidents[0].likely_dependency, "payment")
        self.assertEqual(result.candidates[0].evidence[0].source, "feature")
        self.assertEqual(result.notifications[0].runbook_id, "RB-CHECKOUT-DEPENDENCY")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")
        self.assertEqual(result.verification_results[0].status, "not_recovered")

    def test_pipeline_opens_monitoring_incident_for_stale_signal(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
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
                store=store,
                policy=policy(settings),
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual(result.incidents[0].flow, "monitoring")
        self.assertEqual(result.incidents[0].state, "open")

    def test_pipeline_opens_monitoring_incident_for_unqualified_signal(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=0.02,
                            unit="ratio",
                            window="24h",
                            quality=SignalQuality.UNQUALIFIED,
                        )
                    ]
                ),
                detectors=[no_data_detector(settings)],
                store=store,
                policy=policy(settings),
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual(result.incidents[0].flow, "monitoring")
        self.assertEqual(result.incidents[0].events[0].reason, "signal_unqualified")

    def test_verified_remediation_is_added_to_incident_history(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions_path = root / "actions.json"
            history_path = root / "history.json"
            audit_path = root / "audit.jsonl"
            actions_path.write_text(
                json.dumps(
                    [
                        {
                            "action_id": "restart_payment",
                            "action_type": "restart",
                            "target": "payment",
                            "target_kind": "Deployment",
                            "cost_min": 2.0,
                            "downtime_min": 1.0,
                            "blast_radius_services": ["checkout"],
                            "replicas": 3,
                        },
                        {
                            "action_id": "page_oncall",
                            "action_type": "page",
                            "target": "platform-team",
                            "target_kind": "OnCall",
                            "cost_min": 20.0,
                            "downtime_min": 0.0,
                            "blast_radius_services": [],
                            "replicas": 0,
                        },
                    ]
                ),
                encoding="utf-8",
            )
            history_path.write_text(
                json.dumps(
                    [
                        {
                            "incident_id": "hist-payment-latency",
                            "affected_services": ["checkout", "payment"],
                            "log_signatures": ["dependency_signal_breached"],
                            "metric_ratios": {"checkout_payment_error_rate_5m": 0.4},
                            "actions_taken": [
                                {"action_id": "restart_payment", "target": "payment", "outcome": "success"}
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
            hyperparameters = load_hyperparameters(settings.hyperparameters_path)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [
                        Observation(
                            signal_id="checkout_payment_error_rate_5m",
                            value=0.2,
                            unit="ratio",
                            window="5m",
                            quality=SignalQuality.VERIFIED,
                        )
                    ]
                ),
                detectors=[RecoveredDependencyDetector()],
                store=store,
                policy=policy(settings),
                correlation_hyperparameters=hyperparameters["correlation"],
                remediation=(
                    RemediationFeatureExtractor(),
                    HistoryRetriever(hyperparameters["remediation"]["similarity_weights"], hyperparameters["remediation"]["history_top_k"]),
                    RemediationDecisionEngine(
                        ood_threshold=hyperparameters["remediation"]["ood_threshold"],
                        cost_page=hyperparameters["remediation"]["cost_page"],
                        blast_radius_limit=hyperparameters["remediation"]["blast_radius_limit"],
                        confidence_threshold=hyperparameters["remediation"]["confidence_threshold"],
                    ),
                    ActionCatalog(actions_path),
                    IncidentHistoryStore(history_path),
                    RemediationAuditLog(audit_path),
                ),
            )

            result = pipeline.run_once()
            store.close()
            history = json.loads(history_path.read_text(encoding="utf-8"))

        self.assertEqual(result.verification_results[0].status, "recovered")
        self.assertEqual(result.remediation_decisions[0].selected_action, "restart_payment")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["incident_id"], result.incidents[0].incident_id)
        self.assertEqual(history[1]["actions_taken"][0]["outcome"], "success")


if __name__ == "__main__":
    unittest.main()
