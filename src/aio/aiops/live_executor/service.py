#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runbooks.actions import page_oncall, plan_scale_deployment, restore_deployment_replicas, scale_deployment
from runbooks.actions.common import (
    ALLOWLIST,
    POLICY_EXPIRES_AT,
    POLICY_ID,
    PROTECTED_NAMESPACES,
    PROTECTED_TARGETS,
    block_response,
    stable_hash,
    utc_now,
)

from aiops.live_executor.store import LiveExecutorStore, utc_now_text


STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_BLOCKED = "blocked"
STATUS_ROLLED_BACK = "rolled_back"
DEFAULT_CAPABILITY_CATALOG_PATH = Path("config/executor_supported_actions.json")


class LiveExecutorService:
    def __init__(self, store: LiveExecutorStore, capability_catalog_path: Path | None = None):
        self.store = store
        self.capability_catalog_path = capability_catalog_path or DEFAULT_CAPABILITY_CATALOG_PATH

    @classmethod
    def from_path(cls, path: Path) -> "LiveExecutorService":
        return cls(LiveExecutorStore(path))

    def catalog(self) -> list[dict[str, Any]]:
        return _load_capability_catalog(self.capability_catalog_path)

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "plan")
        if cached is not None:
            return cached

        response = _script_response_to_api(plan_scale_deployment.run({**request, "dry_run": True}), STATUS_PLANNED)
        response["incident_id"] = request.get("incident_id")
        self._audit(request, response, "plan_recorded")
        if response["allowed"]:
            self.store.save_plan(response)
        self._save_idempotency(request, "plan", response)
        return response

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "execute")
        if cached is not None:
            return cached

        plan_hash = request.get("plan_hash")
        plan_response = self.store.get_plan_response(plan_hash) if isinstance(plan_hash, str) else None
        if plan_response is None:
            response = self._blocked(request, "missing or unknown plan", ["missing_plan"])
        else:
            running = self.store.execution_for_target(plan_response["target"])
            if running is not None:
                response = self._blocked(request, "target already has a running execution", ["single_flight_target"])
            else:
                script_context = _request_to_script_context(request, plan_response)
                response = _script_response_to_api(scale_deployment.run(script_context), STATUS_RUNNING)
                response["incident_id"] = request.get("incident_id")
                response["plan_hash"] = plan_hash
                if response["executed"]:
                    self.store.save_execution(response, STATUS_RUNNING)
        self._audit(request, response, "execute_submitted" if response["executed"] else "execute_blocked")
        self._save_idempotency(request, "execute", response)
        return response

    def status(self, execution_id: str) -> dict[str, Any]:
        response = self.store.get_execution_response(execution_id)
        if response is None:
            return self._blocked({"action_id": "unknown"}, "execution not found", ["execution_not_found"])
        return response

    def rollback(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "rollback")
        if cached is not None:
            return cached

        execution = self.store.get_execution_response(execution_id)
        if execution is None:
            response = self._blocked(request, "execution not found", ["execution_not_found"])
        else:
            script_execution = {
                **execution,
                "rollback_token": execution.get("rollback_token") or (execution.get("rollback") or {}).get("rollback_token"),
            }
            script_context = {
                "schema_version": request.get("schema_version", "1.0"),
                "incident_id": request.get("incident_id") or execution.get("incident_id"),
                "action_id": "restore_deployment_replicas",
                "action_type": "restore_deployment_replicas",
                "target": execution["target"],
                "target_kind": "Deployment",
                "namespace": execution.get("namespace"),
                "dry_run": False,
                "policy_id": request.get("policy_id", POLICY_ID),
                "policy_approved": request.get("policy_approved", True),
                "policy_expires_at": request.get("policy_expires_at", "2026-08-31T23:59:59Z"),
                "idempotency_key": request.get("idempotency_key"),
                "reason": request.get("reason", "rollback_requested"),
                "root_cause_metrics": [],
                "rollback_token": request.get("rollback_token"),
                "execution": script_execution,
                "kubernetes_snapshot": request.get("kubernetes_snapshot") or execution.get("after"),
            }
            response = _script_response_to_api(restore_deployment_replicas.run(script_context), STATUS_ROLLED_BACK)
            response["incident_id"] = script_context["incident_id"]
            if response["executed"]:
                self.store.save_execution(response, STATUS_ROLLED_BACK)
        self._audit(request, response, "rollback_submitted" if response["executed"] else "rollback_blocked")
        self._save_idempotency(request, "rollback", response)
        return response

    def legacy_submit(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("action_type") == "page":
            response = _script_response_to_api(page_oncall.run(request), STATUS_PLANNED)
            self._audit(request, response, "page_recorded")
            return response
        if request.get("dry_run") is True or not request.get("plan_hash"):
            return self.plan(request)
        return self.execute(request)

    def _idempotent(self, request: dict[str, Any], operation: str) -> dict[str, Any] | None:
        key = request.get("idempotency_key")
        if isinstance(key, str):
            return self.store.get_idempotency(key, operation)
        return None

    def _save_idempotency(self, request: dict[str, Any], operation: str, response: dict[str, Any]) -> None:
        key = request.get("idempotency_key")
        if isinstance(key, str):
            self.store.save_idempotency(key, operation, response)

    def _blocked(self, request: dict[str, Any], message: str, reasons: list[str]) -> dict[str, Any]:
        response = block_response(request, message, reasons)
        return _script_response_to_api(response, STATUS_BLOCKED)

    def _audit(self, request: dict[str, Any], response: dict[str, Any], event_type: str) -> None:
        target = {
            "kind": response.get("target_kind"),
            "namespace": response.get("namespace"),
            "name": response.get("target"),
        }
        event_seed = {
            "timestamp": utc_now_text(),
            "request_id": request.get("request_id"),
            "incident_id": request.get("incident_id") or response.get("incident_id"),
            "action_id": response.get("action_id"),
            "event_type": event_type,
            "target": target,
        }
        self.store.audit(
            {
                "event_id": "evt-" + stable_hash(event_seed).split(":", 1)[1][:16],
                "timestamp": utc_now_text(),
                "request_id": request.get("request_id"),
                "incident_id": request.get("incident_id") or response.get("incident_id"),
                "execution_id": response.get("execution_id"),
                "action_id": response.get("action_id"),
                "event_type": event_type,
                "actor_type": "service",
                "actor_id": request.get("requested_by", "aiops-runtime"),
                "policy_id": request.get("policy_id"),
                "allowed": response.get("allowed", False),
                "executed": response.get("executed", False),
                "reasons": response.get("reasons", []),
                "target": target,
            }
        )

    def close(self) -> None:
        self.store.close()


def _request_to_script_context(request: dict[str, Any], plan_response: dict[str, Any]) -> dict[str, Any]:
    plan = {
        **(plan_response.get("plan") or {}),
        "plan_hash": plan_response.get("plan_hash"),
        "expires_at": plan_response.get("expires_at"),
        "before": plan_response.get("before"),
        "after": plan_response.get("after"),
        "rollback_token": plan_response.get("rollback", {}).get("rollback_token"),
    }
    before = plan.get("before") or {}
    return {
        "schema_version": request.get("schema_version", "1.0"),
        "incident_id": request.get("incident_id"),
        "action_id": request.get("action_id"),
        "action_type": request.get("action_type"),
        "target": request.get("target"),
        "target_kind": request.get("target_kind"),
        "namespace": request.get("namespace"),
        "dry_run": False,
        "policy_id": request.get("policy_id"),
        "policy_approved": request.get("policy_approved"),
        "policy_expires_at": request.get("policy_expires_at", "2026-08-31T23:59:59Z"),
        "idempotency_key": request.get("idempotency_key"),
        "reason": request.get("reason"),
        "root_cause_metrics": request.get("root_cause", {}).get("metrics", []),
        "plan": plan,
        "plan_hash": request.get("plan_hash"),
        "rollback_token": request.get("rollback_token"),
        "kubernetes_snapshot": request.get("kubernetes_snapshot") or before,
        "live_apply": request.get("live_apply", False),
    }


def _script_response_to_api(response: dict[str, Any], default_status: str) -> dict[str, Any]:
    allowed = bool(response.get("ok")) and not response.get("reasons")
    status = default_status if allowed else STATUS_BLOCKED
    if response.get("executed") and default_status == STATUS_ROLLED_BACK:
        status = STATUS_ROLLED_BACK
    api_response = {
        "ok": bool(response.get("ok", False)),
        "allowed": allowed,
        "executed": bool(response.get("executed", False)),
        "status": status,
        "execution_id": response.get("execution_id"),
        "action_id": response.get("action_id", ""),
        "target": response.get("target", ""),
        "message": response.get("message", ""),
        "reasons": response.get("reasons", []),
        "plan_hash": response.get("plan_hash") or (response.get("plan") or {}).get("plan_hash"),
        "expires_at": response.get("expires_at") or (response.get("plan") or {}).get("expires_at"),
        "before": response.get("before") or (response.get("plan") or {}).get("before"),
        "after": response.get("after") or (response.get("plan") or {}).get("after"),
        "verification": {
            "defined": bool((response.get("verification") or {}).get("defined", False)),
            "passed": (response.get("verification") or {}).get("passed"),
            "query_id": (response.get("verification") or {}).get("query_id"),
            "message": (response.get("verification") or {}).get("message"),
        },
        "rollback": {
            "defined": bool((response.get("rollback") or {}).get("defined", False)),
            "rollback_token": response.get("rollback_token"),
            "action_id": (response.get("rollback") or {}).get("action_id")
            or (response.get("rollback") or {}).get("action_type"),
        },
    }
    if response.get("rollback_id"):
        api_response["rollback_id"] = response["rollback_id"]
    _assert_json_serializable(api_response)
    return api_response


def _assert_json_serializable(response: dict[str, Any]) -> None:
    json.dumps(response, sort_keys=True)

def _load_capability_catalog(path: Path) -> list[dict[str, Any]]:
    if path.exists():
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(catalog, list):
            _assert_json_serializable({"actions": catalog})
            return catalog
    catalog = [_capability_from_allowlist(config) for config in ALLOWLIST.values()]
    _assert_json_serializable({"actions": catalog})
    return catalog

def _capability_from_allowlist(config: dict[str, Any]) -> dict[str, Any]:
    target = config["target"]
    namespace = config["namespace"]
    protected = target in PROTECTED_TARGETS or namespace in PROTECTED_NAMESPACES
    return {
        "action_id": config["action_id"],
        "action_type": config["action_type"],
        "target": target,
        "target_kind": config["target_kind"],
        "namespace": namespace,
        "executor_supported": not protected,
        "recommendation_only": False,
        "audit_only": False,
        "dry_run_supported": True,
        "execute_supported": not protected,
        "live_execute_supported": False,
        "rollback_supported": not protected,
        "rollback_action_id": config.get("rollback_action_id"),
        "verification_query_id": config.get("verification_query_id"),
        "policy_id": POLICY_ID,
        "policy_expires_at": POLICY_EXPIRES_AT,
        "policy_approval_required": True,
        "protected": protected,
        "blocked": protected,
        "blocked_reason": "target or namespace is protected" if protected else None,
        "min_replicas": config.get("min_replicas"),
        "max_replicas": config.get("max_replicas"),
        "target_replicas": config.get("target_replicas"),
        "blast_radius_services": config.get("blast_radius_services", []),
    }
