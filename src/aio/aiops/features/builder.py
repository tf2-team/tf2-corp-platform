from __future__ import annotations

from aiops.schemas import Feature, Observation, SignalQuality


class FeatureBuilder:
    def build(self, observations: list[Observation]) -> list[Feature]:
        return [self._build_one(observation) for observation in observations]

    def _build_one(self, observation: Observation) -> Feature:
        if observation.quality == SignalQuality.VERIFIED:
            status = "ready"
        elif observation.quality == SignalQuality.FALLBACK_ONLY:
            status = "fallback"
        else:
            status = "unknown"

        return Feature(
            signal_id=observation.signal_id,
            value=observation.value if status != "unknown" else None,
            unit=observation.unit,
            window=observation.window,
            quality=observation.quality,
            status=status,
            labels=dict(observation.labels),
        )
