from __future__ import annotations

from aiops.schemas import Incident, NotificationMessage


class NotificationBuilder:
    def build(self, incidents: list[Incident]) -> list[NotificationMessage]:
        return [self._build_one(incident) for incident in incidents]

    def _build_one(self, incident: Incident) -> NotificationMessage:
        last_event = incident.events[-1]
        dependency = incident.likely_dependency
        title = f"{incident.flow} incident"
        if dependency != "unknown":
            title = f"{incident.flow} likely dependency: {dependency}"
        details = [
            f"{last_event.reason} on {last_event.signal_id}",
            f"window={last_event.window}",
        ]
        if last_event.value is not None:
            details.append(f"value={last_event.value:g}{last_event.unit}")
        if last_event.threshold is not None:
            details.append(f"threshold={last_event.threshold:g}")
        if last_event.contributing_signals:
            details.append(f"signals={','.join(last_event.contributing_signals)}")
        if impact := last_event.labels.get("impact"):
            details.append(f"impact={impact}")
        return NotificationMessage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            state=incident.state,
            title=title,
            summary="; ".join(details),
            flow=incident.flow,
            service=incident.service,
            likely_dependency=dependency,
            runbook_id=last_event.runbook_id,
        )

