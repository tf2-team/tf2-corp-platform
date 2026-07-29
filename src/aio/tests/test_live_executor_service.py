# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from aiops.live_executor.service import LiveExecutorService
from aiops.live_executor.app import create_app
from starlette.testclient import TestClient


class FakeDeploymentGateway:
    def __init__(self) -> None:
        self.state = {
            "kind": "Deployment",
            "namespace": "techx-corp-prod",
            "name": "product-catalog",
            "replicas": 2,
            "ready_replicas": 2,
            "resource_version": "12345",
        }
        self.closed = False

    def snapshot(self, namespace: str, name: str) -> dict:
        assert namespace == "techx-corp-prod"
        assert name == "product-catalog"
        return dict(self.state)

    def scale(self, namespace: str, name: str, replicas: int, resource_version: str) -> dict:
        assert resource_version == self.state["resource_version"]
        self.state = {
            **self.state,
            "replicas": replicas,
            "ready_replicas": replicas,
            "resource_version": str(int(self.state["resource_version"]) + 1),
        }
        return dict(self.state)

    def close(self) -> None:
        self.closed = True


def _live_service(path: Path) -> tuple[LiveExecutorService, FakeDeploymentGateway]:
    gateway = FakeDeploymentGateway()
    return (
        LiveExecutorService.from_path(
            path,
            deployment_gateway=gateway,
            allow_live_apply=True,
            cooldown_seconds=0,
        ),
        gateway,
    )


def _request(**overrides) -> dict:
    request = {
        "request_id": "req-20260728-0001",
        "incident_id": "inc-product-catalog-cpu-001",
        "action_id": "scale_product_catalog",
        "action_type": "scale_deployment",
        "target": "product-catalog",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "replicas": 3,
        "policy_id": "phase3-scale-policy-v1",
        "policy_approved": True,
        "policy_expires_at": "2026-08-31T23:59:59Z",
        "approval_id": "adr-live-001",
        "plan_hash": None,
        "rollback_token": None,
        "idempotency_key": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "reason": "cpu_saturation",
        "requested_by": "aiops-runtime",
        "dry_run": True,
        "root_cause": {
            "service": "product-catalog",
            "score": 0.81,
            "metrics": ["product_catalog_cpu_millicores"],
            "evidence_scores": {"weighted_rrf": 0.91},
        },
        "kubernetes_snapshot": {
            "kind": "Deployment",
            "namespace": "techx-corp-prod",
            "name": "product-catalog",
            "replicas": 2,
            "ready_replicas": 2,
            "resource_version": "12345",
        },
    }
    request.update(overrides)
    return request


def test_live_executor_plan_execute_status_rollback(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        assert plan["allowed"] is True
        assert plan["executed"] is False
        assert plan["after"]["replicas"] == 3

        execute_request = _request(
            request_id="req-20260728-0002",
            dry_run=False,
            plan_hash=plan["plan_hash"],
            rollback_token=plan["rollback"]["rollback_token"],
            idempotency_key="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        execution = service.execute(execute_request)
        assert execution["allowed"] is True
        assert execution["executed"] is True
        assert execution["status"] == "running"
        assert gateway.state["replicas"] == 3

        status = service.status(execution["execution_id"])
        assert status["execution_id"] == execution["execution_id"]
        assert status["status"] == "running"

        rollback = service.rollback(
            execution["execution_id"],
            {
                "request_id": "req-20260728-0003",
                "incident_id": "inc-product-catalog-cpu-001",
                "rollback_token": execution["rollback"]["rollback_token"],
                "reason": "verification_failed",
                "requested_by": "aiops-runtime",
                "idempotency_key": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            },
        )
        assert rollback["allowed"] is True
        assert rollback["executed"] is True
        assert rollback["status"] == "rolled_back"
        assert rollback["after"]["replicas"] == 2
        assert gateway.state["replicas"] == 2
        events = service.store.audit_events_for("inc-product-catalog-cpu-001")
        assert [event["event_type"] for event in events] == [
            "plan_recorded",
            "execute_submitted",
            "rollback_submitted",
        ]
        json.dumps(rollback)
    finally:
        service.close()


def test_live_executor_idempotent_execute(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        execute_request = _request(
            request_id="req-20260728-0002",
            dry_run=False,
            plan_hash=plan["plan_hash"],
            rollback_token=plan["rollback"]["rollback_token"],
            idempotency_key="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        )
        first = service.execute(execute_request)
        second = service.execute(execute_request)
        assert first == second
        assert gateway.state["resource_version"] == "12346"
    finally:
        service.close()


def test_live_executor_blocks_stale_state(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        gateway.state["resource_version"] = "changed"
        response = service.execute(
            _request(
                request_id="req-20260728-0002",
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            )
        )
        assert response["allowed"] is False
        assert response["executed"] is False
        assert "resource_version_mismatch" in response["reasons"]
    finally:
        service.close()


def test_live_executor_requires_explicit_live_apply(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        response = service.execute(
            _request(
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            )
        )
        assert response["allowed"] is False
        assert response["executed"] is False
        assert response["reasons"] == ["live_apply_disabled"]
    finally:
        service.close()


def test_live_executor_resolves_allowlist_before_reading_target(tmp_path: Path) -> None:
    service, _ = _live_service(tmp_path / "executor.sqlite3")
    try:
        response = service.plan(
            _request(
                action_id="not_allowlisted",
                target="payment",
                namespace="kube-system",
            )
        )
        assert response["allowed"] is False
        assert "action_not_allowlisted" in response["reasons"]
    finally:
        service.close()


def test_live_executor_records_runtime_verification(tmp_path: Path) -> None:
    service, _ = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        execution = service.execute(
            _request(
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:abababababababababababababababababababababababababababababababab",
            )
        )
        verified = service.record_verification(
            execution["execution_id"],
            {
                "request_id": "req-verify",
                "incident_id": "inc-product-catalog-cpu-001",
                "idempotency_key": "sha256:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
                "passed": True,
                "query_id": "product_catalog_cpu_millicores",
                "message": "fresh samples recovered",
            },
        )
        assert verified["status"] == "succeeded"
        assert verified["verification"]["passed"] is True
        assert service.status(execution["execution_id"])["status"] == "succeeded"

        conflicting = service.record_verification(
            execution["execution_id"],
            {
                "request_id": "req-verify-conflict",
                "incident_id": "inc-product-catalog-cpu-001",
                "idempotency_key": "sha256:edededededededededededededededededededededededededededededededed",
                "passed": False,
                "query_id": "product_catalog_cpu_millicores",
            },
        )
        assert conflicting["allowed"] is False
        assert conflicting["reasons"] == ["verification_already_recorded"]
        assert service.status(execution["execution_id"])["status"] == "succeeded"
    finally:
        service.close()


def test_live_executor_app_auth_and_plan_endpoint(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    try:
        unauthorized = client.post("/v1/actions/plan", json=_request())
        assert unauthorized.status_code == 401

        response = client.post(
            "/v1/actions/plan",
            json=_request(),
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-20260728-0001",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["allowed"] is True
        assert payload["status"] == "planned"
        assert payload["after"]["replicas"] == 3
    finally:
        service.close()


def test_live_executor_app_refuses_live_apply_without_auth_token(tmp_path: Path) -> None:
    service, _ = _live_service(tmp_path / "executor.sqlite3")
    try:
        try:
            create_app(service=service, token="")
        except RuntimeError as exc:
            assert "token is required" in str(exc)
        else:
            raise AssertionError("live executor app must fail closed without authentication")
    finally:
        service.close()
