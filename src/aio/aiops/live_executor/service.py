#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from runbooks.actions import plan_scale_deployment, restore_deployment_replicas, scale_deployment
from runbooks.actions.common import (
    ALLOWLIST,
    POLICY_EXPIRES_AT,
    POLICY_ID,
    PROTECTED_NAMESPACES,
    PROTECTED_TARGETS,
    block_response,
    parse_time,
    stable_hash,
    utc_now,
)

from aiops.live_executor.kubernetes import DeploymentGateway
from aiops.live_executor.store import LiveExecutorStore, utc_now_text


STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_ROLLED_BACK = "rolled_back"
DEFAULT_CAPABILITY_CATALOG_PATH = Path("config/executor_supported_actions.json")
DEFAULT_SERVICE_SUPPORT_CATALOG_PATH = Path("config/executor_service_support.json")


class LiveExecutorService:
    def __init__(
        self,
        store: LiveExecutorStore,
        *,
        deployment_gateway: DeploymentGateway | None = None,
        allow_live_apply: bool = False,
        cooldown_seconds: int = 900,
        action_budget_window_seconds: int = 3600,
        action_budget_max_executions: int = 10,
        policy_id: str = POLICY_ID,
        policy_expires_at: str = "2026-08-31T23:59:59Z",
        approval_id: str = "",
        environment: str = "techx-corp-prod",
        capability_catalog_path: Path | None = None,
        service_support_catalog_path: Path | None = None,
    ):
        self.store = store
        self.deployment_gateway = deployment_gateway
        self.allow_live_apply = allow_live_apply
        self.cooldown_seconds = cooldown_seconds
        self.action_budget_window_seconds = action_budget_window_seconds
        self.action_budget_max_executions = action_budget_max_executions
        self.policy_id = policy_id
        self.policy_expires_at = policy_expires_at
        self.approval_id = approval_id
        self.environment = environment
        self.capability_catalog_path = capability_catalog_path or DEFAULT_CAPABILITY_CATALOG_PATH
        self.service_support_catalog_path = service_support_catalog_path or DEFAULT_SERVICE_SUPPORT_CATALOG_PATH
        self._lock = RLock()

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        deployment_gateway: DeploymentGateway | None = None,
        allow_live_apply: bool = False,
        cooldown_seconds: int = 900,
        action_budget_window_seconds: int = 3600,
        action_budget_max_executions: int = 10,
        policy_id: str = POLICY_ID,
        policy_expires_at: str = "2026-08-31T23:59:59Z",
        approval_id: str = "",
        environment: str = "techx-corp-prod",
        capability_catalog_path: Path | None = None,
        service_support_catalog_path: Path | None = None,
    ) -> "LiveExecutorService":
        return cls(
            LiveExecutorStore(path),
            deployment_gateway=deployment_gateway,
            allow_live_apply=allow_live_apply,
            cooldown_seconds=cooldown_seconds,
            action_budget_window_seconds=action_budget_window_seconds,
            action_budget_max_executions=action_budget_max_executions,
            policy_id=policy_id,
            policy_expires_at=policy_expires_at,
            approval_id=approval_id,
            environment=environment,
            capability_catalog_path=capability_catalog_path,
            service_support_catalog_path=service_support_catalog_path,
        )

    def catalog(self) -> list[dict[str, Any]]:
        return [
            _action_with_runtime_state(action, self.allow_live_apply, self.environment)
            for action in _load_capability_catalog(self.capability_catalog_path)
        ]

    def service_catalog(self) -> list[dict[str, Any]]:
        return [
            _service_with_runtime_state(service, self.allow_live_apply, self.environment)
            for service in _load_service_support_catalog(self.service_support_catalog_path)
        ]

    def ready(self) -> bool:
        if not self.store.ready():
            return False
        try:
            if not self.catalog() or not self.service_catalog():
                return False
            if not self.policy_id or parse_time(self.policy_expires_at) <= utc_now():
                return False
        except (AttributeError, TypeError, ValueError):
            return False
        if self.allow_live_apply:
            if self.deployment_gateway is None or not self.approval_id:
                return False
            for action in ALLOWLIST.values():
                self.deployment_gateway.snapshot(self.environment, action["target"])
        return True

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._plan(request)

    def _plan(self, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "plan")
        if cached is not None:
            return cached

        plan_request = self._executor_policy_context({**request, "dry_run": True})
        allowlisted = ALLOWLIST.get(str(request.get("action_id") or ""))
        if self.deployment_gateway is not None and allowlisted is not None:
            try:
                plan_request["kubernetes_snapshot"] = self.deployment_gateway.snapshot(
                    self.environment,
                    allowlisted["target"],
                )
            except Exception as exc:
                response = self._blocked(
                    request,
                    "unable to snapshot target before planning",
                    [self._gateway_error_reason(exc)],
                )
                self._audit(request, response, "plan_blocked")
                self._save_idempotency(request, "plan", response)
                return response

        response = _script_response_to_api(plan_scale_deployment.run(plan_request), STATUS_PLANNED)
        response["incident_id"] = request.get("incident_id")
        self._audit(request, response, "plan_recorded")
        if response["allowed"]:
            self.store.save_plan(response, _plan_binding(request))
        self._save_idempotency(request, "plan", response)
        return response

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._execute(request)

    def _execute(self, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "execute")
        if cached is not None:
            return cached

        plan_hash = request.get("plan_hash")
        plan_response = self.store.get_plan_response(plan_hash) if isinstance(plan_hash, str) else None
        if plan_response is None:
            response = self._blocked(request, "missing or unknown plan", ["missing_plan"])
        elif binding_reasons := _binding_reasons(request, plan_response.get("_binding"), _PLAN_BINDING_FIELDS):
            response = self._blocked(request, "request does not match stored plan context", binding_reasons)
        elif not self.allow_live_apply or self.deployment_gateway is None:
            response = self._blocked(request, "live apply is disabled", ["live_apply_disabled"])
        elif self.store.cooldown_active(plan_response["target"]):
            response = self._blocked(request, "target is in cooldown", ["target_cooldown"])
        elif self.store.execution_count_since(self.action_budget_window_seconds) >= self.action_budget_max_executions:
            response = self._blocked(request, "executor action budget is exhausted", ["action_budget_exhausted"])
        else:
            running = self.store.execution_for_target(plan_response["target"])
            if running is not None:
                response = self._blocked(request, "target already has a running execution", ["single_flight_target"])
            else:
                try:
                    current = self.deployment_gateway.snapshot(plan_response["namespace"], plan_response["target"])
                    script_context = _request_to_script_context(
                        self._executor_policy_context({**request, "kubernetes_snapshot": current}),
                        plan_response,
                    )
                    response = _script_response_to_api(scale_deployment.run(script_context), STATUS_RUNNING)
                    response["incident_id"] = (plan_response.get("_binding") or {}).get("incident_id")
                    response["plan_hash"] = plan_hash
                    if response["executed"]:
                        requested_replicas = int(
                            (plan_response.get("after") or {}).get("control_replicas")
                            or (plan_response.get("after") or {})["replicas"]
                        )
                        after = self.deployment_gateway.scale(
                            plan_response["namespace"],
                            plan_response["target"],
                            requested_replicas,
                            str(current.get("resource_version") or ""),
                        )
                        after["requested_replicas"] = requested_replicas
                        response["before"] = current
                        response["after"] = after
                        response["message"] = (
                            f"scaled deployment/{plan_response['target']} "
                            f"from {current.get('replicas')} to {after.get('replicas')} replicas"
                        )
                        self.store.save_execution(response, STATUS_RUNNING)
                        self.store.set_cooldown(plan_response["target"], self.cooldown_seconds)
                except Exception as exc:
                    response = self._blocked(
                        request,
                        "deployment mutation failed",
                        [self._gateway_error_reason(exc)],
                    )
        self._audit(request, response, "execute_submitted" if response["executed"] else "execute_blocked")
        self._save_idempotency(request, "execute", response)
        return response

    def status(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            response = self.store.get_execution_response(execution_id)
            if response is None:
                return self._blocked({"action_id": "unknown"}, "execution not found", ["execution_not_found"])
            return response

    def record_verification(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._record_verification(execution_id, request)

    def _record_verification(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "verification", execution_id)
        if cached is not None:
            return cached

        execution = self.store.get_execution_response(execution_id)
        passed = request.get("passed")
        transient = False
        if execution is None:
            response = self._blocked(request, "execution not found", ["execution_not_found"])
        elif binding_reasons := _binding_reasons(request, execution, ("incident_id",)):
            response = self._blocked(request, "request does not match stored execution context", binding_reasons)
        elif request.get("query_id") != (execution.get("verification") or {}).get("query_id"):
            response = self._blocked(request, "verification query does not match execution plan", ["query_id_mismatch"])
        elif not isinstance(passed, bool):
            response = self._blocked(request, "verification result must be boolean", ["invalid_verification_result"])
        elif execution.get("status") in {STATUS_FAILED, STATUS_SUCCEEDED}:
            existing_passed = (execution.get("verification") or {}).get("passed")
            if existing_passed is passed:
                response = execution
            else:
                response = self._blocked(
                    request,
                    "verification result is already terminal",
                    ["verification_already_recorded"],
                )
        elif execution.get("status") != STATUS_RUNNING:
            response = self._blocked(request, "execution cannot be verified in its current state", ["invalid_execution_state"])
        elif passed and self.deployment_gateway is not None:
            try:
                current = self.deployment_gateway.snapshot(execution.get("namespace"), execution["target"])
            except Exception as exc:
                transient = True
                response = self._blocked(
                    request,
                    "unable to verify target readiness",
                    [self._gateway_error_reason(exc)],
                )
            else:
                expected_replicas = int(
                    (execution.get("after") or {}).get("requested_replicas")
                    or (execution.get("after") or {}).get("control_replicas")
                    or (execution.get("after") or {}).get("replicas")
                    or 0
                )
                original_control_replicas = int(
                    (execution.get("before") or {}).get("control_replicas")
                    or (execution.get("before") or {}).get("replicas")
                    or 0
                )
                hpa_managed = (
                    (execution.get("before") or {}).get("scaling_controller")
                    == "HorizontalPodAutoscaler"
                )
                reasons: list[str] = []
                current_control_replicas = int(current.get("control_replicas") or 0)
                controller_matches = current_control_replicas == expected_replicas
                controller_already_released = (
                    hpa_managed and current_control_replicas == original_control_replicas
                )
                if not controller_matches and not controller_already_released:
                    reasons.append("scaling_controller_drift")
                if int(current.get("ready_replicas") or 0) < expected_replicas:
                    reasons.append("target_not_ready")
                if reasons:
                    transient = True
                    response = self._blocked(request, "target is not ready for successful verification", reasons)
                else:
                    if hpa_managed and not controller_already_released:
                        try:
                            released = self.deployment_gateway.scale(
                                execution.get("namespace"),
                                execution["target"],
                                original_control_replicas,
                                str(current.get("resource_version") or ""),
                            )
                        except Exception as exc:
                            transient = True
                            response = self._blocked(
                                request,
                                "unable to release autoscaler override after verification",
                                [self._gateway_error_reason(exc)],
                            )
                        else:
                            if int(released.get("control_replicas") or -1) != original_control_replicas:
                                transient = True
                                response = self._blocked(
                                    request,
                                    "autoscaler override release was not observed",
                                    ["scaling_controller_drift"],
                                )
                            else:
                                released["requested_replicas"] = expected_replicas
                                released["control_released"] = True
                                response = self._complete_verification(execution, request, passed, released)
                    else:
                        current["requested_replicas"] = expected_replicas
                        current["control_released"] = controller_already_released
                        response = self._complete_verification(execution, request, passed, current)
        else:
            response = self._complete_verification(execution, request, passed)

        event_type = (
            "verification_pending"
            if transient
            else "verification_passed"
            if response.get("status") == STATUS_SUCCEEDED
            else "verification_failed"
        )
        self._audit(request, response, event_type)
        if transient:
            return response
        self._save_idempotency(request, "verification", response, execution_id)
        return response

    def rollback(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._rollback(execution_id, request)

    def _rollback(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "rollback", execution_id)
        if cached is not None:
            return cached

        execution = self.store.get_execution_response(execution_id)
        if execution is None:
            response = self._blocked(request, "execution not found", ["execution_not_found"])
        elif binding_reasons := _binding_reasons(request, execution, ("incident_id",)):
            response = self._blocked(request, "request does not match stored execution context", binding_reasons)
        elif not self.allow_live_apply or self.deployment_gateway is None:
            response = self._blocked(request, "live rollback is disabled", ["live_apply_disabled"])
        elif execution.get("status") not in {STATUS_RUNNING, STATUS_FAILED}:
            response = self._blocked(request, "execution cannot be rolled back in its current state", ["invalid_execution_state"])
        else:
            try:
                current = self.deployment_gateway.snapshot(execution.get("namespace"), execution["target"])
            except Exception as exc:
                response = self._blocked(
                    request,
                    "unable to snapshot target before rollback",
                    [self._gateway_error_reason(exc)],
                )
                self._audit(request, response, "rollback_blocked")
                self._save_idempotency(request, "rollback", response, execution_id)
                return response
            expected_controller = (execution.get("before") or {}).get(
                "scaling_controller",
                "Deployment",
            )
            if current.get("scaling_controller", "Deployment") != expected_controller:
                response = self._blocked(
                    request,
                    "scaling controller changed after execution",
                    ["scaling_controller_changed"],
                )
                self._audit(request, response, "rollback_blocked")
                self._save_idempotency(request, "rollback", response, execution_id)
                return response
            script_execution = {
                **execution,
                "rollback_token": execution.get("rollback_token") or (execution.get("rollback") or {}).get("rollback_token"),
            }
            script_context = {
                "schema_version": request.get("schema_version", "1.0"),
                "request_id": request.get("request_id"),
                "incident_id": request.get("incident_id") or execution.get("incident_id"),
                "action_id": "restore_deployment_replicas",
                "action_type": "restore_deployment_replicas",
                "target": execution["target"],
                "target_kind": "Deployment",
                "namespace": execution.get("namespace"),
                "dry_run": False,
                "policy_id": self.policy_id,
                "policy_approved": request.get("policy_approved", True),
                "policy_expires_at": self.policy_expires_at,
                "approval_id": self.approval_id,
                "_executor_policy_id": self.policy_id,
                "_executor_policy_expires_at": self.policy_expires_at,
                "_executor_approval_id": self.approval_id,
                "idempotency_key": request.get("idempotency_key"),
                "reason": request.get("reason", "rollback_requested"),
                "requested_by": request.get("requested_by", "aiops-runtime"),
                "root_cause_metrics": [],
                "rollback_token": request.get("rollback_token"),
                "execution": script_execution,
                "kubernetes_snapshot": current,
            }
            try:
                response = _script_response_to_api(restore_deployment_replicas.run(script_context), STATUS_ROLLED_BACK)
                response["incident_id"] = script_context["incident_id"]
                if response["executed"]:
                    target_replicas = int(
                        (execution.get("before") or {}).get("control_replicas")
                        or (execution.get("before") or {})["replicas"]
                    )
                    after = self.deployment_gateway.scale(
                        execution.get("namespace"),
                        execution["target"],
                        target_replicas,
                        str(current.get("resource_version") or ""),
                    )
                    response["before"] = current
                    response["after"] = after
                    response["message"] = (
                        f"restored deployment/{execution['target']} "
                        f"replicas from {current.get('replicas')} to {after.get('replicas')}"
                    )
                    rollback_verified = (
                        int(after.get("control_replicas") or -1) == target_replicas
                        and int(after.get("ready_replicas") or 0) >= target_replicas
                    )
                    response["verification"] = {
                        "defined": True,
                        "passed": rollback_verified,
                        "query_id": "scaling_controller_and_ready_replicas",
                        "message": (
                            "rollback replica snapshot restored"
                            if rollback_verified
                            else "rollback replica snapshot mismatch"
                        ),
                    }
                    if not rollback_verified:
                        response["status"] = STATUS_FAILED
                        response["executed"] = False
                    self.store.save_execution(response, response["status"])
            except Exception as exc:
                response = self._blocked(
                    request,
                    "deployment rollback failed",
                    [self._gateway_error_reason(exc)],
                )
        self._audit(request, response, "rollback_submitted" if response["executed"] else "rollback_blocked")
        self._save_idempotency(request, "rollback", response, execution_id)
        return response

    def _idempotent(
        self,
        request: dict[str, Any],
        operation: str,
        resource_id: str | None = None,
    ) -> dict[str, Any] | None:
        key = request.get("idempotency_key")
        if isinstance(key, str):
            stored = self.store.get_idempotency(key, operation)
            if stored is None:
                return None
            binding = stored.pop("_idempotency_binding", None)
            if not isinstance(binding, dict):
                return self._blocked(
                    request,
                    "stored idempotency result has no request binding",
                    ["idempotency_context_unbound"],
                )
            if binding != _idempotency_binding(request, resource_id):
                return self._blocked(
                    request,
                    "idempotency key was already used for another request context",
                    ["idempotency_context_mismatch"],
                )
            return stored
        return None

    def _save_idempotency(
        self,
        request: dict[str, Any],
        operation: str,
        response: dict[str, Any],
        resource_id: str | None = None,
    ) -> None:
        key = request.get("idempotency_key")
        if isinstance(key, str):
            self.store.save_idempotency(
                key,
                operation,
                {
                    **response,
                    "_idempotency_binding": _idempotency_binding(request, resource_id),
                },
            )

    def _blocked(self, request: dict[str, Any], message: str, reasons: list[str]) -> dict[str, Any]:
        response = block_response(request, message, reasons)
        return _script_response_to_api(response, STATUS_BLOCKED)

    def _executor_policy_context(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            **request,
            "_executor_policy_id": self.policy_id,
            "_executor_policy_expires_at": self.policy_expires_at,
            "_executor_approval_id": self.approval_id,
            "_executor_environment": self.environment,
        }

    def _complete_verification(
        self,
        execution: dict[str, Any],
        request: dict[str, Any],
        passed: bool,
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = dict(execution)
        response["status"] = STATUS_SUCCEEDED if passed else STATUS_FAILED
        response["message"] = request.get("message") or (
            "post-action verification passed" if passed else "post-action verification failed"
        )
        if current is not None:
            response["after"] = {**(response.get("after") or {}), **current}
        response["verification"] = {
            "defined": True,
            "passed": passed,
            "query_id": request.get("query_id"),
            "message": response["message"],
        }
        self.store.save_execution(response, response["status"])
        return response

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
            "execution_id": response.get("execution_id"),
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

    @staticmethod
    def _gateway_error_reason(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 409:
            return "resource_version_mismatch"
        return f"kubernetes_{type(exc).__name__.lower()}"

    def close(self) -> None:
        if self.deployment_gateway is not None:
            self.deployment_gateway.close()
        self.store.close()


def _request_to_script_context(request: dict[str, Any], plan_response: dict[str, Any]) -> dict[str, Any]:
    plan = {
        **(plan_response.get("plan") or {}),
        "plan_hash": plan_response.get("plan_hash"),
        "expires_at": plan_response.get("expires_at"),
        "before": plan_response.get("before"),
        "after": plan_response.get("after"),
        "rollback_token": plan_response.get("rollback", {}).get("rollback_token"),
        **(plan_response.get("_binding") or {}),
    }
    before = plan.get("before") or {}
    return {
        "schema_version": request.get("schema_version", "1.0"),
        "request_id": request.get("request_id"),
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
        "approval_id": request.get("approval_id"),
        "_executor_policy_id": request.get("_executor_policy_id"),
        "_executor_policy_expires_at": request.get("_executor_policy_expires_at"),
        "_executor_approval_id": request.get("_executor_approval_id"),
        "_executor_environment": request.get("_executor_environment"),
        "idempotency_key": request.get("idempotency_key"),
        "reason": request.get("reason"),
        "requested_by": request.get("requested_by", "aiops-runtime"),
        "root_cause_metrics": (request.get("root_cause") or {}).get("metrics", []),
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
        "executed_at": response.get("executed_at"),
        "action_id": response.get("action_id", ""),
        "action_type": response.get("action_type"),
        "target": response.get("target", ""),
        "target_kind": response.get("target_kind"),
        "namespace": response.get("namespace"),
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
    if response.get("incident_id"):
        api_response["incident_id"] = response["incident_id"]
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


def _load_service_support_catalog(path: Path) -> list[dict[str, Any]]:
    if path.exists():
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(catalog, list):
            _assert_json_serializable({"services": catalog})
            return catalog
    return []


def _resolve_namespace(namespace: Any, environment: str) -> Any:
    return environment if namespace == "techx-corp-prod" else namespace


def _action_with_runtime_state(action: dict[str, Any], allow_live_apply: bool, environment: str) -> dict[str, Any]:
    live_capable = bool(action.get("live_execute_supported"))
    live_apply_enabled = bool(
        allow_live_apply
        and live_capable
        and action.get("executor_supported")
        and not action.get("blocked")
    )
    return {
        **action,
        "namespace": _resolve_namespace(action.get("namespace"), environment),
        "live_execute_supported": live_capable and live_apply_enabled,
        "live_execute_capable": live_capable,
        "live_apply_enabled": live_apply_enabled,
    }


def _service_with_runtime_state(service: dict[str, Any], allow_live_apply: bool, environment: str) -> dict[str, Any]:
    live_capable = bool(service.get("live_execute_supported"))
    live_apply_enabled = bool(
        allow_live_apply
        and live_capable
        and service.get("executor_supported")
        and not service.get("protected")
    )
    return {
        **service,
        "namespace": _resolve_namespace(service.get("namespace"), environment),
        "live_execute_supported": live_capable and live_apply_enabled,
        "live_execute_capable": live_capable,
        "live_apply_enabled": live_apply_enabled,
    }

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
        "live_execute_supported": not protected,
        "rollback_supported": not protected,
        "rollback_action_id": config.get("rollback_action_id"),
        "verification_query_id": config.get("verification_query_id"),
        "verification_signal_id": config.get("verification_signal_id"),
        "verification_threshold": config.get("verification_threshold"),
        "verification_max_ratio": config.get("verification_max_ratio"),
        "policy_id": POLICY_ID,
        "policy_expires_at": POLICY_EXPIRES_AT,
        "policy_approval_required": True,
        "owner": config.get("owner"),
        "protected": protected,
        "blocked": protected,
        "blocked_reason": "target or namespace is protected" if protected else None,
        "min_replicas": config.get("min_replicas"),
        "max_replicas": config.get("max_replicas"),
        "target_replicas": config.get("target_replicas"),
        "blast_radius_services": config.get("blast_radius_services", []),
    }


_PLAN_BINDING_FIELDS = (
    "incident_id",
    "action_id",
    "action_type",
    "target",
    "target_kind",
    "namespace",
    "policy_id",
    "policy_approved",
    "policy_expires_at",
    "approval_id",
    "requested_by",
)


def _plan_binding(request: dict[str, Any]) -> dict[str, Any]:
    return {field: request.get(field) for field in _PLAN_BINDING_FIELDS}


def _binding_reasons(
    request: dict[str, Any],
    binding: dict[str, Any] | None,
    fields: tuple[str, ...],
) -> list[str]:
    if not isinstance(binding, dict):
        return ["stored_context_unbound"]
    return [
        f"{field}_mismatch"
        for field in fields
        if request.get(field) != binding.get(field)
    ]


_IDEMPOTENCY_BINDING_FIELDS = (
    "incident_id",
    "action_id",
    "action_type",
    "target",
    "target_kind",
    "namespace",
    "policy_id",
    "policy_approved",
    "policy_expires_at",
    "approval_id",
    "plan_hash",
    "rollback_token",
    "passed",
    "query_id",
    "reason",
    "requested_by",
    "dry_run",
)


def _idempotency_binding(
    request: dict[str, Any],
    resource_id: str | None,
) -> dict[str, Any]:
    return {
        "resource_id": resource_id,
        **{
            field: request.get(field)
            for field in _IDEMPOTENCY_BINDING_FIELDS
            if field in request
        },
    }
