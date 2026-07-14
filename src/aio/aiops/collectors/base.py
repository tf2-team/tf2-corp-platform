from __future__ import annotations

from abc import ABC, abstractmethod

from aiops.schemas import Observation


class Collector(ABC):
    @abstractmethod
    def collect(self) -> list[Observation]:
        raise NotImplementedError
