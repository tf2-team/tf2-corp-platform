#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from aiops.config import Settings
from aiops.executor import create_executor_app
from aiops.remediation import ActionCatalog, ClosedLoopController, RemediationAuditLog
from aiops.replay import evaluate_replay
from aiops.schemas import (
    CandidateEvent,
    Feature,
    Incident,
    PipelineResult,
    PolicyDecision,
    RemediationDecision,
    ReplayRequest,
    SignalQuality,
)


def incident() -> Incident:
    return Incident(
        incident_id="inc-1",
        fingerprint="sha256:test",
        state="open",
        severity="SEV2",
        flow="checkout",
        service="checkout",
        likely_dependency="payment",
        events=[
            CandidateEvent(
                timestamp=110,
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
                reason="threshold_breached",
                runbook_id="RB-CHECKOUT-DEPENDENCY",
                likely_dependency="payment",
            )
        ],
    )


class FakeExecutor:
    def __init__(self):
        self.requests = []

    def submit_action(self, request):
        self.requests.append(request)
        if request["operation"] == "dry-run":
            return {"status": "validated"}
        if request["operation"] == "execute":
            return {"status": "succeeded", "rollback": {"action_type": "restart", "annotations": {}}}
        return {"status": "rolled-back"}


class FakeCooldownStore:
    def __init__(self):
        self.targets = set()

    def action_cooldown_active(self, target):
        return target in self.targets

    def set_action_cooldown(self, target, cooldown_seconds):
        self.targets.add(target)


class FakeKubernetes:
    def __init__(self):
        self.patches = []

    def get_deployment(self, namespace, name):
        return {
            "spec": {
                "replicas": 2,
                "template": {"metadata": {"annotations": {"existing": "value"}}},
            }
        }

    def patch_deployment(self, namespace, name, patch):
        self.patches.append((namespace, name, patch))
        return {"status": "ok"}


def feature(value: float) -> Feature:
    return Feature(
        signal_id="checkout_payment_error_rate_5m",
        value=value,
        unit="ratio",
        window="5m",
        quality=SignalQuality.VERIFIED,
        status="ready",
        feature_role="dependency_signal",
    )


def empty_result(*, detected: bool) -> PipelineResult:
    current = incident()
    return PipelineResult(
        observations=[],
        features=[],
        candidates=current.events if detected else [],
        incidents=[current] if detected else [],
        notifications=[],
        policy_decisions=[],
        verification_results=[],
    )


class ReplayEvaluationTest(unittest.TestCase):
    def test_scores_positive_negative_lead_time_and_mttd(self):
        request = ReplayRequest(
            baseline_mttd_seconds=60,
            scenarios=[
                {
                    "scenario_id": "incident",
                    "expected_incident": True,
                    "incident_start_timestamp": 100,
                    "expected_service": "checkout",
                },
                {"scenario_id": "healthy", "expected_incident": False},
            ],
        )
        results = iter([empty_result(detected=True), empty_result(detected=False)])

        report = evaluate_replay(request, lambda _: next(results))

        self.assertEqual(report.metrics.precision, 1.0)
        self.assertEqual(report.metrics.recall, 1.0)
        self.assertEqual(report.metrics.mttd_after_seconds, 10.0)
        self.assertEqual(report.metrics.mttd_improvement_seconds, 50.0)
        self.assertTrue(report.cases[0].service_correct)


class ClosedLoopControllerTest(unittest.TestCase):
    def controller(self, root: Path, fresh_value: float):
        actions = root / "actions.json"
        actions.write_text(
            json.dumps(
                [
                    {
                        "action_id": "restart_payment",
                        "action_type": "restart",
                        "target": "payment",
                        "target_kind": "Deployment",
                        "cost_min": 1,
                        "downtime_min": 1,
                        "blast_radius_services": ["checkout"],
                        "replicas": 3,
                    }
                ]
            ),
            encoding="utf-8",
        )
        executor = FakeExecutor()
        cooldown = FakeCooldownStore()
        return (
            ClosedLoopController(
                executor=executor,
                catalog=ActionCatalog(actions),
                audit=RemediationAuditLog(root / "audit.jsonl"),
                cooldown_store=cooldown,
                fresh_features=lambda: [feature(fresh_value)],
                cooldown_seconds=300,
                blast_radius_limit=3,
            ),
            executor,
            cooldown,
        )

    def inputs(self):
        remediation = RemediationDecision(
            incident_id="inc-1",
            selected_action="restart_payment",
            target="payment",
            confidence=0.9,
            expected_cost=2,
            decision="live-approved",
            fallback=False,
        )
        policy = PolicyDecision(
            incident_id="inc-1",
            action_type="restart",
            target="payment",
            allowed=True,
            result="allowed",
        )
        return remediation, policy

    def test_dry_runs_executes_and_verifies_with_fresh_telemetry(self):
        with TemporaryDirectory() as tmp:
            controller, executor, cooldown = self.controller(Path(tmp), fresh_value=0.01)
            remediation, policy = self.inputs()

            lifecycles, verification = controller.run([incident()], [remediation], [policy])

            self.assertEqual([request["operation"] for request in executor.requests], ["dry-run", "execute"])
            self.assertEqual(verification[0].status, "recovered")
            self.assertEqual(lifecycles[0].verification_status, "recovered")
            self.assertEqual(lifecycles[0].rollback_status, "not-required")
            self.assertIn("payment", cooldown.targets)

    def test_rolls_back_when_post_action_verification_fails(self):
        with TemporaryDirectory() as tmp:
            controller, executor, _ = self.controller(Path(tmp), fresh_value=0.2)
            remediation, policy = self.inputs()

            lifecycles, verification = controller.run([incident()], [remediation], [policy])

            self.assertEqual([request["operation"] for request in executor.requests], ["dry-run", "execute", "rollback"])
            self.assertEqual(verification[0].status, "not_recovered")
            self.assertEqual(lifecycles[0].rollback_status, "succeeded")
            self.assertFalse(lifecycles[0].escalated)

    def test_cooldown_blocks_repeated_action(self):
        with TemporaryDirectory() as tmp:
            controller, executor, cooldown = self.controller(Path(tmp), fresh_value=0.01)
            remediation, policy = self.inputs()
            cooldown.targets.add("payment")

            lifecycles, verification = controller.run([incident()], [remediation], [policy])

            self.assertEqual(executor.requests, [])
            self.assertEqual(verification, [])
            self.assertIn("action_cooldown_active", lifecycles[0].reasons)


class ScopedExecutorTest(unittest.TestCase):
    def test_dry_run_execute_and_rollback_are_scoped_and_idempotent(self):
        with TemporaryDirectory() as tmp:
            settings = Settings(
                _env_file=None,
                executor_shared_secret="test-secret",
                executor_allowed_targets="payment",
                executor_state_path=Path(tmp) / "executor.sqlite3",
            )
            kubernetes = FakeKubernetes()
            headers = {"Authorization": "Bearer test-secret"}
            base = {
                "incident_id": "inc-1",
                "action_id": "restart_payment",
                "action_type": "restart",
                "target": "payment",
                "target_kind": "Deployment",
                "replicas": 3,
            }
            with TestClient(create_executor_app(settings, kubernetes)) as client:
                dry_run = client.post(
                    "/actions",
                    headers=headers,
                    json={**base, "operation": "dry-run", "idempotency_key": "dry-1"},
                )
                execute = client.post(
                    "/actions",
                    headers=headers,
                    json={**base, "operation": "execute", "idempotency_key": "execute-1"},
                )
                duplicate = client.post(
                    "/actions",
                    headers=headers,
                    json={**base, "operation": "execute", "idempotency_key": "execute-1"},
                )
                rollback = client.post(
                    "/actions",
                    headers=headers,
                    json={
                        **base,
                        "operation": "rollback",
                        "idempotency_key": "rollback-1",
                        "rollback": execute.json()["rollback"],
                    },
                )

            self.assertEqual(dry_run.json()["status"], "validated")
            self.assertEqual(execute.json()["status"], "succeeded")
            self.assertEqual(duplicate.json(), execute.json())
            self.assertEqual(rollback.json()["status"], "rolled-back")
            self.assertEqual(len(kubernetes.patches), 2)

    def test_rejects_target_outside_allowlist(self):
        with TemporaryDirectory() as tmp:
            settings = Settings(
                _env_file=None,
                executor_shared_secret="test-secret",
                executor_allowed_targets="payment",
                executor_state_path=Path(tmp) / "executor.sqlite3",
            )
            with TestClient(create_executor_app(settings, FakeKubernetes())) as client:
                response = client.post(
                    "/actions",
                    headers={"Authorization": "Bearer test-secret"},
                    json={
                        "operation": "dry-run",
                        "incident_id": "inc-1",
                        "action_id": "restart_checkout",
                        "action_type": "restart",
                        "target": "checkout",
                        "target_kind": "Deployment",
                        "replicas": 3,
                        "idempotency_key": "outside",
                    },
                )

            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
