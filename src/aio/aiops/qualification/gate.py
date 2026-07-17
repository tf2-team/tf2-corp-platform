from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from aiops.schemas import Observation, RuntimeConfig, SignalQuality


def load_qualification_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class QualificationGate:
    def __init__(
        self,
        runtime_config: RuntimeConfig | None = None,
        schema: dict[str, Any] | None = None,
        *,
        dev: bool = False,
        max_sample_age_seconds: int = 300,
    ):
        self.dev = dev
        self.max_sample_age_seconds = max_sample_age_seconds
        self._signals = {signal.id: signal for signal in runtime_config.signals} if runtime_config else {}
        self._schema = schema or {"timestamp_label": "sample_timestamp", "units": {}}

    def evaluate(self, observations: list[Observation]) -> list[Observation]:
        if self.dev or not self._signals:
            return observations
        return [self._evaluate_one(observation) for observation in observations]

    def _evaluate_one(self, observation: Observation) -> Observation:
        signal = self._signals.get(observation.signal_id)
        if signal is None:
            return observation.model_copy(update={"value": None, "quality": SignalQuality.UNQUALIFIED})
        if observation.quality in {SignalQuality.MISSING, SignalQuality.STALE, SignalQuality.INVALID}:
            return observation.model_copy(update={"value": None})
        if observation.value is None:
            return observation.model_copy(update={"quality": SignalQuality.MISSING})
        if (
            observation.unit not in self._schema.get("units", {})
            or observation.unit != signal.unit
            or observation.window != signal.window
            or not set(signal.required_labels).issubset(observation.labels)
            or any(observation.labels.get(label, getattr(signal, label)) != getattr(signal, label) for label in self._schema.get("registry_labels", []))
            or not self._valid_series_shape(observation)
            or not self._valid_value(observation.unit, observation.value)
        ):
            return observation.model_copy(update={"value": None, "quality": SignalQuality.INVALID})
        sample_timestamp = observation.labels.get(self._schema.get("timestamp_label", "sample_timestamp"))
        if sample_timestamp:
            try:
                age_seconds = time.time() - float(sample_timestamp)
            except ValueError:
                return observation.model_copy(update={"value": None, "quality": SignalQuality.INVALID})
            if age_seconds > self.max_sample_age_seconds:
                return observation.model_copy(update={"value": None, "quality": SignalQuality.STALE})
        if observation.quality == SignalQuality.FALLBACK_ONLY:
            return observation
        return observation.model_copy(update={"quality": SignalQuality.VERIFIED})

    def _valid_value(self, unit: str, value: float) -> bool:
        if not math.isfinite(value):
            return False
        rule = self._schema["units"][unit]
        if "allowed" in rule:
            return value in rule["allowed"]
        if "min" in rule and value < rule["min"]:
            return False
        if "max" in rule and value > rule["max"]:
            return False
        return True

    def _valid_series_shape(self, observation: Observation) -> bool:
        series_count = observation.labels.get(self._schema.get("series_count_label", "series_count"))
        if series_count is None:
            return True
        try:
            return int(series_count) <= int(self._schema.get("max_series_count", 1))
        except ValueError:
            return False
