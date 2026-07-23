#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiops.incidents.fingerprint import incident_fingerprint
from aiops.schemas import CandidateEvent, Incident

logger = logging.getLogger(__name__)


class IncidentManager:
    def __init__(self, environment: str, topology_graph=None):
        self.environment = environment
        self.topology_graph = topology_graph
        self._incidents_by_fingerprint: dict[str, Incident] = {}

    def upsert(self, candidate: CandidateEvent) -> Incident:
        fingerprint = self.fingerprint(candidate)
        incident = self._incidents_by_fingerprint.get(fingerprint)
        if incident is None:
            digest = fingerprint.removeprefix("sha256:")
            incident = Incident(
                incident_id=f"inc-{digest[:12]}",
                fingerprint=fingerprint,
                state="open",
                last_seen=_seen_at(candidate),
                severity=candidate.severity,
                flow=candidate.flow,
                service=candidate.service,
                likely_dependency=candidate.likely_dependency,
                events=[candidate],
            )
            self._incidents_by_fingerprint[fingerprint] = incident
            logger.info(
                "AIOPS_INCIDENT_UPSERT action=created incident=%s fingerprint=%s service=%s detector=%s occurrence=%s",
                incident.incident_id,
                fingerprint,
                incident.service,
                candidate.detector_id,
                incident.occurrence_count,
            )
            return incident

        incident.occurrence_count += 1
        incident.events.append(candidate)
        incident.last_seen = _seen_at(candidate)
        incident.severity = min(incident.severity, candidate.severity)
        logger.info(
            "AIOPS_INCIDENT_UPSERT action=deduped incident=%s fingerprint=%s service=%s detector=%s occurrence=%s",
            incident.incident_id,
            fingerprint,
            incident.service,
            candidate.detector_id,
            incident.occurrence_count,
        )
        return incident

    def fingerprint(self, candidate: CandidateEvent) -> str:
        return incident_fingerprint(self.environment, candidate, self.topology_graph)


def _seen_at(candidate: CandidateEvent) -> str:
    if candidate.timestamp:
        return datetime.fromtimestamp(candidate.timestamp, UTC).isoformat()
    return datetime.now(UTC).isoformat()
