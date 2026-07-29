#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4

from aiops.schemas import (
    ActionCatalogItem,
    Feature,
    Incident,
    RootCauseCandidate,
    VerificationResult,
)


class ExecutorClient(Protocol):
    def plan(self, action: dict) -> dict: ...

    def execute(self, action: dict) -> dict: ...

    def record_verification(self, execution_id: str, verification: dict) -> dict: ...

    def rollback(self, execution_id: str, request: dict) -> dict: ...


class WorkflowStore(Protocol):
    def save_self_heal_workflow(self, workflow: dict) -> None: ...

    def active_self_heal_workflows(self) -> list[dict]: ...

    def self_heal_workflow(self, incident_id: str) -> dict | None: ...

    def append_self_heal_audit(
        self,
        event_type: str,
        incident_id: str,
        execution_id: str | None,
        payload: dict,
    ) -> None: ...

    def mark_incident_recovered(self, incident_id: str, recovered_at: str | None = None) -> Incident | None: ...


@dataclass(frozen=True)
class SelfHealConfig:
    namespace: str
    policy_id: str
    policy_expires_at: str
    approval_id: str
    protected_targets: frozenset[str]
    verification_deadline_seconds: int = 300
    min_fresh_samples: int = 2
    consecutive_passes: int = 2
    failure_samples: int = 2


class SelfHealOrchestrator:
    """Persistent, fail-closed orchestration for one allowlisted live action."""

    def __init__(
        self,
        client: ExecutorClient,
        store: WorkflowStore,
        config: SelfHealConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.store = store
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))

    def start(
        self,
        incident: Incident,
        action: ActionCatalogItem,
        root_cause: RootCauseCandidate | None,
    ) -> dict[str, Any]:
        existing = self.store.self_heal_workflow(incident.incident_id)
        if existing is not None and existing["status"] != "succeeded":
            return {
                "status": existing["status"],
                "execution_id": existing.get("execution_id"),
                "executed": False,
                "reasons": ["workflow_already_exists"],
            }
        attempt = int((existing or {}).get("attempt", 0)) + 1

        event = incident.events[-1]
        request = {
            "request_id": str(uuid4()),
            "incident_id": incident.incident_id,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "target_kind": action.target_kind,
            "namespace": self.config.namespace,
            "replicas": action.replicas,
            "policy_id": self.config.policy_id,
            "policy_approved": True,
            "policy_expires_at": self.config.policy_expires_at,
            "approval_id": self.config.approval_id or None,
            "plan_hash": None,
            "rollback_token": None,
            "idempotency_key": _idempotency_key(incident.incident_id, action.action_id, f"plan-{attempt}"),
            "reason": event.reason,
            "requested_by": "aiops-runtime",
            "dry_run": True,
            "root_cause": {
                "service": root_cause.service if root_cause else incident.service,
                "score": root_cause.score if root_cause else incident.events[-1].confidence,
                "metrics": root_cause.root_cause_metrics if root_cause else [event.signal_id],
                "evidence_scores": root_cause.evidence_scores if root_cause else {},
            },
            "safety": {
                "protected_targets": sorted(self.config.protected_targets),
                "blast_radius_services": action.blast_radius_services,
                "cost_status_current": True,
            },
        }

        try:
            plan = self.client.plan(request)
        except Exception as exc:
            return self._start_error(incident.incident_id, "plan_request_failed", exc)
        self.store.append_self_heal_audit("plan", incident.incident_id, None, plan)
        if not plan.get("allowed") or plan.get("status") != "planned":
            return self._save_blocked(incident.incident_id, action, "plan_blocked", plan)

        execute_request = {
            **request,
            "request_id": str(uuid4()),
            "dry_run": False,
            "plan_hash": plan.get("plan_hash"),
            "rollback_token": (plan.get("rollback") or {}).get("rollback_token"),
            "idempotency_key": _idempotency_key(incident.incident_id, action.action_id, f"execute-{attempt}"),
        }
        try:
            execution = self.client.execute(execute_request)
        except Exception as exc:
            return self._start_error(incident.incident_id, "execute_request_failed", exc)
        self.store.append_self_heal_audit(
            "execute",
            incident.incident_id,
            execution.get("execution_id"),
            execution,
        )
        if not execution.get("allowed") or not execution.get("executed"):
            return self._save_blocked(incident.incident_id, action, "execute_blocked", execution)

        executed_at = _parse_time(execution.get("executed_at"), self.clock())
        workflow = {
            "incident_id": incident.incident_id,
            "execution_id": execution["execution_id"],
            "status": "verifying",
            "attempt": attempt,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "namespace": self.config.namespace,
            "signal_id": event.signal_id,
            "threshold": event.threshold,
            "verification_direction": _verification_direction(event.signal_id),
            "verification_query_id": event.signal_id,
            "executed_at": _iso(executed_at),
            "deadline_at": _iso(executed_at + timedelta(seconds=self.config.verification_deadline_seconds)),
            "last_sample_timestamp": None,
            "fresh_samples": 0,
            "consecutive_passes": 0,
            "consecutive_failures": 0,
            "rollback_token": (execution.get("rollback") or {}).get("rollback_token"),
            "plan_hash": execution.get("plan_hash"),
            "before": execution.get("before"),
            "after": execution.get("after"),
        }
        self.store.save_self_heal_workflow(workflow)
        return {
            "status": "verifying",
            "execution_id": execution["execution_id"],
            "executed": True,
            "reasons": [],
        }

    def reconcile(self, features: list[Feature]) -> list[VerificationResult]:
        by_signal = {feature.signal_id: feature for feature in features}
        return [
            self._reconcile_one(workflow, by_signal.get(workflow["signal_id"]))
            for workflow in self.store.active_self_heal_workflows()
        ]

    def _reconcile_one(self, workflow: dict[str, Any], feature: Feature | None) -> VerificationResult:
        incident_id = workflow["incident_id"]
        if workflow["status"] == "rollback_pending":
            return self._rollback(workflow, "verification_failed")

        now = self.clock()
        deadline = _parse_time(workflow.get("deadline_at"), now)
        sample_time = _feature_timestamp(feature)
        executed_at = _parse_time(workflow.get("executed_at"), now)
        last_sample = _parse_time(workflow.get("last_sample_timestamp"), datetime.min.replace(tzinfo=UTC))
        fresh = (
            feature is not None
            and feature.status == "ready"
            and feature.value is not None
            and sample_time is not None
            and sample_time > executed_at
            and sample_time > last_sample
        )

        if fresh:
            passed = _sample_passed(
                float(feature.value),
                workflow.get("threshold"),
                workflow["verification_direction"],
            )
            workflow["last_sample_timestamp"] = _iso(sample_time)
            workflow["fresh_samples"] = int(workflow.get("fresh_samples", 0)) + 1
            if passed:
                workflow["consecutive_passes"] = int(workflow.get("consecutive_passes", 0)) + 1
                workflow["consecutive_failures"] = 0
            else:
                workflow["consecutive_failures"] = int(workflow.get("consecutive_failures", 0)) + 1
                workflow["consecutive_passes"] = 0
            self.store.append_self_heal_audit(
                "verification_sample",
                incident_id,
                workflow.get("execution_id"),
                {
                    "signal_id": workflow["signal_id"],
                    "sample_timestamp": workflow["last_sample_timestamp"],
                    "value": feature.value,
                    "threshold": workflow.get("threshold"),
                    "passed": passed,
                },
            )

        enough_passes = (
            int(workflow.get("fresh_samples", 0)) >= self.config.min_fresh_samples
            and int(workflow.get("consecutive_passes", 0)) >= self.config.consecutive_passes
        )
        if enough_passes:
            return self._complete_verification(workflow)

        failed = int(workflow.get("consecutive_failures", 0)) >= self.config.failure_samples
        timed_out = now >= deadline
        if failed or timed_out:
            reason = "verification_failed" if failed else "verification_inconclusive_timeout"
            self._record_failed_verification(workflow, reason)
            workflow["status"] = "rollback_pending"
            self.store.save_self_heal_workflow(workflow)
            return self._rollback(workflow, reason)

        self.store.save_self_heal_workflow(workflow)
        return VerificationResult(
            incident_id=incident_id,
            status="inconclusive" if not fresh else "not_recovered",
            reason="awaiting_fresh_post_action_telemetry" if not fresh else "verification_samples_pending",
        )

    def _complete_verification(self, workflow: dict[str, Any]) -> VerificationResult:
        request = {
            "request_id": str(uuid4()),
            "incident_id": workflow["incident_id"],
            "idempotency_key": _idempotency_key(
                workflow["incident_id"],
                workflow["action_id"],
                f"verify-pass-{workflow.get('attempt', 1)}",
            ),
            "passed": True,
            "query_id": workflow["verification_query_id"],
            "message": "fresh telemetry met the post-action recovery rule",
            "requested_by": "aiops-runtime",
        }
        try:
            response = self.client.record_verification(workflow["execution_id"], request)
        except Exception as exc:
            self.store.append_self_heal_audit(
                "verification_callback_error",
                workflow["incident_id"],
                workflow["execution_id"],
                {"error_type": type(exc).__name__},
            )
            self.store.save_self_heal_workflow(workflow)
            return VerificationResult(
                incident_id=workflow["incident_id"],
                status="inconclusive",
                reason="verification_callback_failed",
            )

        self.store.append_self_heal_audit(
            "verification_passed",
            workflow["incident_id"],
            workflow["execution_id"],
            response,
        )
        if response.get("status") != "succeeded":
            self.store.save_self_heal_workflow(workflow)
            return VerificationResult(
                incident_id=workflow["incident_id"],
                status="inconclusive",
                reason="executor_rejected_verification",
            )
        workflow["status"] = "succeeded"
        self.store.save_self_heal_workflow(workflow)
        self.store.mark_incident_recovered(workflow["incident_id"], _iso(self.clock()))
        return VerificationResult(
            incident_id=workflow["incident_id"],
            status="recovered",
            reason="post_action_verification_passed",
        )

    def _record_failed_verification(self, workflow: dict[str, Any], reason: str) -> None:
        request = {
            "request_id": str(uuid4()),
            "incident_id": workflow["incident_id"],
            "idempotency_key": _idempotency_key(
                workflow["incident_id"],
                workflow["action_id"],
                f"verify-fail-{workflow.get('attempt', 1)}",
            ),
            "passed": False,
            "query_id": workflow["verification_query_id"],
            "message": reason,
            "requested_by": "aiops-runtime",
        }
        try:
            response = self.client.record_verification(workflow["execution_id"], request)
        except Exception as exc:
            response = {"status": "callback_failed", "error_type": type(exc).__name__}
        self.store.append_self_heal_audit(
            "verification_failed",
            workflow["incident_id"],
            workflow["execution_id"],
            response,
        )

    def _rollback(self, workflow: dict[str, Any], reason: str) -> VerificationResult:
        request = {
            "request_id": str(uuid4()),
            "incident_id": workflow["incident_id"],
            "rollback_token": workflow.get("rollback_token"),
            "reason": reason,
            "requested_by": "aiops-runtime",
            "policy_id": self.config.policy_id,
            "policy_approved": True,
            "policy_expires_at": self.config.policy_expires_at,
            "idempotency_key": _idempotency_key(
                workflow["incident_id"],
                workflow["action_id"],
                f"rollback-{workflow.get('attempt', 1)}",
            ),
        }
        try:
            response = self.client.rollback(workflow["execution_id"], request)
        except Exception as exc:
            response = {"status": "rollback_failed", "error_type": type(exc).__name__}

        self.store.append_self_heal_audit(
            "rollback",
            workflow["incident_id"],
            workflow["execution_id"],
            response,
        )
        if response.get("status") == "rolled_back" and response.get("executed"):
            workflow["status"] = "rolled_back"
            workflow["rollback"] = response
            result_reason = "post_action_verification_failed_rolled_back"
        else:
            workflow["status"] = "rollback_failed"
            workflow["rollback"] = response
            self.store.append_self_heal_audit(
                "escalation_required",
                workflow["incident_id"],
                workflow["execution_id"],
                {"reason": "automatic_rollback_failed"},
            )
            result_reason = "post_action_verification_failed_rollback_failed"
        self.store.save_self_heal_workflow(workflow)
        return VerificationResult(
            incident_id=workflow["incident_id"],
            status="not_recovered",
            reason=result_reason,
        )

    def _save_blocked(
        self,
        incident_id: str,
        action: ActionCatalogItem,
        status: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        workflow = {
            "incident_id": incident_id,
            "execution_id": response.get("execution_id"),
            "status": status,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "reasons": response.get("reasons", []),
        }
        self.store.save_self_heal_workflow(workflow)
        return {
            "status": status,
            "execution_id": response.get("execution_id"),
            "executed": False,
            "reasons": response.get("reasons", []),
        }

    def _start_error(self, incident_id: str, event_type: str, exc: Exception) -> dict[str, Any]:
        payload = {"error_type": type(exc).__name__}
        self.store.append_self_heal_audit(event_type, incident_id, None, payload)
        return {
            "status": event_type,
            "execution_id": None,
            "executed": False,
            "reasons": [event_type],
        }


def _idempotency_key(incident_id: str, action_id: str, operation: str) -> str:
    digest = hashlib.sha256(f"{incident_id}:{action_id}:{operation}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _verification_direction(signal_id: str) -> str:
    return "at_or_above" if "ready_pods" in signal_id or "available_replicas" in signal_id else "at_or_below"


def _sample_passed(value: float, threshold: float | None, direction: str) -> bool:
    if threshold is None:
        return False
    if direction == "at_or_above":
        return value >= float(threshold)
    return value <= float(threshold)


def _feature_timestamp(feature: Feature | None) -> datetime | None:
    if feature is None:
        return None
    raw = feature.labels.get("sample_timestamp")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), UTC)
    except (TypeError, ValueError, OSError):
        try:
            return _parse_time(raw)
        except ValueError:
            return None


def _parse_time(value: str | None, default: datetime | None = None) -> datetime:
    if not value:
        if default is None:
            raise ValueError("timestamp is required")
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
