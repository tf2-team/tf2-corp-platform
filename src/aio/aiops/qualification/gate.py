from __future__ import annotations

from aiops.schemas import Observation, SignalQuality


class QualificationGate:
    def evaluate(self, observations: list[Observation]) -> list[Observation]:
        return [
            observation
            if observation.quality != SignalQuality.UNQUALIFIED
            else Observation(
                signal_id=observation.signal_id,
                value=None,
                unit=observation.unit,
                window=observation.window,
                quality=SignalQuality.FALLBACK_ONLY,
                labels=observation.labels,
            )
            for observation in observations
        ]

