#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from aiops.remediation.audit import RemediationAuditLog
from aiops.remediation.catalog import ActionCatalog
from aiops.schemas import (
    Feature,
    Incident,
    PolicyDecision,
    RemediationDecision,
    RemediationLifecycle,
    VerificationResult,
)
from aiops.verification import VerificationEngine


logger = logging.getLogger(__name__)


class ActionExecutor(Protocol):
    def submit_action(self, action: dict) -> dict: ...


class ActionCooldownStore(Protocol):
    def action_cooldown_active(self, target: str) -> bool: ...

    def set_action_cooldown(self, target: str, cooldown_seconds: int) -> None: ...


FreshFeatureProvider = Callable[[], list[Feature]]


class ClosedLoopController:
    def __init__(
        self,
        executor: ActionExecutor,
        catalog: ActionCatalog,
        audit: RemediationAuditLog,
        cooldown_store: ActionCooldownStore,
        fresh_features: FreshFeatureProvider,
        cooldown_seconds: int,
        blast_radius_limit: int,
        verification_attempts: int = 1,
        verification_interval_seconds: float = 0.0,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.executor = executor
        self.catalog = catalog
        self.audit = audit
        self.cooldown_store = cooldown_store
        self.fresh_features = fresh_features
        self.cooldown_seconds = cooldown_seconds
        self.blast_radius_limit = blast_radius_limit
        self.verification_attempts = max(1, verification_attempts)
        self.verification_interval_seconds = max(0.0, verification_interval_seconds)
        self.sleeper = sleeper
        self.verifier = VerificationEngine()

    def run(
        self,
        incidents: list[Incident],
        remediation_decisions: list[RemediationDecision],
        policy_decisions: list[PolicyDecision],
    ) -> tuple[list[RemediationLifecycle], list[VerificationResult]]:
        incident_by_id = {incident.incident_id: incident for incident in incidents}
        policy_by_id = {decision.incident_id: decision for decision in policy_decisions}
        actions = self.catalog.load()
        lifecycles: list[RemediationLifecycle] = []
        verifications: list[VerificationResult] = []
        for decision in remediation_decisions:
            incident = incident_by_id.get(decision.incident_id)
            action = actions.get(decision.selected_action)
            policy = policy_by_id.get(decision.incident_id)
            if incident is None:
                continue
            lifecycle = self._start_lifecycle(incident, decision)
            safety_reasons = self._safety_reasons(decision, action, policy)
            if safety_reasons:
                lifecycle.safety_status = "blocked"
                lifecycle.reasons.extend(safety_reasons)
                lifecycle.escalated = decision.fallback
                lifecycle.completed_at = _now()
                self.audit.append_lifecycle(lifecycle)
                lifecycles.append(lifecycle)
                continue

            lifecycle.safety_status = "passed"
            request = {
                "incident_id": incident.incident_id,
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target": action.target,
                "target_kind": action.target_kind,
                "replicas": action.replicas,
                "idempotency_key": f"{incident.incident_id}:{action.action_id}",
            }
            try:
                dry_run_response = self.executor.submit_action(
                    {
                        **request,
                        "operation": "dry-run",
                        "idempotency_key": f"{incident.incident_id}:{action.action_id}:dry-run",
                    }
                )
                if dry_run_response.get("status") != "validated":
                    lifecycle.safety_status = "blocked"
                    lifecycle.execution_status = "not-started"
                    lifecycle.escalated = True
                    lifecycle.reasons.append("executor_dry_run_failed")
                    lifecycle.completed_at = _now()
                    self.cooldown_store.set_action_cooldown(action.target, self.cooldown_seconds)
                    self.audit.append_lifecycle(lifecycle)
                    lifecycles.append(lifecycle)
                    continue
                response = self.executor.submit_action({**request, "operation": "execute"})
            except Exception as exc:
                lifecycle.execution_status = "failed"
                lifecycle.escalated = True
                lifecycle.reasons.append(f"executor_error:{type(exc).__name__}")
                lifecycle.completed_at = _now()
                self.cooldown_store.set_action_cooldown(action.target, self.cooldown_seconds)
                self.audit.append_lifecycle(lifecycle)
                lifecycles.append(lifecycle)
                logger.exception("AIOPS_REMEDIATION_EXECUTION_FAILED incident=%s", incident.incident_id)
                continue

            lifecycle.execution_status = str(response.get("status", "unknown"))
            if lifecycle.execution_status not in {"succeeded", "completed"}:
                lifecycle.escalated = True
                lifecycle.reasons.append("execution_not_successful")
                lifecycle.completed_at = _now()
                self.cooldown_store.set_action_cooldown(action.target, self.cooldown_seconds)
                self.audit.append_lifecycle(lifecycle)
                lifecycles.append(lifecycle)
                continue

            policy.executed = True
            verification = self._verify_after_action(incident)
            verifications.append(verification)
            lifecycle.verification_status = verification.status
            if verification.status == "recovered":
                lifecycle.rollback_status = "not-required"
            else:
                lifecycle.rollback_status = self._rollback(incident, action, response, lifecycle)
                lifecycle.escalated = lifecycle.rollback_status != "succeeded"
            lifecycle.completed_at = _now()
            self.cooldown_store.set_action_cooldown(action.target, self.cooldown_seconds)
            self.audit.append_lifecycle(lifecycle)
            lifecycles.append(lifecycle)
        return lifecycles, verifications

    def _verify_after_action(self, incident: Incident) -> VerificationResult:
        verification = VerificationResult(
            incident_id=incident.incident_id,
            status="inconclusive",
            reason="verification_not_run",
        )
        for attempt in range(self.verification_attempts):
            if attempt > 0 and self.verification_interval_seconds:
                self.sleeper(self.verification_interval_seconds)
            verification = self.verifier.verify([incident], self.fresh_features())[0]
            if verification.status == "recovered":
                break
        return verification

    def _safety_reasons(self, decision, action, policy) -> list[str]:
        reasons: list[str] = []
        if decision.fallback or action is None or action.action_type == "page":
            reasons.append("no_automatic_action")
        if policy is None or not policy.allowed:
            reasons.append("policy_not_allowed")
        if action is not None and policy is not None and (
            policy.target != action.target or policy.action_type != action.action_type
        ):
            reasons.append("action_not_policy_approved")
        if action is not None and len(action.blast_radius_services) >= self.blast_radius_limit:
            reasons.append("blast_radius_limit_exceeded")
        if action is not None and self.cooldown_store.action_cooldown_active(action.target):
            reasons.append("action_cooldown_active")
        return reasons

    def _rollback(self, incident, action, response, lifecycle) -> str:
        rollback_payload = response.get("rollback")
        if not isinstance(rollback_payload, dict):
            lifecycle.reasons.append("rollback_not_available")
            return "escalated"
        try:
            rollback_response = self.executor.submit_action(
                {
                    "operation": "rollback",
                    "incident_id": incident.incident_id,
                    "action_id": action.action_id,
                    "target": action.target,
                    "target_kind": action.target_kind,
                    "idempotency_key": f"{incident.incident_id}:{action.action_id}:rollback",
                    "rollback": rollback_payload,
                }
            )
        except Exception as exc:
            lifecycle.reasons.append(f"rollback_error:{type(exc).__name__}")
            return "failed"
        status = str(rollback_response.get("status", "unknown"))
        if status in {"succeeded", "completed", "rolled-back"}:
            return "succeeded"
        lifecycle.reasons.append("rollback_not_successful")
        return "failed"

    @staticmethod
    def _start_lifecycle(incident: Incident, decision: RemediationDecision) -> RemediationLifecycle:
        return RemediationLifecycle(
            incident_id=incident.incident_id,
            trigger_detector=incident.events[-1].detector_id,
            selected_action=decision.selected_action,
            target=decision.target,
            safety_status="pending",
            started_at=_now(),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
