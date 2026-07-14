from __future__ import annotations

from aiops.incidents import IncidentManager
from aiops.schemas import CandidateEvent, Incident


class InMemoryIncidentStore:
    def __init__(self, environment: str):
        self._manager = IncidentManager(environment)

    def upsert(self, candidate: CandidateEvent) -> Incident:
        return self._manager.upsert(candidate)
