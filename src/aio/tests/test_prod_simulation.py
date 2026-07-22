#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.collectors import StaticCollector
from aiops.config import Settings, build_detectors, load_hyperparameters, load_runtime_config
from aiops.normalization import load_normalization_schema
from aiops.pipeline import AiopsPipeline
from aiops.qualification import load_qualification_schema
from aiops.remediation import PolicyEngine
from aiops.schemas import MetricPoint, MetricSeries, Observation, SignalQuality
from aiops.storage import SQLiteIncidentStore


class FakeNotificationSender:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return {"accepted": True}


def observation(signal_id: str, value: float | None, quality: SignalQuality = SignalQuality.VERIFIED) -> Observation:
    labels = {"service": "checkout", "dependency": "payment"} if signal_id == "checkout_payment_error_rate_5m" else {}
    window = "24h" if signal_id == "checkout_bad_ratio_24h" else "5m"
    unit = "seconds" if "latency" in signal_id else "ratio"
    return Observation(signal_id=signal_id, value=value, unit=unit, window=window, quality=quality, labels=labels)


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


def prod_pipeline(root: Path, sender: FakeNotificationSender, repeat_seconds: int = 900, observations=None, slo_state=None) -> AiopsPipeline:
    settings = Settings().model_copy(update={"state_store_path": root / "aiops.sqlite3"})
    runtime_config = load_runtime_config(settings.runtime_config_path)
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    correlation_hyperparameters = {**hyperparameters["correlation"], "suppress_window_seconds": repeat_seconds}
    store = SQLiteIncidentStore(
        settings.state_store_path,
        settings.environment,
        notification_cooldown_seconds=int(correlation_hyperparameters["suppress_window_seconds"]),
    )
    return AiopsPipeline(
        collector=StaticCollector(observations or []),
        detectors=build_detectors(runtime_config, settings, hyperparameters["no_data"], hyperparameters["detectors"]),
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
        qualification_schema=load_qualification_schema(settings.qualification_schema_path),
        normalization_schema=load_normalization_schema(settings.normalization_schema_path),
        qualification_dev=settings.qualification_gate_dev,
        qualification_max_sample_age_seconds=settings.qualification_max_sample_age_seconds,
        slo_notification_suppress_seconds=hyperparameters["incident"]["direct_slo_suppress_seconds"],
        slo_notification_state=slo_state if slo_state is not None else {},
        rca_hyperparameters=hyperparameters["rca"],
        correlation_hyperparameters=correlation_hyperparameters,
        notification_sender=sender,
        rca_history_path=root / "rca_history.jsonl",
    )


class ProdSimulationTest(unittest.TestCase):
    def test_checkout_latency_slo_breach_sends_notification(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender, observations=[observation("checkout_p95_latency_5m", 16.0)])

            pipeline.run_once()
            pipeline.store.close()

        self.assertEqual([message.runbook_id for message in sender.sent], ["RB-SERVICE-LATENCY"])

    def test_service_error_rate_slo_breach_sends_notification(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender, observations=[observation("payment_error_rate_5m", 0.2)])

            pipeline.run_once()
            pipeline.store.close()

        self.assertEqual([message.runbook_id for message in sender.sent], ["RB-SERVICE-ERROR-RATE"])

    def test_checkout_latency_breach_pages_once(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender, observations=[observation("checkout_p95_latency_5m", 16.0)])

            result = pipeline.run_once()
            pipeline.store.close()

        self.assertEqual([incident.service for incident in result.incidents], ["checkout"])
        self.assertEqual([message.runbook_id for message in sender.sent], ["RB-SERVICE-LATENCY"])

    def test_checkout_payment_dependency_breach_pages_dependency_runbook(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender, observations=[observation("checkout_payment_error_rate_5m", 0.2)])

            result = pipeline.run_once()
            pipeline.store.close()

        self.assertEqual(result.incidents[0].likely_dependency, "payment")
        self.assertEqual(sender.sent[0].runbook_id, "RB-CHECKOUT-DEPENDENCY")

    def test_prometheus_no_data_pages_monitoring(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender, observations=[observation("checkout_bad_ratio_24h", None, SignalQuality.STALE)])

            result = pipeline.run_once()
            pipeline.store.close()

        self.assertEqual(result.incidents[0].service, "aiops")
        self.assertEqual(sender.sent[0].runbook_id, "RB-MONITORING-LOSS")

    def test_metric_only_rca_does_not_create_incident_or_notification(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            pipeline = prod_pipeline(Path(tmp), sender)

            result = pipeline.run_once(
                metric_series=[
                    metric("payment", "error_rate_5m", [0.0] * 350 + [0.4] * 10),
                    metric("payment", "p95_latency_5m", [0.1] * 350 + [1.2] * 10),
                    metric("payment", "request_rate_5m", [10.0] * 350 + [80.0] * 10),
                    metric("payment", "cpu_millicores", [100.0] * 350 + [900.0] * 10),
                ]
            )
            pipeline.store.close()

        self.assertEqual(result.candidates, [])
        self.assertEqual(result.incidents, [])
        self.assertEqual(result.rca_result.root_causes[0].service, "payment")
        self.assertEqual(sender.sent, [])

    def test_repeated_slo_breach_is_suppressed_for_fifteen_minutes_without_persistence(self):
        with TemporaryDirectory() as tmp:
            sender = FakeNotificationSender()
            root = Path(tmp)
            slo_state = {}
            first = prod_pipeline(root, sender, repeat_seconds=0, observations=[observation("checkout_p95_latency_5m", 16.0)], slo_state=slo_state)
            first.run_once()
            first.store.close()

            second = prod_pipeline(root, sender, repeat_seconds=0, observations=[observation("checkout_p95_latency_5m", 17.0)], slo_state=slo_state)
            result = second.run_once()
            counts = second.store._connection.execute(
                "SELECT (SELECT COUNT(*) FROM incidents), (SELECT COUNT(*) FROM notification_outbox)"
            ).fetchone()
            history_exists = (root / "notification_history.jsonl").exists()
            second.store.close()
            for key in slo_state:
                slo_state[key] -= 901
            third = prod_pipeline(root, sender, observations=[observation("checkout_p95_latency_5m", 18.0)], slo_state=slo_state)
            third.run_once()
            third.store.close()

        self.assertEqual(result.incidents[0].occurrence_count, 1)
        self.assertEqual(len(sender.sent), 2)
        self.assertEqual(result.notifications, [])
        self.assertEqual(counts, (0, 0))
        self.assertFalse(history_exists)


if __name__ == "__main__":
    unittest.main()
