from __future__ import annotations

from aiops.incidents.fingerprint import incident_fingerprint
from aiops.schemas import CandidateEvent, Incident


class IncidentManager:
    def __init__(self, environment: str):
        self.environment = environment
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
                severity=candidate.severity,
                flow=candidate.flow,
                service=candidate.service,
                likely_dependency=candidate.likely_dependency,
                events=[candidate],
            )
            self._incidents_by_fingerprint[fingerprint] = incident
            return incident

        incident.occurrence_count += 1
        incident.events.append(candidate)
        incident.severity = min(incident.severity, candidate.severity)
        return incident

    def fingerprint(self, candidate: CandidateEvent) -> str:
        return incident_fingerprint(self.environment, candidate)
