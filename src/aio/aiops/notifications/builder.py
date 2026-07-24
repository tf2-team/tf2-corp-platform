#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import CandidateEvent, Incident, NotificationMessage


def is_slo_notification(event: CandidateEvent) -> bool:
    return event.reason == "threshold_breached" and (
        "slo" in event.detector_id.lower()
        or any(marker in event.signal_id for marker in ("latency", "error_rate", "error_ratio", "bad_ratio"))
    )


class NotificationBuilder:
    def build(self, incidents: list[Incident]) -> list[NotificationMessage]:
        return [self._build_one(incident) for incident in incidents]

    def _build_one(self, incident: Incident) -> NotificationMessage:
        last_event = incident.events[-1]
        dependency = incident.likely_dependency
        title = f"RCA root cause: {incident.service}" if last_event.detector_id == "rca_root_cause" else f"{incident.flow} incident"
        if last_event.detector_id != "rca_root_cause" and dependency != "unknown":
            title = f"{incident.flow} likely dependency: {dependency}"
        signals = tuple(dict.fromkeys(signal for event in incident.events for signal in (event.contributing_signals or (event.signal_id,))))
        return NotificationMessage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            state=incident.state,
            title=title,
            summary=f"{last_event.reason} on {', '.join(signals)}",
            flow=incident.flow,
            service=incident.service,
            likely_dependency=dependency,
            runbook_id=last_event.runbook_id,
        )
