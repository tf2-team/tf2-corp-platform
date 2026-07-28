from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from runbooks.actions import page_oncall, plan_scale_deployment, restore_deployment_replicas, scale_deployment
from runbooks.actions.common import ALLOWLIST, POLICY_ID, block_response, stable_hash

from aiops.live_executor.kubernetes import DeploymentGateway
from aiops.live_executor.store import LiveExecutorStore, utc_now_text


STATUS_PLANNED = "planned"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_ROLLED_BACK = "rolled_back"


class LiveExecutorService:
    def __init__(
        self,
        store: LiveExecutorStore,
        *,
        deployment_gateway: DeploymentGateway | None = None,
        allow_live_apply: bool = False,
        cooldown_seconds: int = 900,
    ):
        self.store = store
        self.deployment_gateway = deployment_gateway
        self.allow_live_apply = allow_live_apply
        self.cooldown_seconds = cooldown_seconds
        self._lock = RLock()

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        deployment_gateway: DeploymentGateway | None = None,
        allow_live_apply: bool = False,
        cooldown_seconds: int = 900,
    ) -> "LiveExecutorService":
        return cls(
            LiveExecutorStore(path),
            deployment_gateway=deployment_gateway,
            allow_live_apply=allow_live_apply,
            cooldown_seconds=cooldown_seconds,
        )

    def catalog(self) -> list[dict[str, Any]]:
        return list(ALLOWLIST.values())

    def ready(self) -> bool:
        if not self.store.ready():
            return False
        if self.allow_live_apply:
            if self.deployment_gateway is None:
                return False
            action = ALLOWLIST["scale_product_catalog"]
            self.deployment_gateway.snapshot(action["namespace"], action["target"])
        return True

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._plan(request)

    def _plan(self, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "plan")
        if cached is not None:
            return cached

        plan_request = {**request, "dry_run": True}
        allowlisted = ALLOWLIST.get(str(request.get("action_id") or ""))
        if self.deployment_gateway is not None and allowlisted is not None:
            try:
                plan_request["kubernetes_snapshot"] = self.deployment_gateway.snapshot(
                    allowlisted["namespace"],
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
            self.store.save_plan(response)
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
        elif not self.allow_live_apply or self.deployment_gateway is None:
            response = self._blocked(request, "live apply is disabled", ["live_apply_disabled"])
        elif self.store.cooldown_active(plan_response["target"]):
            response = self._blocked(request, "target is in cooldown", ["target_cooldown"])
        else:
            running = self.store.execution_for_target(plan_response["target"])
            if running is not None:
                response = self._blocked(request, "target already has a running execution", ["single_flight_target"])
            else:
                try:
                    current = self.deployment_gateway.snapshot(plan_response["namespace"], plan_response["target"])
                    script_context = _request_to_script_context(
                        {**request, "kubernetes_snapshot": current},
                        plan_response,
                    )
                    response = _script_response_to_api(scale_deployment.run(script_context), STATUS_RUNNING)
                    response["incident_id"] = request.get("incident_id")
                    response["plan_hash"] = plan_hash
                    if response["executed"]:
                        after = self.deployment_gateway.scale(
                            plan_response["namespace"],
                            plan_response["target"],
                            int((plan_response.get("after") or {})["replicas"]),
                            str(current.get("resource_version") or ""),
                        )
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
        cached = self._idempotent(request, "verification")
        if cached is not None:
            return cached

        execution = self.store.get_execution_response(execution_id)
        passed = request.get("passed")
        if execution is None:
            response = self._blocked(request, "execution not found", ["execution_not_found"])
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
        else:
            response = dict(execution)
            response["status"] = STATUS_SUCCEEDED if passed else STATUS_FAILED
            response["message"] = request.get("message") or (
                "post-action verification passed" if passed else "post-action verification failed"
            )
            response["verification"] = {
                "defined": True,
                "passed": passed,
                "query_id": request.get("query_id"),
                "message": response["message"],
            }
            self.store.save_execution(response, response["status"])

        event_type = "verification_passed" if response.get("status") == STATUS_SUCCEEDED else "verification_failed"
        self._audit(request, response, event_type)
        self._save_idempotency(request, "verification", response)
        return response

    def rollback(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._rollback(execution_id, request)

    def _rollback(self, execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        cached = self._idempotent(request, "rollback")
        if cached is not None:
            return cached

        execution = self.store.get_execution_response(execution_id)
        if execution is None:
            response = self._blocked(request, "execution not found", ["execution_not_found"])
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
                self._save_idempotency(request, "rollback", response)
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
                "policy_id": request.get("policy_id", POLICY_ID),
                "policy_approved": request.get("policy_approved", True),
                "policy_expires_at": request.get("policy_expires_at", "2026-08-31T23:59:59Z"),
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
                    target_replicas = int((execution.get("before") or {})["replicas"])
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
                    rollback_verified = int(after.get("replicas") or -1) == target_replicas
                    response["verification"] = {
                        "defined": True,
                        "passed": rollback_verified,
                        "query_id": "deployment_spec_replicas",
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
        "idempotency_key": request.get("idempotency_key"),
        "reason": request.get("reason"),
        "requested_by": request.get("requested_by", "aiops-runtime"),
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
