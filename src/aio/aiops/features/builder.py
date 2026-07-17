from __future__ import annotations

from aiops.schemas import Feature, Observation, RuntimeConfig, SignalQuality


class FeatureBuilder:
    def __init__(self, runtime_config: RuntimeConfig | None = None):
        self._roles = {signal.id: signal.feature_role for signal in runtime_config.signals} if runtime_config else {}

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
            feature_role=self._roles.get(observation.signal_id, "unknown"),
            labels=dict(observation.labels),
        )
