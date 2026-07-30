#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4

from runbooks.actions.common import AUTHORIZED_REQUESTER

from aiops.schemas import (
    ActionCatalogItem,
    CandidateEvent,
    Feature,
    Incident,
    NotificationMessage,
    RootCauseCandidate,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class ExecutorClient(Protocol):
    def catalog(self, request_id: str | None = None) -> list[dict]: ...

    def plan(self, action: dict) -> dict: ...

    def execute(self, action: dict) -> dict: ...

    def record_verification(self, execution_id: str, verification: dict) -> dict: ...

    def rollback(self, execution_id: str, request: dict) -> dict: ...


class WorkflowStore(Protocol):
    def save_self_heal_workflow(self, workflow: dict) -> None: ...

    def active_self_heal_workflows(self) -> list[dict]: ...

    def queued_self_heal_workflows(self) -> list[dict]: ...

    def self_heal_workflow(self, incident_id: str) -> dict | None: ...

    def append_self_heal_audit(
        self,
        event_type: str,
        incident_id: str,
        execution_id: str | None,
        payload: dict,
    ) -> None: ...

    def mark_incident_recovered(self, incident_id: str, recovered_at: str | None = None) -> Incident | None: ...

    def enqueue_notification(self, message: NotificationMessage) -> None: ...


@dataclass(frozen=True)
class SelfHealConfig:
    namespace: str
    policy_id: str
    policy_expires_at: str
    approval_id: str
    protected_targets: frozenset[str]
    rollback_failure_runbook_id: str
    verification_deadline_seconds: int = 300
    min_fresh_samples: int = 2
    consecutive_passes: int = 2
    failure_samples: int = 2
    min_incident_occurrences: int = 3
    min_incident_score: float = 0.24
    rollback_after_executions: int = 3
    min_occurrence_interval_seconds: int = 60
    queue_ttl_seconds: int = 900
    verification_callback_max_attempts: int = 3
    rollback_max_attempts: int = 3

    def __post_init__(self) -> None:
        positive = (
            self.verification_deadline_seconds,
            self.min_fresh_samples,
            self.consecutive_passes,
            self.failure_samples,
            self.min_incident_occurrences,
            self.rollback_after_executions,
            self.min_occurrence_interval_seconds,
            self.queue_ttl_seconds,
            self.verification_callback_max_attempts,
            self.rollback_max_attempts,
        )
        if any(value < 1 for value in positive):
            raise ValueError("self-heal thresholds and timeouts must be positive")
        if not 0 <= self.min_incident_score <= 1:
            raise ValueError("self-heal incident score threshold must be between 0 and 1")


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

    def prioritize(self, incidents: list[Incident]) -> list[Incident]:
        queued = {
            workflow["incident_id"]: index
            for index, workflow in enumerate(self.store.queued_self_heal_workflows())
        }
        return sorted(incidents, key=lambda incident: queued.get(incident.incident_id, len(queued)))

    def sync_queue(self, active_incident_ids: set[str]) -> None:
        now = self.clock()
        for workflow in self.store.queued_self_heal_workflows():
            reason = None
            if workflow["incident_id"] not in active_incident_ids:
                reason = "queued_incident_no_longer_active"
            elif _queue_expired(workflow, now, self.config.queue_ttl_seconds):
                reason = "queued_incident_expired"
            if reason is None:
                continue
            workflow["status"] = "cancelled"
            workflow["cancel_reason"] = reason
            self.store.save_self_heal_workflow(workflow)
            self.store.append_self_heal_audit("queue_cancelled", workflow["incident_id"], workflow.get("execution_id"), {"reason": reason})

    def start(
        self,
        incident: Incident,
        action: ActionCatalogItem,
        root_cause: RootCauseCandidate | None,
        *,
        verification_features: list[Feature] | None = None,
    ) -> dict[str, Any]:
        existing = self.store.self_heal_workflow(incident.incident_id)
        if existing is not None and existing.get("status") == "queued" and _queue_expired(
            existing,
            self.clock(),
            self.config.queue_ttl_seconds,
        ):
            existing["status"] = "cancelled"
            self.store.save_self_heal_workflow(existing)
        if existing is not None and existing["status"] in {
            "verifying",
            "rollback_pending",
            "rolled_back",
            "rollback_failed",
        }:
            return {
                "status": existing["status"],
                "execution_id": existing.get("execution_id"),
                "executed": False,
                "reasons": ["workflow_already_exists"],
            }
        score = incident.events[-1].confidence
        trigger_timestamp = (
            float(existing["trigger_event_timestamp"])
            if existing is not None and existing.get("status") != "queued" and existing.get("trigger_event_timestamp") is not None
            else None
        )
        qualifying_events = _qualifying_occurrences(
            incident.events,
            self.config.min_incident_score,
            self.config.min_occurrence_interval_seconds,
            trigger_timestamp,
        )
        occurrences_since_trigger = len(qualifying_events)
        if score < self.config.min_incident_score:
            return self._waiting(
                incident,
                "incident_score_below_threshold",
                score=score,
                occurrences=occurrences_since_trigger,
            )
        if existing is None or existing.get("status") != "queued":
            recurrence_ready = occurrences_since_trigger >= self.config.min_incident_occurrences
        else:
            recurrence_ready = True
        if not recurrence_ready:
            return self._waiting(
                incident,
                "incident_occurrence_threshold_not_met",
                score=score,
                occurrences=occurrences_since_trigger,
            )
        active = self.store.active_self_heal_workflows()
        if any(workflow["incident_id"] != incident.incident_id for workflow in active):
            return self._queue(incident, action, existing)

        same_action = existing is not None and existing.get("action_id") == action.action_id
        execution_count = int(existing.get("execution_count", 0)) if same_action else 0
        if existing is not None and execution_count >= self.config.rollback_after_executions:
            self._rollback(existing, "repeated_self_heal_limit")
            logger.warning(
                "AIOPS_SELF_HEAL_ROLLBACK incident=%s action=%s executions=%s threshold=%s reason=repeated_self_heal_limit",
                incident.incident_id,
                action.action_id,
                execution_count,
                self.config.rollback_after_executions,
            )
            status = self.store.self_heal_workflow(incident.incident_id)["status"]
            return {
                "status": status,
                "execution_id": existing.get("execution_id"),
                "executed": status == "rolled_back",
                "reasons": ["repeated_self_heal_limit"],
            }
        attempt = int((existing or {}).get("attempt", 0)) + 1

        verification_event = next(
            (
                event
                for event in reversed(incident.events)
                if event.signal_id == action.verification_signal_id
            ),
            None,
        )
        verification_feature = next(
            (
                feature
                for feature in verification_features or []
                if feature.signal_id == action.verification_signal_id
                and feature.status == "ready"
                and feature.value is not None
            ),
            None,
        )
        if verification_features is not None and verification_feature is None:
            return self._save_blocked(
                incident.incident_id,
                action,
                "capability_blocked",
                {"reasons": ["verification_signal_unavailable"]},
                attempt,
            )
        if verification_features is None and verification_event is None:
            return self._save_blocked(
                incident.incident_id,
                action,
                "capability_blocked",
                {"reasons": ["verification_signal_unavailable"]},
                attempt,
            )
        verification_threshold = _verification_threshold(action, verification_feature, verification_event)
        if verification_threshold is None:
            return self._save_blocked(
                incident.incident_id,
                action,
                "capability_blocked",
                {"reasons": ["verification_threshold_unavailable"]},
                attempt,
            )

        capability_request_id = str(uuid4())
        try:
            capabilities = self.client.catalog(capability_request_id)
        except Exception as exc:
            return self._start_error(incident.incident_id, "capability_catalog_request_failed", exc)
        capability = next(
            (
                item
                for item in capabilities
                if item.get("action_id") == action.action_id
            ),
            None,
        )
        capability_reasons = _remote_capability_reasons(
            action,
            capability,
            self.config.namespace,
            self.config.policy_id,
        )
        if capability_reasons:
            self.store.append_self_heal_audit(
                "capability_blocked",
                incident.incident_id,
                None,
                {"request_id": capability_request_id, "reasons": capability_reasons},
            )
            return self._save_blocked(
                incident.incident_id,
                action,
                "capability_blocked",
                {"reasons": capability_reasons},
                attempt,
            )

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
            "requested_by": AUTHORIZED_REQUESTER,
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
            return self._save_blocked(incident.incident_id, action, "plan_blocked", plan, attempt)

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
            return self._save_blocked(incident.incident_id, action, "execute_blocked", execution, attempt)

        executed_at = _parse_time(execution.get("executed_at"), self.clock())
        workflow = {
            "incident_id": incident.incident_id,
            "execution_id": execution["execution_id"],
            "status": "verifying",
            "attempt": attempt,
            "execution_count": execution_count + 1,
            "trigger_event_timestamp": max((event.timestamp for event in qualifying_events), default=event.timestamp),
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "namespace": self.config.namespace,
            "signal_id": action.verification_signal_id,
            "triggering_signal_id": event.signal_id,
            "threshold": verification_threshold,
            "verification_baseline": (
                verification_feature.value
                if verification_feature is not None
                else verification_event.value if verification_event is not None else None
            ),
            "verification_direction": _verification_direction(action.verification_signal_id or ""),
            "verification_query_id": action.verification_query_id,
            "verification_signal_id": action.verification_signal_id,
            "severity": incident.severity,
            "flow": incident.flow,
            "service": incident.service,
            "runbook_id": event.runbook_id,
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

    def _waiting(self, incident: Incident, reason: str, *, score: float, occurrences: int) -> dict[str, Any]:
        logger.info(
            "AIOPS_SELF_HEAL_WAIT incident=%s service=%s score=%.3f min_score=%.3f occurrences=%s required=%s reason=%s",
            incident.incident_id,
            incident.service,
            score,
            self.config.min_incident_score,
            occurrences,
            self.config.min_incident_occurrences,
            reason,
        )
        return {"status": "waiting_recurrence", "execution_id": None, "executed": False, "reasons": [reason]}

    def _queue(
        self,
        incident: Incident,
        action: ActionCatalogItem,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        workflow = {
            **(existing or {}),
            "incident_id": incident.incident_id,
            "status": "queued",
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target": action.target,
            "service": incident.service,
            "queued_at": (existing or {}).get("queued_at") or _iso(self.clock()),
        }
        if existing is not None and existing.get("action_id") != action.action_id:
            workflow.update({"execution_id": None, "execution_count": 0, "rollback_token": None})
        if existing is None or existing.get("status") != "queued":
            self.store.append_self_heal_audit(
                "queued",
                incident.incident_id,
                workflow.get("execution_id"),
                {"reason": "another_self_heal_is_active", "action_id": action.action_id},
            )
        self.store.save_self_heal_workflow(workflow)
        logger.info(
            "AIOPS_SELF_HEAL_QUEUED incident=%s service=%s action=%s reason=another_self_heal_is_active",
            incident.incident_id,
            incident.service,
            action.action_id,
        )
        return {
            "status": "queued",
            "execution_id": workflow.get("execution_id"),
            "executed": False,
            "reasons": ["another_self_heal_is_active"],
        }

    def reconcile(self, features: list[Feature]) -> list[VerificationResult]:
        by_signal = {feature.signal_id: feature for feature in features}
        return [
            self._reconcile_one(
                workflow,
                by_signal.get(workflow.get("verification_signal_id") or workflow["signal_id"]),
            )
            for workflow in self.store.active_self_heal_workflows()
        ]

    def _reconcile_one(self, workflow: dict[str, Any], feature: Feature | None) -> VerificationResult:
        incident_id = workflow["incident_id"]
        if workflow["status"] == "rollback_pending":
            return self._rollback(workflow, workflow.get("rollback_reason", "verification_failed"))

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
            workflow["rollback_reason"] = reason
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
            "requested_by": AUTHORIZED_REQUESTER,
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
            return self._verification_callback_failure(workflow, "verification_callback_failed")

        if response.get("status") != "succeeded":
            self.store.append_self_heal_audit(
                "verification_rejected",
                workflow["incident_id"],
                workflow["execution_id"],
                response,
            )
            return self._verification_callback_failure(workflow, "executor_rejected_verification")
        self.store.append_self_heal_audit(
            "verification_passed",
            workflow["incident_id"],
            workflow["execution_id"],
            response,
        )
        workflow["status"] = "succeeded"
        self.store.save_self_heal_workflow(workflow)
        self.store.mark_incident_recovered(workflow["incident_id"], _iso(self.clock()))
        return VerificationResult(
            incident_id=workflow["incident_id"],
            status="recovered",
            reason="post_action_verification_passed",
        )

    def _verification_callback_failure(self, workflow: dict[str, Any], reason: str) -> VerificationResult:
        attempts = int(workflow.get("verification_callback_attempts", 0)) + 1
        workflow["verification_callback_attempts"] = attempts
        if attempts >= self.config.verification_callback_max_attempts:
            workflow["status"] = "rollback_pending"
            workflow["rollback_reason"] = reason
            self.store.save_self_heal_workflow(workflow)
            return self._rollback(workflow, reason)
        self.store.save_self_heal_workflow(workflow)
        return VerificationResult(incident_id=workflow["incident_id"], status="inconclusive", reason=reason)

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
            "requested_by": AUTHORIZED_REQUESTER,
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
        rollback_attempt = int(workflow.get("rollback_attempts", 0)) + 1
        workflow["rollback_attempts"] = rollback_attempt
        workflow["rollback_reason"] = reason
        request = {
            "request_id": str(uuid4()),
            "incident_id": workflow["incident_id"],
            "rollback_token": workflow.get("rollback_token"),
            "reason": reason,
            "requested_by": AUTHORIZED_REQUESTER,
            "idempotency_key": _idempotency_key(
                workflow["incident_id"],
                workflow["action_id"],
                f"rollback-{workflow.get('attempt', 1)}-{rollback_attempt}",
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
        elif rollback_attempt < self.config.rollback_max_attempts:
            workflow["status"] = "rollback_pending"
            workflow["rollback"] = response
            result_reason = "automatic_rollback_retry_pending"
        else:
            workflow["status"] = "rollback_failed"
            workflow["rollback"] = response
            escalation = _rollback_failure_notification(
                workflow,
                response,
                self.config.rollback_failure_runbook_id,
            )
            try:
                self.store.enqueue_notification(escalation)
            except Exception as exc:
                self.store.append_self_heal_audit(
                    "escalation_enqueue_failed",
                    workflow["incident_id"],
                    workflow["execution_id"],
                    {
                        "reason": "automatic_rollback_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                result_reason = "post_action_verification_failed_escalation_enqueue_failed"
            else:
                self.store.append_self_heal_audit(
                    "escalation_enqueued",
                    workflow["incident_id"],
                    workflow["execution_id"],
                    {
                        "reason": "automatic_rollback_failed",
                        "notification_id": escalation.incident_id,
                    },
                )
                result_reason = "post_action_verification_failed_escalated"
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
        attempt: int,
    ) -> dict[str, Any]:
        workflow = {
            "incident_id": incident_id,
            "execution_id": response.get("execution_id"),
            "status": status,
            "attempt": attempt,
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


def _qualifying_occurrences(
    events: list[CandidateEvent],
    min_score: float,
    min_interval_seconds: int,
    after_timestamp: float | None,
) -> list[CandidateEvent]:
    qualifying = sorted(
        (
            event
            for event in events
            if event.confidence >= min_score and (after_timestamp is None or event.timestamp > after_timestamp)
        ),
        key=lambda event: event.timestamp,
    )
    kept: list[CandidateEvent] = []
    for event in qualifying:
        if not kept or event.timestamp - kept[-1].timestamp >= min_interval_seconds:
            kept.append(event)
    return kept


def _queue_expired(workflow: dict[str, Any], now: datetime, ttl_seconds: int) -> bool:
    queued_at = _parse_time(workflow.get("queued_at"), datetime.min.replace(tzinfo=UTC))
    return now - queued_at >= timedelta(seconds=ttl_seconds)


def _remote_capability_reasons(
    action: ActionCatalogItem,
    capability: dict[str, Any] | None,
    namespace: str,
    policy_id: str,
) -> list[str]:
    if capability is None:
        return ["action_not_in_executor_catalog"]

    reasons: list[str] = []
    checks = (
        (capability.get("executor_supported") is True, "executor_not_supported"),
        (capability.get("dry_run_supported") is True, "dry_run_not_supported"),
        (capability.get("execute_supported") is True, "execute_not_supported"),
        (
            capability.get("live_execute_supported") is True
            or capability.get("live_execute_capable") is True,
            "live_execute_not_supported",
        ),
        (capability.get("live_apply_enabled") is True, "live_apply_disabled"),
        (capability.get("recommendation_only") is not True, "recommendation_only"),
        (capability.get("audit_only") is not True, "audit_only"),
        (capability.get("blocked") is not True, "blocked_action"),
        (capability.get("protected") is not True, "protected_action"),
        (capability.get("rollback_supported") is True, "rollback_not_supported"),
        (capability.get("policy_approval_required") is True, "policy_approval_not_required"),
    )
    reasons.extend(reason for allowed, reason in checks if not allowed)
    expected_values = {
        "action_type": action.action_type,
        "target": action.target,
        "target_kind": action.target_kind,
        "namespace": namespace,
        "verification_query_id": action.verification_query_id,
        "verification_signal_id": action.verification_signal_id,
        "verification_threshold": action.verification_threshold,
        "verification_max_ratio": action.verification_max_ratio,
        "rollback_action_id": action.rollback_action_id,
        "policy_id": policy_id,
    }
    reasons.extend(
        f"{field}_mismatch"
        for field, expected in expected_values.items()
        if capability.get(field) != expected
    )
    return reasons


def _verification_direction(signal_id: str) -> str:
    return "at_or_above" if "ready_pods" in signal_id or "available_replicas" in signal_id else "at_or_below"


def _verification_threshold(
    action: ActionCatalogItem,
    feature: Feature | None,
    event: CandidateEvent | None,
) -> float | None:
    if action.verification_threshold is not None:
        return float(action.verification_threshold)
    if action.verification_max_ratio is not None and feature is not None and feature.value is not None:
        return float(feature.value) * float(action.verification_max_ratio)
    if event is not None and event.threshold is not None:
        return float(event.threshold)
    return None


def _rollback_failure_notification(
    workflow: dict[str, Any],
    response: dict[str, Any],
    runbook_id: str,
) -> NotificationMessage:
    attempt = int(workflow.get("attempt", 1))
    notification_id = f"{workflow['incident_id']}:self-heal-escalation:{attempt}"
    return NotificationMessage(
        incident_id=notification_id,
        severity="SEV1",
        state="open",
        title=f"URGENT: AIOps rollback failed for {workflow.get('target', 'unknown target')}",
        summary=(
            "Automated remediation verification failed and the automatic rollback did not complete.\n"
            f"Action: {workflow.get('action_id', 'unknown')}\n"
            f"Execution: {workflow.get('execution_id', 'unknown')}\n"
            f"Target: {workflow.get('target', 'unknown')}\n"
            f"Rollback status: {response.get('status', 'unknown')}\n"
            "Action required: stop further mutation, inspect executor audit, and restore the previous replica state manually."
        ),
        flow=str(workflow.get("flow") or "operations"),
        service=str(workflow.get("service") or workflow.get("target") or AUTHORIZED_REQUESTER),
        likely_dependency="unknown",
        runbook_id=runbook_id,
    )


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
