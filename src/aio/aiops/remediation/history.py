from __future__ import annotations

import json
from pathlib import Path

from aiops.schemas import HistoryAction, Incident, IncidentFeatures, IncidentHistoryRecord, RemediationDecision


class IncidentHistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def load(self) -> list[IncidentHistoryRecord]:
        return [IncidentHistoryRecord.model_validate(item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def append_success(self, incident: Incident, features: IncidentFeatures, decisions: list[RemediationDecision]) -> None:
        actions = [
            HistoryAction(action_id=decision.selected_action, target=decision.target, outcome="success")
            for decision in decisions
            if not decision.fallback
        ]
        if not actions:
            return
        records = self.load()
        if any(record.incident_id == incident.incident_id for record in records):
            return
        records.append(
            IncidentHistoryRecord(
                incident_id=incident.incident_id,
                affected_services=features.affected_services,
                log_signatures=features.log_signatures,
                metric_ratios=features.metric_ratios,
                actions_taken=actions,
            )
        )
        self.path.write_text(json.dumps([record.model_dump(mode="json") for record in records], indent=2), encoding="utf-8")
