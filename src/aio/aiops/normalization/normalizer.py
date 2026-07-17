from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiops.schemas import Observation


def load_normalization_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class Normalizer:
    def __init__(self, schema: dict[str, Any] | None = None):
        self.schema = schema or {}

    def normalize(self, observations: list[Observation]) -> list[Observation]:
        return [self._normalize_one(observation) for observation in observations]

    def _normalize_one(self, observation: Observation) -> Observation:
        labels = self._normalize_labels(observation.labels)
        unit = observation.unit
        value = observation.value
        conversion = self.schema.get("unit_conversions", {}).get(unit)
        if conversion and value is not None:
            unit = conversion["to"]
            value = value * conversion["factor"]
        return observation.model_copy(
            update={
                "labels": dict(sorted(labels.items())),
                "unit": unit,
                "value": value,
                "window": self.schema.get("window_aliases", {}).get(observation.window, observation.window),
            }
        )

    def _normalize_labels(self, labels: dict[str, str]) -> dict[str, str]:
        aliases = self.schema.get("label_aliases", {})
        normalized = {}
        for key, value in labels.items():
            normalized[aliases.get(key, key)] = value
        return normalized
