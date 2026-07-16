from __future__ import annotations

from aiops.detectors.base import Detector
from aiops.schemas import CandidateEvent, Feature
from aiops.shared.features import find_feature


class DependencyDetector(Detector):
    def __init__(
        self,
        detector_id: str,
        signal_id: str,
        threshold: float,
        flow: str,
        service: str,
        dependency: str,
        runbook_id: str,
        severity: str,
        confidence: float,
    ):
        self.detector_id = detector_id
        self.signal_id = signal_id
        self.threshold = threshold
        self.flow = flow
        self.service = service
        self.dependency = dependency
        self.runbook_id = runbook_id
        self.severity = severity
        self.confidence = confidence

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        feature = find_feature(features, self.signal_id)
        if (
            feature is None
            or feature.status != "ready"
            or feature.feature_role not in {"diagnostic", "dependency_signal"}
            or feature.value is None
            or feature.value <= self.threshold
        ):
            return []
        return [
            CandidateEvent(
                detector_id=self.detector_id,
                flow=self.flow,
                service=self.service,
                severity=self.severity,
                signal_id=feature.signal_id,
                value=feature.value,
                unit=feature.unit,
                window=feature.window,
                threshold=self.threshold,
                quality=feature.quality,
                reason="dependency_signal_breached",
                runbook_id=self.runbook_id,
                likely_dependency=self.dependency,
                confidence=self.confidence,
                contributing_signals=(feature.signal_id,),
            )
        ]
