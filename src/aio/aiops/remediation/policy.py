#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import ActionProposal, Incident, PolicyDecision


class PolicyEngine:
    def __init__(
        self,
        mode: str,
        protected_targets: set[str],
        stateful_kinds: set[str],
        non_actionable_flows: set[str],
        action_type: str,
        target_kind: str,
        default_replicas: int,
    ):
        if mode not in {"observe", "dry-run", "live-approved"}:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode
        self.protected_targets = protected_targets
        self.stateful_kinds = stateful_kinds
        self.non_actionable_flows = non_actionable_flows
        self.action_type = action_type
        self.target_kind = target_kind
        self.default_replicas = default_replicas

    def proposal_for(self, incident: Incident) -> ActionProposal | None:
        if incident.flow in self.non_actionable_flows:
            return None
        target = incident.likely_dependency if incident.likely_dependency != "unknown" else incident.service
        return ActionProposal(
            action_type=self.action_type,
            target=target,
            target_kind=self.target_kind,
            replicas=self.default_replicas,
            mutating=True,
            verification_defined=True,
            rollback_defined=True,
        )

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        reasons = self._rejection_reasons(proposal)
        if reasons:
            return PolicyDecision(allowed=False, result="blocked", reasons=tuple(reasons))

        if self.mode != "live-approved":
            return PolicyDecision(allowed=False, result="dry-run-recorded", reasons=("mode_not_live_approved",))

        return PolicyDecision(allowed=True, result="allowed", executed=False)

    def _rejection_reasons(self, proposal: ActionProposal) -> list[str]:
        reasons: list[str] = []
        if proposal.target.lower() in self.protected_targets:
            reasons.append("protected_target")
        if proposal.target_kind in self.stateful_kinds:
            reasons.append("stateful_target")
        if proposal.replicas <= 1:
            reasons.append("single_replica_target")
        if not proposal.verification_defined:
            reasons.append("missing_verification")
        if proposal.mutating and not proposal.rollback_defined:
            reasons.append("missing_rollback")
        if proposal.cost_changing and not proposal.cost_status_current:
            reasons.append("missing_cost_status")
        if self.mode == "live-approved" and proposal.mutating and not proposal.approved:
            reasons.append("missing_approval")
        return reasons
