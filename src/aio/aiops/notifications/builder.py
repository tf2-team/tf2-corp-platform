#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
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
        return NotificationMessage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            state=incident.state,
            title=title,
            summary=f"{last_event.reason} on {last_event.signal_id}",
            flow=incident.flow,
            service=incident.service,
            likely_dependency=dependency,
            runbook_id=last_event.runbook_id,
        )

