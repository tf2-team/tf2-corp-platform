from __future__ import annotations

import logging

from aiops.detectors.base import Detector
from aiops.schemas import CandidateEvent, Feature, SignalQuality
from aiops.shared.features import feature_timestamp


logger = logging.getLogger(__name__)


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
            logger.warning(
                "AIOPS_DETECT no_data_fire detector=%s signal=%s quality=%s service=%s severity=%s",
                self.detector_id,
                feature.signal_id,
                feature.quality.value,
                self.service,
                self.severity,
            )
            candidates.append(
                CandidateEvent(
                    detector_id=self.detector_id,
                    timestamp=feature_timestamp(feature),
                    flow=self.flow,
                    service=self.service,
                    severity=self.severity,
                    signal_id=feature.signal_id,
                    value=None,
                    unit=feature.unit,
                    window=feature.window,
                    threshold=None,
                    quality=feature.quality,
                    reason=f"signal_{feature.quality.value}",
                    runbook_id=self.runbook_id,
                    confidence=self.missing_confidence if feature.quality in {SignalQuality.MISSING, SignalQuality.STALE} else self.unknown_confidence,
                    contributing_signals=(feature.signal_id,),
                    labels=feature.labels,
                )
            )
        return candidates
