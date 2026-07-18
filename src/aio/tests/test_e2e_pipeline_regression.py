import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiops.collectors import StaticCollector
from aiops.config import Settings, build_detectors, load_runtime_config
from aiops.detectors import Detector
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
from aiops.schemas import (
    AnomalyFinding,
    CandidateEvent,
    MetricPoint,
    MetricSeries,
    Observation,
    RcaResult,
    RootCauseCandidate,
    SignalQuality,
)
from aiops.storage import SQLiteIncidentStore


ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = ROOT / ".test-tmp"


def temp_workspace() -> TemporaryDirectory:
    TEST_TMP_ROOT.mkdir(exist_ok=True)
    return TemporaryDirectory(dir=TEST_TMP_ROOT)


def observation(signal_id: str, value: float | None, quality: SignalQuality = SignalQuality.VERIFIED) -> Observation:
    return Observation(signal_id=signal_id, value=value, unit="ratio", window="5m", quality=quality)


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


def write_actions(path: Path) -> None:
    path.write_text(
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


def write_history(path: Path, metric_ratio: float = 4.0) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "incident_id": "hist-payment-dependency",
                    "affected_services": ["checkout", "payment"],
                    "log_signatures": ["dependency_signal_breached"],
                    "metric_ratios": {"checkout_payment_error_rate_5m": metric_ratio},
                    "actions_taken": [{"action_id": "restart_payment", "target": "payment", "outcome": "success"}],
                }
            ]
        ),
        encoding="utf-8",
    )


def settings_for(root: Path, *, rca_enabled: bool = False) -> Settings:
    return Settings().model_copy(
        update={
            "state_store_path": root / "aiops.sqlite3",
            "runtime_config_path": ROOT / "config" / "runtime.json",
            "actions_catalog_path": root / "actions.json",
            "incidents_history_path": root / "history.json",
            "remediation_audit_path": root / "remediation_audit.jsonl",
            "rca_enabled": rca_enabled,
        }
    )


def run_pipeline(
    root: Path,
    observations: list[Observation],
    *,
    metric_series: list[MetricSeries] | None = None,
    rca_enabled: bool = False,
):
    settings = settings_for(root, rca_enabled=rca_enabled)
    runtime_config = load_runtime_config(settings.runtime_config_path)
    store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
    pipeline = AiopsPipeline(
        collector=StaticCollector(observations),
        detectors=build_detectors(runtime_config, settings),
        store=store,
        policy=PolicyEngine(
            mode=settings.policy_mode,
            protected_targets=runtime_config.policy.protected_targets,
            stateful_kinds=runtime_config.policy.stateful_kinds,
            non_actionable_flows=runtime_config.policy.non_actionable_flows,
            action_type=settings.action_type_restart,
            target_kind=settings.action_target_kind_deployment,
            default_replicas=settings.default_action_replicas,
        ),
        runtime_config=runtime_config,
        rca_hyperparameters={
            "enabled": rca_enabled,
            "top_k": settings.rca_top_k,
            "min_points": settings.rca_min_points,
            "ewma_alpha": settings.rca_ewma_alpha,
            "ewma_z_threshold": settings.rca_ewma_z_threshold,
            "seasonal_period": settings.rca_seasonal_period,
            "isolation_score_threshold": settings.rca_isolation_score_threshold,
            "bocpd_score_threshold": settings.rca_bocpd_score_threshold,
            "fallback_split_ratio": settings.rca_fallback_split_ratio,
        },
        remediation=(
            RemediationFeatureExtractor(),
            HistoryRetriever(settings.remediation_similarity_weights, settings.remediation_history_top_k),
            RemediationDecisionEngine(
                ood_threshold=settings.remediation_ood_threshold,
                cost_page=settings.remediation_cost_page,
                blast_radius_limit=settings.remediation_blast_radius_limit,
                confidence_threshold=settings.remediation_confidence_threshold,
            ),
            ActionCatalog(settings.actions_catalog_path),
            IncidentHistoryStore(settings.incidents_history_path),
            RemediationAuditLog(settings.remediation_audit_path),
        ),
    )
    try:
        return pipeline.run_once(metric_series=metric_series)
    finally:
        store.close()


class FakeAnomalyEngine:
    def __init__(self, *args, **kwargs):
        pass

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        return [
            AnomalyFinding(
                algorithm="test_detector",
                service="payment",
                metric="latency",
                signal_id="payment_latency",
                score=9.0,
                timestamp=series[0].points[-1].timestamp if series else 0,
            )
        ]


class FakeRcaEngine:
    def __init__(self, *args, **kwargs):
        pass

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int) -> RcaResult:
        return RcaResult(
            anomalies=findings,
            root_causes=[
                RootCauseCandidate(
                    service="payment",
                    score=9.0,
                    root_cause_metrics=["latency"],
                    evidence=["payment latency regression fixture"],
                )
            ],
        )


class RecoveredDependencyDetector(Detector):
    def evaluate(self, features):
        return [
            CandidateEvent(
                detector_id="test_dependency",
                flow="checkout",
                service="checkout",
                severity="SEV1",
                signal_id="checkout_payment_error_rate_5m",
                value=0.2,
                threshold=0.5,
                quality=SignalQuality.VERIFIED,
                reason="dependency_signal_breached",
                runbook_id="RB-CHECKOUT-DEPENDENCY",
                likely_dependency="payment",
                confidence=0.8,
                contributing_signals=("checkout_payment_error_rate_5m",),
            )
        ]


class E2EPipelineRegressionTest(unittest.TestCase):
    def test_normal_case_does_not_open_incident(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json")
            result = run_pipeline(
                root,
                [
                    observation("checkout_bad_ratio_24h", 0.001),
                    observation("checkout_payment_error_rate_5m", 0.001),
                ],
            )

        self.assertEqual(result.candidates, [])
        self.assertEqual(result.incidents, [])
        self.assertEqual(result.notifications, [])
        self.assertEqual(result.policy_decisions, [])

    def test_threshold_breach_opens_checkout_slo_incident(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json")
            result = run_pipeline(
                root,
                [
                    observation("checkout_bad_ratio_24h", 0.02),
                    observation("checkout_payment_error_rate_5m", 0.001),
                ],
            )

        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.candidates[0].detector_id, "ops01_checkout_slo")
        self.assertEqual(result.candidates[0].reason, "threshold_breached")
        self.assertEqual(result.incidents[0].service, "checkout")
        self.assertEqual(result.notifications[0].runbook_id, "RB-CHECKOUT-SLO")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")

    def test_dependency_breach_prefers_payment_dependency_incident(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json")
            result = run_pipeline(
                root,
                [
                    observation("checkout_bad_ratio_24h", 0.02),
                    observation("checkout_payment_error_rate_5m", 0.2),
                ],
            )

        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.candidates[0].detector_id, "ops03_checkout_payment_dependency")
        self.assertEqual(result.candidates[0].reason, "dependency_signal_breached")
        self.assertEqual(result.incidents[0].likely_dependency, "payment")
        self.assertEqual(result.notifications[0].runbook_id, "RB-CHECKOUT-DEPENDENCY")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")

    def test_no_data_opens_monitoring_incident_without_action_policy(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json")
            result = run_pipeline(root, [observation("checkout_bad_ratio_24h", None, SignalQuality.STALE)])

        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.candidates[0].detector_id, "ops02_monitoring_loss")
        self.assertEqual(result.candidates[0].reason, "signal_stale")
        self.assertEqual(result.incidents[0].flow, "monitoring")
        self.assertEqual(result.policy_decisions, [])

    def test_pipeline_returns_rca_result_for_metric_series(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json")
            with patch("aiops.pipeline.runtime.V001AnomalyEngine", FakeAnomalyEngine), patch(
                "aiops.pipeline.runtime.V001RcaEngine", FakeRcaEngine
            ):
                result = run_pipeline(
                    root,
                    [observation("checkout_payment_error_rate_5m", 0.2)],
                    metric_series=[
                        metric("checkout", "latency", [1.0, 1.0, 1.1, 1.0, 1.2, 1.0, 1.1, 2.0]),
                        metric("payment", "latency", [1.0, 1.0, 1.1, 1.0, 1.2, 1.0, 1.1, 20.0]),
                    ],
                    rca_enabled=True,
                )

        self.assertEqual(result.rca_result.anomalies[0].service, "payment")
        self.assertEqual(result.rca_result.root_causes[0].service, "payment")
        self.assertIn("latency", result.rca_result.root_causes[0].root_cause_metrics)

    def test_remediation_decision_uses_matching_history(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            write_actions(root / "actions.json")
            write_history(root / "history.json", metric_ratio=4.0)
            result = run_pipeline(root, [observation("checkout_payment_error_rate_5m", 0.2)])

        self.assertEqual(len(result.remediation_decisions), 1)
        self.assertFalse(result.remediation_decisions[0].fallback)
        self.assertEqual(result.remediation_decisions[0].selected_action, "restart_payment")
        self.assertEqual(result.remediation_decisions[0].matched_history, ["hist-payment-dependency"])

    def test_verified_recovery_appends_success_to_history(self):
        with temp_workspace() as tmp:
            root = Path(tmp)
            actions_path = root / "actions.json"
            history_path = root / "history.json"
            audit_path = root / "remediation_audit.jsonl"
            write_actions(actions_path)
            write_history(history_path, metric_ratio=0.4)
            settings = settings_for(root)
            store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([observation("checkout_payment_error_rate_5m", 0.2)]),
                detectors=[RecoveredDependencyDetector()],
                store=store,
                policy=PolicyEngine(
                    mode=settings.policy_mode,
                    protected_targets=settings.protected_targets,
                    stateful_kinds=settings.stateful_kinds,
                    non_actionable_flows=settings.non_actionable_flows,
                    action_type=settings.action_type_restart,
                    target_kind=settings.action_target_kind_deployment,
                    default_replicas=settings.default_action_replicas,
                ),
                remediation=(
                    RemediationFeatureExtractor(),
                    HistoryRetriever({"service": 0.4, "log": 0.3, "metric": 0.3}, top_k=3),
                    RemediationDecisionEngine(
                        ood_threshold=0.2,
                        cost_page=20.0,
                        blast_radius_limit=3,
                        confidence_threshold=0.7,
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
