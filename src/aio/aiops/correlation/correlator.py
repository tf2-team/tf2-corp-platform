from __future__ import annotations

from aiops.schemas import CandidateEvent


class Correlator:
    def correlate(self, candidates: list[CandidateEvent]) -> list[CandidateEvent]:
        grouped: dict[tuple[str, str], list[CandidateEvent]] = {}
        for candidate in candidates:
            grouped.setdefault((candidate.flow, candidate.service), []).append(candidate)

        correlated: list[CandidateEvent] = []
        for group in grouped.values():
            dependency = next((item for item in group if item.likely_dependency != "unknown"), None)
            primary = dependency or group[0]
            contributing = tuple(dict.fromkeys(signal for item in group for signal in item.contributing_signals))
            confidence = max(item.confidence for item in group)
            correlated.append(
                primary.model_copy(
                    update={
                        "confidence": confidence,
                        "contributing_signals": contributing,
                        "runbook_id": dependency.runbook_id if dependency else primary.runbook_id,
                    }
                )
            )
        return correlated
