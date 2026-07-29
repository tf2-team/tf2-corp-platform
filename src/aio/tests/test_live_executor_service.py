# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
from aiops.live_executor.kubernetes import KubernetesDeploymentGateway
from aiops.live_executor.service import LiveExecutorService
from aiops.live_executor.app import create_app
from aiops.live_executor.store import LiveExecutorStore
from runbooks.actions.common import ALLOWLIST
from starlette.testclient import TestClient


class FakeDeploymentGateway:
    def __init__(self) -> None:
        self.state = {
            "kind": "Deployment",
            "namespace": "techx-corp-prod",
            "name": "product-catalog",
            "replicas": 2,
            "ready_replicas": 2,
            "scaling_controller": "HorizontalPodAutoscaler",
            "control_replicas": 2,
            "autoscaler_max_replicas": 12,
            "resource_version": "12345",
        }
        self.closed = False

    def snapshot(self, namespace: str, name: str) -> dict:
        assert namespace == "techx-corp-prod"
        assert name == "product-catalog"
        return dict(self.state)

    def scale(self, namespace: str, name: str, replicas: int, resource_version: str) -> dict:
        assert resource_version == self.state["resource_version"]
        observed_replicas = max(int(self.state["replicas"]), replicas)
        observed_ready_replicas = max(int(self.state["ready_replicas"]), replicas)
        self.state = {
            **self.state,
            "replicas": observed_replicas,
            "ready_replicas": observed_ready_replicas,
            "control_replicas": replicas,
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
            approval_id="adr-live-001",
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
        assert rollback["after"]["control_replicas"] == 2
        assert gateway.state["control_replicas"] == 2
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

        replay = service.execute({**execute_request, "incident_id": "inc-other"})
        assert replay["allowed"] is False
        assert replay["reasons"] == ["idempotency_context_mismatch"]
        assert gateway.state["resource_version"] == "12346"
    finally:
        service.close()


def test_live_executor_rejects_plan_replay_under_another_incident(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        response = service.execute(
            _request(
                request_id="req-20260728-replay",
                incident_id="inc-other",
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:1010101010101010101010101010101010101010101010101010101010101010",
            )
        )

        assert response["allowed"] is False
        assert response["executed"] is False
        assert response["reasons"] == ["incident_id_mismatch"]
        assert gateway.state["replicas"] == 2
        assert [event["event_type"] for event in service.store.audit_events_for("inc-other")] == [
            "execute_blocked"
        ]
    finally:
        service.close()


def test_live_executor_allows_same_key_for_plan_and_execute(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        request = _request()
        plan = service.plan(request)
        execute_request = _request(
            request_id="req-20260728-0002",
            dry_run=False,
            plan_hash=plan["plan_hash"],
            rollback_token=plan["rollback"]["rollback_token"],
        )
        first = service.execute(execute_request)
        second = service.execute(execute_request)

        assert first == second
        assert first["executed"] is True
        assert gateway.state["resource_version"] == "12346"
    finally:
        service.close()


def test_live_executor_never_plans_a_scale_down(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        gateway.state.update({"replicas": 7, "ready_replicas": 7, "control_replicas": 2})
        plan = service.plan(_request())

        assert plan["allowed"] is True
        assert plan["before"]["replicas"] == 7
        assert plan["after"]["replicas"] == 8
    finally:
        service.close()


def test_live_executor_blocks_when_autoscaler_capacity_is_exhausted(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        gateway.state.update({"replicas": 12, "ready_replicas": 12})
        response = service.plan(_request())

        assert response["allowed"] is False
        assert response["reasons"] == ["scale_capacity_exhausted"]
    finally:
        service.close()


def test_live_executor_requires_matching_executor_approval(tmp_path: Path) -> None:
    service, _ = _live_service(tmp_path / "executor.sqlite3")
    try:
        response = service.plan(_request(approval_id="different-approval"))

        assert response["allowed"] is False
        assert response["reasons"] == ["approval_id_mismatch"]
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


def test_live_executor_scopes_allowlist_to_configured_environment(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(
        tmp_path / "executor.sqlite3",
        environment="techx-corp-dev",
    )
    try:
        request = _request(
            namespace="techx-corp-dev",
            kubernetes_snapshot={
                "kind": "Deployment",
                "namespace": "techx-corp-dev",
                "name": "product-catalog",
                "replicas": 2,
                "ready_replicas": 2,
                "scaling_controller": "Deployment",
                "control_replicas": 2,
                "resource_version": "dev-1",
            },
        )
        response = service.plan(request)

        assert response["allowed"] is True
        assert response["namespace"] == "techx-corp-dev"
        assert service.catalog()[0]["namespace"] == "techx-corp-dev"
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
                "query_id": "product-catalog.cpu_millicores",
                "message": "fresh samples recovered",
            },
        )
        assert verified["status"] == "succeeded"
        assert verified["verification"]["passed"] is True
        assert verified["after"]["control_released"] is True
        assert verified["after"]["control_replicas"] == 2
        assert verified["after"]["requested_replicas"] == 3
        assert service.status(execution["execution_id"])["status"] == "succeeded"

        conflicting = service.record_verification(
            execution["execution_id"],
            {
                "request_id": "req-verify-conflict",
                "incident_id": "inc-product-catalog-cpu-001",
                "idempotency_key": "sha256:edededededededededededededededededededededededededededededededed",
                "passed": False,
                "query_id": "product-catalog.cpu_millicores",
            },
        )
        assert conflicting["allowed"] is False
        assert conflicting["reasons"] == ["verification_already_recorded"]
        assert service.status(execution["execution_id"])["status"] == "succeeded"
    finally:
        service.close()


def test_live_executor_binds_verification_and_rollback_to_execution_context(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        execution = service.execute(
            _request(
                request_id="req-context-execute",
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:2020202020202020202020202020202020202020202020202020202020202020",
            )
        )

        wrong_incident = service.record_verification(
            execution["execution_id"],
            {
                "request_id": "req-context-verify-incident",
                "incident_id": "inc-other",
                "idempotency_key": "sha256:3030303030303030303030303030303030303030303030303030303030303030",
                "passed": True,
                "query_id": "product-catalog.cpu_millicores",
            },
        )
        assert wrong_incident["reasons"] == ["incident_id_mismatch"]

        wrong_query = service.record_verification(
            execution["execution_id"],
            {
                "request_id": "req-context-verify-query",
                "incident_id": "inc-product-catalog-cpu-001",
                "idempotency_key": "sha256:4040404040404040404040404040404040404040404040404040404040404040",
                "passed": True,
                "query_id": "product-catalog.p95_latency_5m",
            },
        )
        assert wrong_query["reasons"] == ["query_id_mismatch"]

        wrong_rollback = service.rollback(
            execution["execution_id"],
            {
                "request_id": "req-context-rollback",
                "incident_id": "inc-other",
                "rollback_token": execution["rollback"]["rollback_token"],
                "reason": "verification_failed",
                "requested_by": "aiops-runtime",
                "idempotency_key": "sha256:5050505050505050505050505050505050505050505050505050505050505050",
            },
        )
        assert wrong_rollback["reasons"] == ["incident_id_mismatch"]
        assert gateway.state["control_replicas"] == 3
        assert service.status(execution["execution_id"])["status"] == "running"
    finally:
        service.close()


def test_live_executor_rejects_success_until_requested_pods_are_ready(tmp_path: Path) -> None:
    service, gateway = _live_service(tmp_path / "executor.sqlite3")
    try:
        plan = service.plan(_request())
        execution = service.execute(
            _request(
                dry_run=False,
                plan_hash=plan["plan_hash"],
                rollback_token=plan["rollback"]["rollback_token"],
                idempotency_key="sha256:1212121212121212121212121212121212121212121212121212121212121212",
            )
        )
        gateway.state["ready_replicas"] = 2
        request = {
            "request_id": "req-verify-ready",
            "incident_id": "inc-product-catalog-cpu-001",
            "idempotency_key": "sha256:3434343434343434343434343434343434343434343434343434343434343434",
            "passed": True,
            "query_id": "product-catalog.cpu_millicores",
        }
        blocked = service.record_verification(execution["execution_id"], request)
        assert blocked["status"] == "blocked"
        assert blocked["reasons"] == ["target_not_ready"]

        gateway.state["ready_replicas"] = 3
        verified = service.record_verification(execution["execution_id"], request)
        assert verified["status"] == "succeeded"
        assert verified["after"]["ready_replicas"] == 3
    finally:
        service.close()


def test_live_executor_app_auth_and_plan_endpoint(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    try:
        unauthorized = client.post("/v1/actions/plan", json=_request())
        assert unauthorized.status_code == 401

        api_request = _request()
        api_request.pop("kubernetes_snapshot")
        response = client.post(
            "/v1/actions/plan",
            json=api_request,
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


def test_live_executor_app_rejects_invalid_contract_input_without_500(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    try:
        api_request = _request(policy_expires_at="not-a-timestamp")
        api_request.pop("kubernetes_snapshot")
        response = client.post(
            "/v1/actions/plan",
            json=api_request,
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-20260728-0001",
            },
        )
        assert response.status_code == 422

        api_request = _request(unexpected_field=True)
        api_request.pop("kubernetes_snapshot")
        response = client.post(
            "/v1/actions/plan",
            json=api_request,
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-20260728-0001",
            },
        )
        assert response.status_code == 422
    finally:
        service.close()


def test_live_executor_app_rejects_spoofed_auth_context(tmp_path: Path) -> None:
    service = LiveExecutorService.from_path(tmp_path / "executor.sqlite3")
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    api_request = _request()
    api_request.pop("kubernetes_snapshot")
    try:
        wrong_account = client.post(
            "/v1/actions/plan",
            json=api_request,
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "another-service",
                "X-Request-Id": api_request["request_id"],
            },
        )
        assert wrong_account.status_code == 403

        wrong_request_id = client.post(
            "/v1/actions/plan",
            json=api_request,
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-header-does-not-match",
            },
        )
        assert wrong_request_id.status_code == 400
        assert wrong_request_id.json()["detail"] == "request id header does not match body"
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


def test_live_executor_app_refuses_live_apply_without_executor_approval(tmp_path: Path) -> None:
    gateway = FakeDeploymentGateway()
    service = LiveExecutorService.from_path(
        tmp_path / "executor.sqlite3",
        deployment_gateway=gateway,
        allow_live_apply=True,
    )
    try:
        try:
            create_app(service=service, token="test-token")
        except RuntimeError as exc:
            assert "approval id is required" in str(exc)
        else:
            raise AssertionError("live executor app must fail closed without executor approval")
    finally:
        service.close()


def test_kubernetes_gateway_scales_hpa_minimum_instead_of_deployment() -> None:
    calls: list[tuple[str, str, dict | None]] = []
    deployment = {
        "kind": "Deployment",
        "metadata": {"namespace": "techx-corp-prod", "name": "product-catalog", "resourceVersion": "dep-1"},
        "spec": {"replicas": 7},
        "status": {"readyReplicas": 7},
    }
    autoscaler = {
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"namespace": "techx-corp-prod", "name": "product-catalog", "resourceVersion": "hpa-1"},
        "spec": {"minReplicas": 2, "maxReplicas": 12},
        "status": {"currentReplicas": 7, "desiredReplicas": 7},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path.endswith("/horizontalpodautoscalers/product-catalog"):
            if request.method == "PATCH":
                updated = {
                    **autoscaler,
                    "metadata": {**autoscaler["metadata"], "resourceVersion": "hpa-2"},
                    "spec": {**autoscaler["spec"], "minReplicas": payload["spec"]["minReplicas"]},
                }
                return httpx.Response(200, json=updated)
            return httpx.Response(200, json=autoscaler)
        return httpx.Response(200, json=deployment)

    gateway = KubernetesDeploymentGateway(
        "https://kubernetes.example",
        transport=httpx.MockTransport(handler),
    )
    try:
        snapshot = gateway.snapshot("techx-corp-prod", "product-catalog")
        assert snapshot["scaling_controller"] == "HorizontalPodAutoscaler"
        assert snapshot["control_replicas"] == 2
        result = gateway.scale("techx-corp-prod", "product-catalog", 8, snapshot["resource_version"])
        assert result["control_replicas"] == 8
        assert (
            "PATCH",
            "/apis/autoscaling/v2/namespaces/techx-corp-prod/horizontalpodautoscalers/product-catalog",
            {"metadata": {"resourceVersion": "hpa-1"}, "spec": {"minReplicas": 8}},
        ) in calls
        assert not any(
            method == "PATCH" and "/apis/apps/v1/" in path
            for method, path, _ in calls
        )
    finally:
        gateway.close()


def test_live_executor_store_migrates_legacy_idempotency_key(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?)",
        ("shared", "plan", '{"status":"planned"}', "2026-07-29T00:00:00Z"),
    )
    connection.commit()
    connection.close()

    service = LiveExecutorService.from_path(path)
    try:
        service.store.save_idempotency("shared", "execute", {"status": "running"})
        assert service.store.get_idempotency("shared", "plan") == {"status": "planned"}
        assert service.store.get_idempotency("shared", "execute") == {"status": "running"}
    finally:
        service.close()


def test_live_executor_catalog_endpoint_returns_action_capabilities(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = LiveExecutorService(
        LiveExecutorStore(tmp_path / "executor.sqlite3"),
        capability_catalog_path=root / "config" / "executor_supported_actions.json",
        service_support_catalog_path=root / "config" / "executor_service_support.json",
    )
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/actions/catalog",
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-20260729-catalog",
            },
        )
        assert response.status_code == 200
        catalog = {item["action_id"]: item for item in response.json()}

        scale = catalog["scale_product_catalog"]
        allowlist = ALLOWLIST["scale_product_catalog"]
        assert scale["executor_supported"] is True
        assert scale["live_execute_supported"] is True
        assert scale["live_apply_enabled"] is False
        assert scale["rollback_supported"] is True
        assert scale["rollback_action_id"] == allowlist["rollback_action_id"]
        assert scale["verification_query_id"] == allowlist["verification_query_id"]
        assert scale["namespace"] == allowlist["namespace"]
        assert scale["min_replicas"] == allowlist["min_replicas"]
        assert scale["max_replicas"] == allowlist["max_replicas"]
        assert scale["blast_radius_services"] == allowlist["blast_radius_services"]

        restart_actions = [item for item in catalog.values() if item["action_type"] == "restart"]
        assert restart_actions
        assert all(item["executor_supported"] is False for item in restart_actions)
        assert catalog["restart_payment"]["protected"] is True
        assert catalog["restart_payment"]["blocked"] is True
    finally:
        service.close()


def test_live_executor_services_catalog_covers_runbook_services(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = LiveExecutorService(
        LiveExecutorStore(tmp_path / "executor.sqlite3"),
        capability_catalog_path=root / "config" / "executor_supported_actions.json",
        service_support_catalog_path=root / "config" / "executor_service_support.json",
    )
    app = create_app(service=service, token="test-token")
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/services/catalog",
            headers={
                "Authorization": "Bearer test-token",
                "X-AIOPS-Account": "aiops-runtime",
                "X-Request-Id": "req-20260729-services-catalog",
            },
        )
        assert response.status_code == 200
        service_catalog = {item["service"]: item for item in response.json()}
        runbook_map = json.loads((root / "runbooks" / "service_runbook_map.json").read_text(encoding="utf-8"))

        assert set(service_catalog) == set(runbook_map["services"])
        assert service_catalog["product-catalog"]["executor_supported"] is True
        assert service_catalog["product-catalog"]["supported_actions"] == ["scale_product_catalog"]
        assert service_catalog["product-catalog"]["live_execute_supported"] is True
        assert service_catalog["product-catalog"]["live_apply_enabled"] is False
        assert service_catalog["checkout"]["support_status"] == "recommendation_only"
        assert service_catalog["checkout"]["supported_actions"] == []
        assert service_catalog["payment"]["protected"] is True
        assert service_catalog["postgresql"]["fallback_action"] == "page_data_oncall"
    finally:
        service.close()


def test_live_executor_catalog_reports_implementation_and_runtime_gate_separately(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = LiveExecutorService(
        LiveExecutorStore(tmp_path / "executor.sqlite3"),
        deployment_gateway=FakeDeploymentGateway(),
        allow_live_apply=True,
        approval_id="adr-live-001",
        capability_catalog_path=root / "config" / "executor_supported_actions.json",
        service_support_catalog_path=root / "config" / "executor_service_support.json",
    )
    try:
        scale = next(item for item in service.catalog() if item["action_id"] == "scale_product_catalog")
        product_catalog = next(
            item for item in service.service_catalog() if item["service"] == "product-catalog"
        )

        assert scale["live_execute_supported"] is True
        assert scale["live_apply_enabled"] is True
        assert product_catalog["live_execute_supported"] is True
        assert product_catalog["live_apply_enabled"] is True
    finally:
        service.close()
