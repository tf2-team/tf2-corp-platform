from __future__ import annotations

from aiops.detectors.base import Detector
from aiops.schemas import CandidateEvent, Feature


class DetectorEngine:
    def __init__(self, detectors: list[Detector]):
        self._detectors = detectors

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        candidates: list[CandidateEvent] = []
        for detector in self._detectors:
            candidates.extend(detector.evaluate(features))
        return candidates
