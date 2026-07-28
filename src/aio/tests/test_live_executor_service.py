from __future__ import annotations

import json
from pathlib import Path

from aiops.live_executor.service import LiveExecutorService
from aiops.live_executor.app import create_app
from starlette.testclient import TestClient


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
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
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
        json.dumps(rollback)
    finally:
        service.close()


def test_live_executor_idempotent_execute(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
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
    finally:
        service.close()


def test_live_executor_blocks_stale_state(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        response = service.execute(
            _request(
                request_id="req-20260728-0002",
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                kubernetes_snapshot={"replicas": 2, "resource_version": "changed"},
            )
        )
        assert response["allowed"] is False
        assert response["executed"] is False
        assert "resource_version_mismatch" in response["reasons"]
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
