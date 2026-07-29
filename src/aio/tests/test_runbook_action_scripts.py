# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from runbooks.actions import page_oncall, plan_scale_deployment, restore_deployment_replicas, scale_deployment


def _base_context() -> dict:
    return {
        "schema_version": "1.0",
        "incident_id": "inc-product-catalog-cpu-001",
        "action_id": "scale_product_catalog",
        "action_type": "scale_deployment",
        "target": "product-catalog",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "dry_run": True,
        "policy_id": "phase3-scale-policy-v1",
        "policy_approved": True,
        "policy_expires_at": "2026-08-31T23:59:59Z",
        "approval_id": "adr-live-001",
        "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "reason": "cpu_saturation",
        "root_cause_metrics": ["product_catalog_cpu_millicores"],
        "requested_at": "2026-08-01T00:00:00Z",
        "kubernetes_snapshot": {
            "kind": "Deployment",
            "namespace": "techx-corp-prod",
            "name": "product-catalog",
            "replicas": 2,
            "ready_replicas": 2,
            "resource_version": "12345",
        },
    }


def test_plan_scale_deployment_returns_dry_run_plan() -> None:
    response = plan_scale_deployment.run(_base_context())

    assert response["ok"] is True
    assert response["executed"] is False
    assert response["plan"]["before"]["replicas"] == 2
    assert response["plan"]["after"]["replicas"] == 3
    assert response["plan"]["plan_hash"].startswith("sha256:")
    assert response["rollback_token"].startswith("rbt:")
    json.dumps(response)


def test_scale_deployment_executes_valid_phase2_plan() -> None:
    context = _base_context()
    plan = plan_scale_deployment.run(context)
    execute_context = {
        **context,
        "dry_run": False,
        "plan": {**plan["plan"], "rollback_token": plan["rollback_token"]},
        "plan_hash": plan["plan"]["plan_hash"],
        "rollback_token": plan["rollback_token"],
    }

    response = scale_deployment.run(execute_context)

    assert response["ok"] is True
    assert response["executed"] is True
    assert response["before"]["replicas"] == 2
    assert response["after"]["replicas"] == 3
    assert response["rollback_token"] == plan["rollback_token"]
    json.dumps(response)


def test_scale_deployment_rejects_resource_version_mismatch() -> None:
    context = _base_context()
    plan = plan_scale_deployment.run(context)
    execute_context = {
        **context,
        "dry_run": False,
        "plan": {**plan["plan"], "rollback_token": plan["rollback_token"]},
        "plan_hash": plan["plan"]["plan_hash"],
        "rollback_token": plan["rollback_token"],
        "kubernetes_snapshot": {
            "kind": "Deployment",
            "namespace": "techx-corp-prod",
            "name": "product-catalog",
            "replicas": 2,
            "ready_replicas": 2,
            "resource_version": "changed",
        },
    }

    response = scale_deployment.run(execute_context)

    assert response["executed"] is False
    assert "resource_version_mismatch" in response["reasons"]


def test_restore_deployment_replicas_uses_execution_snapshot() -> None:
    context = _base_context()
    plan = plan_scale_deployment.run(context)
    execute_context = {
        **context,
        "dry_run": False,
        "plan": {**plan["plan"], "rollback_token": plan["rollback_token"]},
        "plan_hash": plan["plan"]["plan_hash"],
        "rollback_token": plan["rollback_token"],
    }
    execution = scale_deployment.run(execute_context)
    rollback_context = {
        **context,
        "action_id": "restore_deployment_replicas",
        "action_type": "restore_deployment_replicas",
        "dry_run": False,
        "rollback_token": execution["rollback_token"],
        "execution": execution,
        "kubernetes_snapshot": {"replicas": 3, "resource_version": "12346"},
    }

    response = restore_deployment_replicas.run(rollback_context)

    assert response["ok"] is True
    assert response["executed"] is True
    assert response["after"]["replicas"] == 2
    json.dumps(response)


def test_page_oncall_is_audit_only() -> None:
    response = page_oncall.run({"action_id": "page_oncall", "target": "platform-team", "dry_run": True})

    assert response["ok"] is True
    assert response["executed"] is False
    assert response["audit_only"] is True
    assert response["rollback"]["defined"] is False
    json.dumps(response)
