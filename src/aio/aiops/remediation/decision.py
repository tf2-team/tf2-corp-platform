from __future__ import annotations

from collections import defaultdict

from aiops.schemas import ActionCatalogItem, IncidentFeatures, IncidentHistoryRecord, RemediationDecision


class RemediationDecisionEngine:
    def __init__(
        self,
        ood_threshold: float,
        cost_page: float,
        blast_radius_limit: int,
        confidence_threshold: float,
    ):
        self.ood_threshold = ood_threshold
        self.cost_page = cost_page
        self.blast_radius_limit = blast_radius_limit
        self.confidence_threshold = confidence_threshold

    def decide(
        self,
        incident_id: str,
        features: IncidentFeatures,
        matches: list[tuple[IncidentHistoryRecord, float]],
        catalog: dict[str, ActionCatalogItem],
    ) -> RemediationDecision:
        max_similarity = matches[0][1] if matches else 0.0
        if max_similarity < self.ood_threshold:
            return self._page(incident_id, ["ood_or_no_history"])

        votes: dict[str, float] = defaultdict(float)
        matched_ids: list[str] = []
        for record, similarity in matches:
            matched_ids.append(record.incident_id)
            for action in record.actions_taken:
                votes[action.action_id] += similarity * self._outcome_weight(action.outcome)

        if not votes:
            return self._page(incident_id, ["no_action_votes"])

        total = sum(votes.values()) or 1.0
        action_id, vote = max(votes.items(), key=lambda item: item[1])
        action = catalog.get(action_id)
        if action is None:
            return self._page(incident_id, ["action_not_in_catalog"])

        confidence = (vote / total) * max_similarity
        reasons = self._guardrail_reasons(action, features, confidence)
        expected_cost = action.cost_min + 2 * action.downtime_min + (1.0 - confidence) * self.cost_page
        if expected_cost >= self.cost_page:
            reasons.append("page_cheaper_than_action")

        if reasons:
            return self._page(incident_id, reasons, matched_ids)

        return RemediationDecision(
            incident_id=incident_id,
            selected_action=action.action_id,
            target=action.target,
            confidence=confidence,
            expected_cost=expected_cost,
            decision="dry-run-recorded",
            fallback=False,
            matched_history=matched_ids,
        )

    def _guardrail_reasons(self, action: ActionCatalogItem, features: IncidentFeatures, confidence: float) -> list[str]:
        reasons: list[str] = []
        if action.action_type == "increase_pool_size" and {"deadlock", "lock"} & features.log_signatures:
            reasons.append("deadlock_pool_size_forbidden")
        if action.action_type in {"restart", "rollback", "increase_pool_size"} and action.target not in features.affected_services:
            reasons.append("target_not_affected")
        if len(action.blast_radius_services) >= self.blast_radius_limit and confidence < self.confidence_threshold:
            reasons.append("blast_radius_too_large_for_confidence")
        return reasons

    def _page(self, incident_id: str, reasons: list[str], matched_ids: list[str] | None = None) -> RemediationDecision:
        return RemediationDecision(
            incident_id=incident_id,
            selected_action="page_oncall",
            target="platform-team",
            confidence=0.0,
            expected_cost=self.cost_page,
            decision="fallback-page-oncall",
            fallback=True,
            reasons=reasons,
            matched_history=matched_ids or [],
        )

    def _outcome_weight(self, outcome: str) -> float:
        return {"success": 1.0, "partial": 0.5, "failed": 0.0}.get(outcome, 0.0)
