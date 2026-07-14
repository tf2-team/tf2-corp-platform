from __future__ import annotations

from aiops.schemas import Observation


class StaticCollector:
    """Fixture-backed collector that is deliberately excluded from runtime packaging."""

    def __init__(self, observations: list[Observation]):
        self._observations = observations

    def collect(self) -> list[Observation]:
        return list(self._observations)
