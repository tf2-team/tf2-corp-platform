from __future__ import annotations

from abc import ABC, abstractmethod

from aiops.schemas import CandidateEvent, Feature


class Detector(ABC):
    @abstractmethod
    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        raise NotImplementedError

