from __future__ import annotations

from aiops.schemas import Observation


class Normalizer:
    def normalize(self, observations: list[Observation]) -> list[Observation]:
        return [observation.model_copy(update={"labels": dict(sorted(observation.labels.items()))}) for observation in observations]
