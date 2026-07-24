#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.collectors import StaticCollector
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.normalization import load_normalization_schema
from aiops.qualification import load_qualification_schema
from aiops.schemas import (
    AnomalyFinding,
    CandidateEvent,
    EvidenceItem,
    Feature,
    Incident,
    MetricPoint,
    MetricSeries,
    Observation,
    RcaResult,
    RootCauseCandidate,
    SignalQuality,
    TelemetryCorroboration,
)
from aiops.pipeline import AiopsPipeline
from aiops.notifications import is_slo_notification
from aiops.pipeline.runtime import _algorithm_service_scores, _apply_corroboration, _slo_impact_findings
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
    runtime_config = load_runtime_config(settings.runtime_config_path)
    return PolicyEngine(
        mode=settings.policy_mode,
        protected_targets=runtime_config.policy.protected_targets,
        stateful_kinds=runtime_config.policy.stateful_kinds,
        non_actionable_flows=runtime_config.policy.non_actionable_flows,
        action_type=settings.action_type_restart,
        target_kind=settings.action_target_kind_deployment,
        default_replicas=settings.default_action_replicas,
    )


def no_data_detector(settings: Settings) -> NoDataDetector:
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


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


def anomaly(name: str, score: float = 0.5, timestamp: int = 5) -> AnomalyFinding:
    return AnomalyFinding(algorithm="weighted_sum", service="checkout", metric=name, signal_id=f"checkout_{name}", score=score, timestamp=timestamp)


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


class MultiServiceDetector(Detector):
    def __init__(self, cart_severity: str = "SEV2", cart_signal_id: str = "cart_error_rate_5m"):
        self.cart_severity = cart_severity
        self.cart_signal_id = cart_signal_id

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        return [
            CandidateEvent(
                detector_id="auto_cart_error_rate",
                timestamp=10,
                flow="checkout",
                service="cart",
                severity=self.cart_severity,
                signal_id=self.cart_signal_id,
                value=0.2,
                unit="ratio",
                window="5m",
                threshold=0.05,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
            ),
            CandidateEvent(
                detector_id="ops01_checkout_slo",
                timestamp=10,
                flow="checkout",
                service="checkout",
                severity="SEV1",
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                threshold=0.01,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
            ),
            CandidateEvent(
                detector_id="auto_valkey_cart_error_rate",
                timestamp=10,
                flow="checkout",
                service="valkey-cart",
                severity="SEV2",
                signal_id="valkey_cart_error_rate_5m",
                value=0.2,
                unit="ratio",
                window="5m",
                threshold=0.05,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
            ),
        ]


class ServiceSignalDetector(Detector):
    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        return [
            CandidateEvent(
                detector_id="auto_frontend_proxy_latency_p99",
                timestamp=10,
                flow="checkout",
                service="frontend-proxy",
                severity="SEV1",
                signal_id="frontend_proxy_p99_latency_5m",
                value=2.4,
                unit="seconds",
                window="5m",
                threshold=1.5,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
                confidence=1.0,
                contributing_signals=("frontend_proxy_p99_latency_5m",),
            ),
            CandidateEvent(
                detector_id="auto_checkout_latency_p95",
                timestamp=10,
                flow="checkout",
                service="checkout",
                severity="SEV1",
                signal_id="checkout_p95_latency_5m",
                value=4.8,
                unit="seconds",
                window="5m",
                threshold=2.0,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
                confidence=1.0,
                contributing_signals=("checkout_p95_latency_5m",),
            ),
            CandidateEvent(
                detector_id="auto_checkout_latency_p99",
                timestamp=10,
                flow="checkout",
                service="checkout",
                severity="SEV1",
                signal_id="checkout_p99_latency_5m",
                value=7.4,
                unit="seconds",
                window="5m",
                threshold=2.0,
                quality=SignalQuality.VERIFIED,
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-SLO",
                confidence=1.0,
                contributing_signals=("checkout_p99_latency_5m",),
            ),
        ]


class FakeNotificationSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    def send(self, message):
        if self.fail:
            raise RuntimeError("grafana webhook down")
        self.sent.append(message)
        return {"accepted": True}


class RuntimePipelineTest(unittest.TestCase):
    def test_pipeline_wraps_same_service_signals_into_one_notification(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[ServiceSignalDetector()],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual([message.service for message in result.notifications], ["frontend-proxy", "checkout"])
        self.assertEqual(result.notifications[0].summary, "threshold_breached on frontend_proxy_p99_latency_5m")
        self.assertEqual(result.notifications[1].summary, "threshold_breached on checkout_p95_latency_5m, checkout_p99_latency_5m")

    def test_bad_ratio_slo_incident_is_added_to_rca_anomalies(self):
        event = CandidateEvent(
            timestamp=44,
            detector_id="ops01_checkout_slo",
            flow="checkout",
            service="checkout",
            severity="SEV1",
            signal_id="checkout_bad_ratio_24h",
            value=0.03,
            unit="ratio",
            window="24h",
            threshold=0.01,
            quality=SignalQuality.VERIFIED,
            reason="threshold_breached",
            runbook_id="RB-CHECKOUT-SLO",
        )
        incident = Incident(
            incident_id="inc-slo",
            fingerprint="sha256:slo",
            state="open",
            severity="SEV1",
            flow="checkout",
            service="checkout",
            likely_dependency="unknown",
            events=[event],
        )

        findings = _slo_impact_findings([incident])

        self.assertEqual([finding.signal_id for finding in findings], ["checkout_bad_ratio_24h"])
        self.assertTrue(is_slo_notification(event))
        self.assertTrue(is_slo_notification(event.model_copy(update={"signal_id": "checkout_p95_latency_5m"})))
        self.assertTrue(is_slo_notification(event.model_copy(update={"detector_id": "auto_checkout_error_rate", "signal_id": "checkout_error_rate_5m"})))

    def test_slo_threshold_incident_is_added_to_rca_anomalies(self):
        settings = Settings()
        hyperparameters = load_hyperparameters(settings.hyperparameters_path)["rca"]
        with TemporaryDirectory() as tmp:
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment),
                policy=policy(settings),
                rca_hyperparameters=hyperparameters,
                **runtime_kwargs(settings),
            )
            incident = Incident(
                incident_id="inc-latency",
                fingerprint="sha256:latency",
                state="open",
                severity="SEV1",
                flow="checkout",
                service="checkout",
                likely_dependency="unknown",
                events=[
                    CandidateEvent(
                        timestamp=44,
                        detector_id="ops04_checkout_latency_p95",
                        flow="checkout",
                        service="checkout",
                        severity="SEV1",
                        signal_id="checkout_p95_latency_5m",
                        value=16.0,
                        unit="seconds",
                        window="5m",
                        threshold=0.5,
                        quality=SignalQuality.VERIFIED,
                        reason="threshold_breached",
                        runbook_id="RB-CHECKOUT-LATENCY",
                    )
                ],
            )

            result = pipeline._run_v001_rca([metric("checkout", "p95_latency_5m", [16.0] * 45)], [incident])
            pipeline.store.close()

        self.assertIn("slo_threshold", {finding.algorithm for finding in result.anomalies})

    def test_rca_dedup_respects_configured_one_hop_scope(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            kwargs = runtime_kwargs(settings)
            kwargs["correlation_hyperparameters"] = {**kwargs["correlation_hyperparameters"], "topology_max_hops": 1}
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **kwargs,
            )
            roots = pipeline._dedup_rca_root_causes(
                [
                    RootCauseCandidate(service="frontend-proxy", score=1.0, root_cause_metrics=["latency"]),
                    RootCauseCandidate(service="checkout", score=0.9, root_cause_metrics=["latency"]),
                ]
            )
            store.close()

        self.assertEqual([root.service for root in roots], ["frontend-proxy", "checkout"])

    def test_corroboration_keeps_hard_failure_confidence(self):
        finding = anomaly("error_rate_5m")
        evidence = {"checkout": TelemetryCorroboration(service="checkout", available_sources={"log", "trace"})}

        self.assertEqual(_apply_corroboration([finding], [], evidence, 0.5, 0.15, 0.3)[0].score, 0.5)

    def test_breakout_score_ignores_impact_and_context_metrics(self):
        findings = [
            AnomalyFinding(algorithm="robust_drift", service="checkout", metric="p95_latency_5m", signal_id="checkout_p95_latency_5m", score=10.0, timestamp=1),
            AnomalyFinding(algorithm="ewma_stl", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=10.0, timestamp=1),
            AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="error_budget_burn_rate_24h", signal_id="checkout_error_budget_burn_rate_24h", score=10.0, timestamp=1),
            AnomalyFinding(algorithm="robust_drift", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.3, timestamp=1),
        ]

        self.assertEqual(_algorithm_service_scores(findings), {"checkout": 0.3})

    def test_corroboration_adds_single_and_dual_source_bonus(self):
        finding = anomaly("cpu_millicores")
        trace = {"checkout": TelemetryCorroboration(service="checkout", available_sources={"trace"}, trace_failure=True)}
        both = {"checkout": TelemetryCorroboration(service="checkout", available_sources={"log", "trace"}, log_failure=True, trace_failure=True)}

        self.assertEqual(_apply_corroboration([finding], [], trace, 0.5, 0.15, 0.3)[0].score, 0.65)
        self.assertEqual(_apply_corroboration([finding], [], both, 0.5, 0.15, 0.3)[0].score, 0.8)

    def test_corroboration_lowers_confidence_only_when_source_was_available(self):
        finding = anomaly("cpu_millicores")
        empty = {"checkout": TelemetryCorroboration(service="checkout", available_sources={"log", "trace"})}
        unavailable = {"checkout": TelemetryCorroboration(service="checkout")}

        self.assertEqual(_apply_corroboration([finding], [], empty, 0.5, 0.15, 0.3)[0].score, 0.25)
        self.assertEqual(_apply_corroboration([finding], [], unavailable, 0.5, 0.15, 0.3)[0].score, 0.5)

    def test_corroboration_treats_only_ready_pods_decrease_as_hard(self):
        decrease = metric("checkout", "workload_ready_pods", [2, 2, 2, 2, 2, 1])
        increase = metric("checkout", "workload_ready_pods", [1, 1, 1, 1, 1, 2])
        evidence = {"checkout": TelemetryCorroboration(service="checkout", available_sources={"trace"})}
        finding = anomaly("workload_ready_pods")

        self.assertEqual(_apply_corroboration([finding], [decrease], evidence, 0.5, 0.15, 0.3)[0].score, 0.5)
        self.assertEqual(_apply_corroboration([finding], [increase], evidence, 0.5, 0.15, 0.3)[0].score, 0.25)

    def test_root_cause_logs_conclusion(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            result = RcaResult(
                root_causes=[
                    RootCauseCandidate(
                        service="frontend-proxy",
                        score=0.93,
                        root_cause_metrics=["request_rate_5m", "socket_io_bytes_per_second"],
                        evidence=["graph_score=0.700", "weighted_rrf_score=0.930"],
                    )
                ]
            )

            with self.assertLogs("aiops.pipeline.runtime", level="INFO") as logs:
                pipeline._log_failure_conclusion(result, [])
            store.close()

        text = "\n".join(logs.output)
        self.assertIn("AIOPS_CONCLUSION", text)
        self.assertIn("failed_service=frontend-proxy", text)
        self.assertIn("metrics=request_rate_5m,socket_io_bytes_per_second", text)

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
                        severity="SEV1",
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

    def test_pipeline_notifies_metric_only_rca_root(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                anomalies=[
                    AnomalyFinding(
                        algorithm="isolation_forest",
                        service="frontend",
                        metric="p95_latency_5m",
                        signal_id="frontend_p95_latency_5m",
                        score=5.127,
                        timestamp=123,
                    )
                ],
                root_causes=[
                    RootCauseCandidate(
                        service="frontend",
                        score=0.882,
                        root_cause_metrics=["p95_latency_5m"],
                        evidence=["isolation_forest=5.127"],
                    )
                ],
            )

            with self.assertLogs("aiops.pipeline.runtime", level="INFO") as logs:
                result = pipeline.run_once(metric_series=[metric("frontend", "p95_latency_5m", [0.1] * 31)])
            store.close()

        self.assertEqual(result.candidates, [])
        self.assertEqual([incident.service for incident in result.incidents], ["frontend"])
        self.assertEqual([message.service for message in result.notifications], ["frontend"])
        self.assertEqual(result.notifications[0].flow, "web")
        self.assertEqual(result.notifications[0].title, "RCA root cause: frontend")
        self.assertEqual(result.notifications[0].likely_dependency, "unknown")
        self.assertEqual(result.rca_result.root_causes[0].service, "frontend")
        text = "\n".join(logs.output)
        self.assertIn("AIOPS_DEDUP_RESULT input_candidates=0 incidents=0", text)

    def test_pipeline_dedups_repeated_rca_root_notification(self):
        settings = Settings()
        sender = FakeNotificationSender()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment, rca_dedup_seconds=900)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                notification_sender=sender,
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                root_causes=[RootCauseCandidate(service="payment", score=1.0, root_cause_metrics=["cpu_millicores"])]
            )

            first = pipeline.run_once(metric_series=[metric("payment", "cpu_millicores", [100.0] * 31)])
            second = pipeline.run_once(metric_series=[metric("payment", "cpu_millicores", [100.0] * 31)])
            store.close()

        self.assertEqual([message.service for message in sender.sent], ["payment"])
        self.assertEqual(first.incidents[0].incident_id, second.incidents[0].incident_id)
        self.assertEqual(second.incidents[0].occurrence_count, 2)

    def test_pipeline_dedups_rca_roots_by_topology_before_notification(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            rca_result = RcaResult(
                root_causes=[
                    RootCauseCandidate(service="checkout", score=1.0, root_cause_metrics=["p99_latency_5m"]),
                    RootCauseCandidate(service="payment", score=0.9, root_cause_metrics=["error_rate_5m"]),
                    RootCauseCandidate(service="ad", score=0.8, root_cause_metrics=["error_rate_5m"]),
                ]
            )

            with self.assertLogs("aiops.pipeline.runtime", level="INFO") as logs:
                incidents = pipeline._upsert_rca_root_incidents(rca_result, [])
            notifications = store.pending_notifications_for(incidents)
            store.close()

        self.assertEqual([incident.service for incident in incidents], ["checkout", "ad"])
        self.assertEqual([message.service for message in notifications], ["checkout", "ad"])
        text = "\n".join(logs.output)
        self.assertIn("service=payment kept_service=checkout", text)

    def test_pipeline_keeps_slo_notification_and_adds_rca_root_notification(self):
        settings = Settings()
        sender = FakeNotificationSender()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [Observation(signal_id="checkout_bad_ratio_24h", value=0.2, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
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
                    )
                ],
                store=store,
                policy=policy(settings),
                notification_sender=sender,
                **runtime_kwargs(settings),
            )

            def run_rca(metric_series, incidents):
                self.assertEqual([message.service for message in sender.sent], ["checkout"])
                return RcaResult(
                    anomalies=[
                        AnomalyFinding(
                            algorithm="weighted_sum",
                            service="payment",
                            metric="error_rate_5m",
                            signal_id="payment_error_rate_5m",
                            score=0.8,
                            timestamp=123,
                        )
                    ],
                    root_causes=[RootCauseCandidate(service="payment", score=1.0, root_cause_metrics=["cpu_millicores"])],
                )

            pipeline._run_v001_rca = run_rca

            result = pipeline.run_once(metric_series=[metric("payment", "error_rate_5m", [0.0] * 31)])
            store.close()

        self.assertEqual([incident.service for incident in result.incidents], ["checkout", "payment"])
        self.assertEqual(result.incidents[1].likely_dependency, "unknown")
        self.assertEqual([message.service for message in result.notifications], ["checkout", "payment"])
        self.assertEqual(result.notifications[1].likely_dependency, "unknown")

    def test_pipeline_does_not_notify_invalid_rca_roots(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            incidents = pipeline._upsert_rca_root_incidents(
                RcaResult(
                    root_causes=[
                        RootCauseCandidate(service="frontend", score=0.79, root_cause_metrics=["memory_usage_bytes"]),
                        RootCauseCandidate(service="accounting", score=1.0, root_cause_metrics=[]),
                    ]
                ),
                [],
            )
            store.close()

        self.assertEqual(incidents, [])

    def test_pipeline_flushes_notification_outbox_to_sender(self):
        settings = Settings()
        sender = FakeNotificationSender()
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
                        )
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
                    )
                ],
                store=store,
                policy=policy(settings),
                notification_sender=sender,
                **runtime_kwargs(settings),
            )

            result = pipeline.run_once()
            outbox_row = store._connection.execute(
                "SELECT status, attempt_count FROM notification_outbox WHERE incident_id = ?",
                (result.incidents[0].incident_id,),
            ).fetchone()
            store.close()

        self.assertEqual([message.incident_id for message in sender.sent], [result.incidents[0].incident_id])
        self.assertEqual(outbox_row, ("sent", 1))

    def test_pipeline_logs_notification_ready_after_dedup(self):
        settings = Settings()
        with TemporaryDirectory() as tmp, self.assertLogs("aiops.pipeline.runtime", level="INFO") as logs:
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
                        )
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
                    )
                ],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            pipeline.run_once()
            store.close()

        text = "\n".join(logs.output)
        self.assertRegex(text, r"-+ AIOPS_RUN_START run=\d+ -+")
        self.assertIn("AIOPS_DEDUP_RESULT", text)
        self.assertIn("input_candidates=1 incidents=1", text)
        self.assertIn("AIOPS_CONCLUSION source=incident failed_service=checkout", text)
        self.assertIn("AIOPS_NOTIFY_READY", text)
        self.assertIn("status=pending", text)
        self.assertRegex(text, r"-+ AIOPS_RUN_END run=\d+ candidates=1 incidents=1 root_causes=0 -+")

    def test_pipeline_marks_notification_failure_for_retry(self):
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
                        )
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
                    )
                ],
                store=store,
                policy=policy(settings),
                notification_sender=FakeNotificationSender(fail=True),
                **runtime_kwargs(settings),
            )

            result = pipeline.run_once()
            outbox_row = store._connection.execute(
                "SELECT status, attempt_count, last_error FROM notification_outbox WHERE incident_id = ?",
                (result.incidents[0].incident_id,),
            ).fetchone()
            store.close()

        self.assertEqual(outbox_row, ("retry", 1, "grafana webhook down"))

    def test_slo_notification_failure_uses_common_retry_outbox(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [Observation(signal_id="checkout_p95_latency_5m", value=16.0, unit="seconds", window="5m", quality=SignalQuality.VERIFIED)]
                ),
                detectors=[
                    ThresholdDetector(
                        detector_id="ops04_checkout_latency_p95",
                        signal_id="checkout_p95_latency_5m",
                        threshold=0.5,
                        flow="checkout",
                        service="checkout",
                        severity="SEV1",
                        runbook_id="RB-CHECKOUT-LATENCY",
                    )
                ],
                store=store,
                policy=policy(settings),
                notification_sender=FakeNotificationSender(fail=True),
                **runtime_kwargs(settings),
            )

            with self.assertLogs("aiops.pipeline.runtime", level="WARNING") as logs:
                result = pipeline.run_once()
            counts = store._connection.execute(
                "SELECT (SELECT COUNT(*) FROM incidents), (SELECT COUNT(*) FROM notification_outbox)"
            ).fetchone()
            store.close()

        self.assertEqual(len(result.notifications), 1)
        self.assertEqual(counts, (1, 1))
        self.assertIn("AIOPS_BLOCK notify_failed", " ".join(logs.output))

    def test_pipeline_accepts_current_cdo_signal_shape_before_detection(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=2.0,
                            unit="percent",
                            window="1d",
                            quality=SignalQuality.UNQUALIFIED,
                            labels={
                                "query_id": "checkout.bad_ratio.24h",
                                "service_name": "checkout",
                                "flow": "checkout",
                            },
                        )
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
                    )
                ],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual(result.observations[0].quality, SignalQuality.VERIFIED)
        self.assertEqual(result.observations[0].unit, "ratio")
        self.assertEqual(result.observations[0].window, "24h")
        self.assertEqual(result.observations[0].labels["service"], "checkout")
        self.assertEqual(result.candidates[0].detector_id, "ops01_checkout_slo")

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

    def test_pipeline_extracts_log_evidence_for_v001_rca(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            hyperparameters = load_hyperparameters(settings.hyperparameters_path)["rca"]
            hyperparameters = {
                **hyperparameters,
                "min_points": 8,
                "anomaly": {**hyperparameters["anomaly"], "log_history_buckets": 8, "log_min_nonzero_buckets": 1},
            }
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment),
                policy=policy(settings),
                rca_hyperparameters=hyperparameters,
                runtime_config=load_runtime_config(settings.runtime_config_path),
            )
            incident = Incident(
                incident_id="inc-test",
                fingerprint="sha256:test",
                state="open",
                severity="SEV1",
                flow="checkout",
                service="checkout",
                likely_dependency="payment",
                events=[
                    CandidateEvent(
                        timestamp=10,
                        detector_id="test",
                        flow="checkout",
                        service="checkout",
                        severity="SEV1",
                        signal_id="checkout_error_rate_5m",
                        value=1.0,
                        unit="ratio",
                        window="5m",
                        threshold=0.1,
                        quality=SignalQuality.VERIFIED,
                        reason="test",
                        runbook_id="RB-CHECKOUT-SLO",
                        evidence=(EvidenceItem(source="log", reference="opensearch", summary="count=8 excerpts=['payment failed order=123 status=500']"),),
                    )
                ],
            )

            result = pipeline._run_v001_rca([], [incident])
            pipeline.store.close()

        self.assertEqual(result.root_causes, [])
        self.assertEqual(result.anomalies, [])

    def test_pipeline_records_rca_history_jsonl(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hyperparameters = load_hyperparameters(settings.hyperparameters_path)["rca"]
            store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector(
                    [
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=0.02,
                            unit="ratio",
                            window="24h",
                            quality=SignalQuality.VERIFIED,
                        )
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
                    )
                ],
                store=store,
                policy=policy(settings),
                rca_hyperparameters=hyperparameters,
                rca_history_path=root / "state" / "rca_history.jsonl",
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                anomalies=[
                    AnomalyFinding(
                        algorithm="weighted_sum",
                        service="checkout",
                        metric="error_rate_5m",
                        signal_id="checkout_error_rate_5m",
                        score=1.7,
                        timestamp=59,
                    )
                ],
                root_causes=[
                    RootCauseCandidate(
                        service="checkout",
                        score=1.7,
                        root_cause_metrics=["error_rate_5m"],
                        evidence=["test"],
                    )
                ],
            )

            result = pipeline.run_once(
                metric_series=[
                    metric("checkout", "error_rate_5m", [0.0] * 40 + [0.4] * 20),
                    metric("checkout", "p95_latency_5m", [0.1] * 40 + [1.5] * 20),
                ]
            )
            store.close()
            rows = [json.loads(line) for line in (root / "state" / "rca_history.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["incidents"][0]["service"], "checkout")
        self.assertEqual(rows[0]["incidents"][0]["detectors"], ["ops01_checkout_slo"])
        self.assertEqual([message.service for message in result.notifications], ["checkout", "checkout"])
        self.assertEqual([incident.events[-1].detector_id for incident in result.incidents], ["ops01_checkout_slo", "rca_root_cause"])
        self.assertEqual(rows[0]["parameters"]["min_points"], hyperparameters["min_points"])
        self.assertEqual(rows[0]["series_point_count"]["max"], 60)
        self.assertEqual(rows[0]["root_causes"][0]["service"], result.rca_result.root_causes[0].service)

    def test_pipeline_does_not_suppress_slo_notification_in_blast_radius(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteIncidentStore(root / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[MultiServiceDetector()],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                root_causes=[RootCauseCandidate(service="valkey-cart", score=1.0, root_cause_metrics=["error_rate_5m"])]
            )

            result = pipeline.run_once()
            outbox_rows = store._connection.execute("SELECT incident_id, status FROM notification_outbox ORDER BY incident_id").fetchall()
            store.close()

        self.assertEqual([message.service for message in result.notifications], ["checkout", "cart", "valkey-cart", "valkey-cart"])
        self.assertEqual([status for _, status in outbox_rows].count("suppressed"), 0)
        self.assertEqual([decision.result for decision in result.policy_decisions], ["blocked"])

    def test_pipeline_does_not_suppress_children_for_low_confidence_root_cause(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[MultiServiceDetector()],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                root_causes=[RootCauseCandidate(service="checkout", score=0.79, root_cause_metrics=["error_rate_5m"])]
            )

            result = pipeline.run_once()
            outbox_rows = store._connection.execute("SELECT status FROM notification_outbox").fetchall()
            store.close()

        self.assertEqual({message.service for message in result.notifications}, {"checkout", "cart", "valkey-cart"})
        self.assertEqual([status for (status,) in outbox_rows].count("suppressed"), 0)

    def test_pipeline_suppresses_current_child_root_without_breakout_score(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=900)
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[MultiServiceDetector()],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                root_causes=[RootCauseCandidate(service="cart", score=1.0, root_cause_metrics=["error_rate_5m"])]
            )

            result = pipeline.run_once()
            store.close()

        self.assertIn("cart", {message.service for message in result.notifications})

    def test_pipeline_suppresses_child_while_root_window_is_active(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=300, root_score=1.0)
            incident = store.upsert(
                CandidateEvent(
                    detector_id="auto_cart_error_rate",
                    flow="checkout",
                    service="cart",
                    severity="SEV2",
                    signal_id="cart_error_rate_5m",
                    value=0.2,
                    unit="ratio",
                    window="5m",
                    threshold=0.05,
                    quality=SignalQuality.VERIFIED,
                    reason="threshold_breached",
                    runbook_id="RB-CART-ERROR-RATE",
                )
            )
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            suppressed = pipeline._suppress_related_notifications([incident], RcaResult())
            status = store._connection.execute(
                "SELECT status FROM notification_outbox WHERE incident_id = ?",
                (incident.incident_id,),
            ).fetchone()
            store.close()

        self.assertEqual(suppressed, {incident.incident_id})
        self.assertEqual(status, ("suppressed",))

    def test_pipeline_allows_one_hop_service_at_one_point_five_times_root_score(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=300, root_score=1.0)
            incident = store.upsert(
                CandidateEvent(
                    detector_id="auto_cart_error_rate",
                    flow="checkout",
                    service="cart",
                    severity="SEV2",
                    signal_id="cart_error_rate_5m",
                    value=0.2,
                    unit="ratio",
                    window="5m",
                    threshold=0.05,
                    quality=SignalQuality.VERIFIED,
                    reason="threshold_breached",
                    runbook_id="RB-CART-ERROR-RATE",
                )
            )
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            suppressed = pipeline._suppress_related_notifications(
                [incident],
                RcaResult(
                    algorithm_findings=[
                        AnomalyFinding(
                            algorithm="robust_drift",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.5,
                            timestamp=10,
                        ),
                        AnomalyFinding(
                            algorithm="ewma_stl",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.5,
                            timestamp=10,
                        ),
                        AnomalyFinding(
                            algorithm="isolation_forest",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.5,
                            timestamp=10,
                        )
                    ]
                ),
            )
            notifications = store.pending_notifications_for([incident])
            store.close()

        self.assertEqual(suppressed, set())
        self.assertEqual([message.service for message in notifications], ["cart"])

    def test_pipeline_keeps_one_hop_service_suppressed_below_breakout_score(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=300, root_score=1.0)
            incident = store.upsert(
                CandidateEvent(
                    detector_id="auto_cart_error_rate",
                    flow="checkout",
                    service="cart",
                    severity="SEV2",
                    signal_id="cart_error_rate_5m",
                    value=0.2,
                    unit="ratio",
                    window="5m",
                    threshold=0.05,
                    quality=SignalQuality.VERIFIED,
                    reason="threshold_breached",
                    runbook_id="RB-CART-ERROR-RATE",
                )
            )
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[],
                store=store,
                policy=policy(settings),
                **runtime_kwargs(settings),
            )

            suppressed = pipeline._suppress_related_notifications(
                [incident],
                RcaResult(
                    algorithm_findings=[
                        AnomalyFinding(
                            algorithm="robust_drift",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.49,
                            timestamp=10,
                        ),
                        AnomalyFinding(
                            algorithm="ewma_stl",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.5,
                            timestamp=10,
                        ),
                        AnomalyFinding(
                            algorithm="isolation_forest",
                            service="cart",
                            metric="cpu_millicores",
                            signal_id="cart_cpu_millicores",
                            score=0.5,
                            timestamp=10,
                        )
                    ]
                ),
            )
            store.close()

        self.assertEqual(suppressed, {incident.incident_id})

    def test_pipeline_suppresses_sev1_non_slo_caller_notifications(self):
        settings = Settings()
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment=settings.environment)
            kwargs = runtime_kwargs(settings)
            kwargs["correlation_hyperparameters"] = {**kwargs["correlation_hyperparameters"], "topology_max_hops": 2}
            pipeline = AiopsPipeline(
                collector=StaticCollector([]),
                detectors=[MultiServiceDetector(cart_severity="SEV1", cart_signal_id="cart_request_count_5m")],
                store=store,
                policy=policy(settings),
                **kwargs,
            )
            pipeline._run_v001_rca = lambda metric_series, incidents: RcaResult(
                root_causes=[RootCauseCandidate(service="valkey-cart", score=1.0, root_cause_metrics=["error_rate_5m"])]
            )

            result = pipeline.run_once()
            store.close()

        self.assertEqual({message.service for message in result.notifications}, {"checkout", "valkey-cart"})

    def test_dry_run_remediation_is_not_added_to_success_history(self):
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
            audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        decision = result.remediation_decisions[0]

        self.assertEqual(result.verification_results[0].status, "recovered")
        self.assertEqual(decision.selected_action, "restart_payment")
        self.assertEqual(decision.decision, "dry-run-recorded")
        self.assertEqual(decision.policy_result, "dry-run-recorded")
        self.assertFalse(decision.policy_allowed)
        self.assertFalse(decision.would_execute)
        self.assertEqual(len(history), 1)
        self.assertEqual(audit_rows[0]["selected_action"], "restart_payment")
        self.assertEqual(audit_rows[0]["policy_result"], "dry-run-recorded")


if __name__ == "__main__":
    unittest.main()
