from __future__ import annotations

from aiops.detectors.base import Detector
from aiops.schemas import CandidateEvent, Feature, SignalQuality


class NoDataDetector(Detector):
    def __init__(
        self,
        required_signal_ids: list[str],
        detector_id: str,
        flow: str,
        service: str,
        severity: str,
        runbook_id: str,
        missing_confidence: float,
        unknown_confidence: float,
    ):
        self.required_signal_ids = set(required_signal_ids)
        self.detector_id = detector_id
        self.flow = flow
        self.service = service
        self.severity = severity
        self.runbook_id = runbook_id
        self.missing_confidence = missing_confidence
        self.unknown_confidence = unknown_confidence

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        candidates: list[CandidateEvent] = []
        for feature in features:
            if feature.signal_id not in self.required_signal_ids or feature.status != "unknown":
                continue
            candidates.append(
                CandidateEvent(
                    detector_id=self.detector_id,
                    flow=self.flow,
                    service=self.service,
                    severity=self.severity,
                    signal_id=feature.signal_id,
                    value=None,
                    threshold=None,
                    quality=feature.quality,
                    reason=f"signal_{feature.quality.value}",
                    runbook_id=self.runbook_id,
                    confidence=self.missing_confidence if feature.quality in {SignalQuality.MISSING, SignalQuality.STALE} else self.unknown_confidence,
                    contributing_signals=(feature.signal_id,),
                )
            )
        return candidates
