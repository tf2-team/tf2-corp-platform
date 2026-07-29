from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiops.remediation import SelfHealConfig, SelfHealOrchestrator
from aiops.schemas import (
    ActionCatalogItem,
    CandidateEvent,
    Feature,
    Incident,
    RootCauseCandidate,
    SignalQuality,
)
from aiops.storage import SQLiteIncidentStore


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class FakeExecutorClient:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.verifications: list[dict] = []
        self.rollbacks: list[dict] = []
        self.live_apply_enabled = True
        self.plan_calls = 0

    def catalog(self, request_id: str | None = None) -> list[dict]:
        return [
            {
                "action_id": "scale_product_catalog",
                "action_type": "scale_deployment",
                "target": "product-catalog",
                "target_kind": "Deployment",
                "namespace": "techx-corp-prod",
                "executor_supported": True,
                "dry_run_supported": True,
                "execute_supported": True,
                "live_execute_supported": True,
                "live_apply_enabled": self.live_apply_enabled,
                "recommendation_only": False,
                "audit_only": False,
                "blocked": False,
                "protected": False,
                "rollback_supported": True,
                "rollback_action_id": "restore_deployment_replicas",
                "verification_query_id": "product-catalog.cpu_millicores",
                "verification_signal_id": "product_catalog_cpu_millicores",
                "policy_id": "phase3-scale-policy-v1",
                "policy_approval_required": True,
            }
        ]

    def plan(self, action: dict) -> dict:
        self.plan_calls += 1
        return {
            "allowed": True,
            "executed": False,
            "status": "planned",
            "plan_hash": "sha256:plan",
            "before": {"replicas": 2, "resource_version": "1"},
            "after": {"replicas": 3},
            "rollback": {"defined": True, "rollback_token": "rbt:one"},
        }

    def execute(self, action: dict) -> dict:
        return {
            "allowed": True,
            "executed": True,
            "status": "running",
            "execution_id": "exec-one",
            "executed_at": self.clock().isoformat(),
            "plan_hash": action["plan_hash"],
            "before": {"replicas": 2, "resource_version": "1"},
            "after": {"replicas": 3, "resource_version": "2"},
            "verification": {"defined": True, "query_id": action["root_cause"]["metrics"][0]},
            "rollback": {"defined": True, "rollback_token": "rbt:one"},
        }

    def record_verification(self, execution_id: str, verification: dict) -> dict:
        self.verifications.append(verification)
        return {
            "execution_id": execution_id,
            "status": "succeeded" if verification["passed"] else "failed",
            "verification": {"defined": True, "passed": verification["passed"]},
        }

    def rollback(self, execution_id: str, request: dict) -> dict:
        self.rollbacks.append(request)
        return {
            "execution_id": execution_id,
            "status": "rolled_back",
            "executed": True,
            "after": {"replicas": 2},
        }


def _incident() -> Incident:
    event = CandidateEvent(
        environment="techx-corp-prod",
        timestamp=1,
        detector_id="cpu-saturation",
        flow="catalog",
        service="product-catalog",
        severity="SEV2",
        signal_id="product_catalog_cpu_millicores",
        value=120.0,
        unit="mCPU",
        window="5m",
        threshold=80.0,
        quality=SignalQuality.VERIFIED,
        reason="cpu_saturation",
        runbook_id="RB-PRODUCT-CATALOG-CPU",
    )
    return Incident(
        incident_id="inc-product-catalog",
        fingerprint="sha256:test",
        state="open",
        severity="SEV2",
        flow="catalog",
        service="product-catalog",
        likely_dependency="unknown",
        events=[event],
    )


def _action() -> ActionCatalogItem:
    return ActionCatalogItem(
        action_id="scale_product_catalog",
        action_type="scale_deployment",
        target="product-catalog",
        target_kind="Deployment",
        cost_min=2,
        downtime_min=0,
        blast_radius_services=["frontend"],
        replicas=3,
        approved=True,
        executor_supported=True,
        execute_supported=True,
        live_execute_supported=True,
        rollback_supported=True,
        rollback_action_id="restore_deployment_replicas",
        verification_query_id="product-catalog.cpu_millicores",
        verification_signal_id="product_catalog_cpu_millicores",
        policy_id="phase3-scale-policy-v1",
        policy_approval_required=True,
    )


def _root() -> RootCauseCandidate:
    return RootCauseCandidate(
        service="product-catalog",
        score=0.9,
        root_cause_metrics=["product_catalog_cpu_millicores"],
    )


def _feature(value: float, timestamp: datetime) -> Feature:
    return Feature(
        signal_id="product_catalog_cpu_millicores",
        value=value,
        unit="mCPU",
        window="5m",
        quality=SignalQuality.VERIFIED,
        status="ready",
        labels={"sample_timestamp": str(timestamp.timestamp())},
    )


def _orchestrator(tmp_path: Path, clock: Clock):
    store = SQLiteIncidentStore(tmp_path / "runtime.sqlite3", "techx-corp-prod")
    client = FakeExecutorClient(clock)
    orchestrator = SelfHealOrchestrator(
        client,
        store,
        SelfHealConfig(
            namespace="techx-corp-prod",
            policy_id="phase3-scale-policy-v1",
            policy_expires_at="2026-08-31T23:59:59Z",
            approval_id="ADR-LIVE-001",
            protected_targets=frozenset({"payment", "postgresql"}),
            verification_deadline_seconds=120,
            min_fresh_samples=2,
            consecutive_passes=2,
            failure_samples=2,
        ),
        clock=clock,
    )
    return orchestrator, client, store


def test_self_heal_success_requires_two_fresh_post_action_samples(tmp_path: Path) -> None:
    clock = Clock()
    orchestrator, client, store = _orchestrator(tmp_path, clock)
    try:
        started = orchestrator.start(_incident(), _action(), _root())
        assert started["status"] == "verifying"
        assert started["executed"] is True

        clock.advance(30)
        first = orchestrator.reconcile([_feature(70, clock())])[0]
        assert first.status == "not_recovered"
        clock.advance(30)
        second = orchestrator.reconcile([_feature(60, clock())])[0]

        assert second.status == "recovered"
        assert client.verifications[-1]["passed"] is True
        assert store.self_heal_workflow("inc-product-catalog")["status"] == "succeeded"
        assert [event["event_type"] for event in store.self_heal_audit_events("inc-product-catalog")] == [
            "plan",
            "execute",
            "verification_sample",
            "verification_sample",
            "verification_passed",
        ]
    finally:
        store.close()


def test_self_heal_fails_closed_when_executor_live_gate_is_disabled(tmp_path: Path) -> None:
    clock = Clock()
    orchestrator, client, store = _orchestrator(tmp_path, clock)
    client.live_apply_enabled = False
    try:
        result = orchestrator.start(_incident(), _action(), _root())

        assert result["status"] == "capability_blocked"
        assert result["reasons"] == ["live_apply_disabled"]
        assert client.plan_calls == 0
        assert store.self_heal_workflow("inc-product-catalog")["status"] == "capability_blocked"

        client.live_apply_enabled = True
        retried = orchestrator.start(_incident(), _action(), _root())
        assert retried["status"] == "verifying"
        assert retried["executed"] is True
        assert client.plan_calls == 1
    finally:
        store.close()


def test_self_heal_rolls_back_after_two_failed_fresh_samples(tmp_path: Path) -> None:
    clock = Clock()
    orchestrator, client, store = _orchestrator(tmp_path, clock)
    try:
        orchestrator.start(_incident(), _action(), _root())
        clock.advance(30)
        orchestrator.reconcile([_feature(110, clock())])
        clock.advance(30)
        result = orchestrator.reconcile([_feature(100, clock())])[0]

        assert result.status == "not_recovered"
        assert result.reason == "post_action_verification_failed_rolled_back"
        assert client.verifications[-1]["passed"] is False
        assert len(client.rollbacks) == 1
        assert store.self_heal_workflow("inc-product-catalog")["status"] == "rolled_back"
        event_types = [event["event_type"] for event in store.self_heal_audit_events("inc-product-catalog")]
        assert event_types[-2:] == ["verification_failed", "rollback"]
    finally:
        store.close()


def test_self_heal_rolls_back_when_fresh_telemetry_never_arrives(tmp_path: Path) -> None:
    clock = Clock()
    orchestrator, client, store = _orchestrator(tmp_path, clock)
    try:
        orchestrator.start(_incident(), _action(), _root())
        clock.advance(121)
        result = orchestrator.reconcile([])[0]

        assert result.reason == "post_action_verification_failed_rolled_back"
        assert client.verifications[-1]["message"] == "verification_inconclusive_timeout"
        assert len(client.rollbacks) == 1
    finally:
        store.close()
