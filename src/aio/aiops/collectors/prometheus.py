from __future__ import annotations

import time
from typing import Protocol

from aiops.collectors.base import Collector
from aiops.schemas import Observation, RuntimeConfig, SignalQuality


class PrometheusClientLike(Protocol):
    def query(self, query: str) -> dict: ...


class PrometheusCollector(Collector):
    def __init__(self, client: PrometheusClientLike, runtime_config: RuntimeConfig):
        self.client = client
        self.config = runtime_config
        self._dependencies = {
            detector.signal_id: detector.dependency
            for detector in runtime_config.detectors
            if detector.type == "dependency" and detector.signal_id and detector.dependency
        }

    def collect(self) -> list[Observation]:
        return [self._collect_one(signal) for signal in self.config.signals if signal.source == "prometheus"]

    def _collect_one(self, signal) -> Observation:
        labels = {
            "query_id": signal.query_id,
            "service": signal.service,
            "flow": signal.flow,
            "sample_timestamp": str(time.time()),
        }
        dependency = self._dependencies.get(signal.id)
        if dependency:
            labels["dependency"] = dependency
        try:
            query = self.config.prometheus_queries[signal.query_id]
            result = self.client.query(query).get("data", {}).get("result", [])
        except Exception as exc:
            labels["error"] = type(exc).__name__
            return Observation(signal_id=signal.id, value=None, unit=signal.unit, window=signal.window, quality=SignalQuality.MISSING, labels=labels)
        if not result:
            return Observation(signal_id=signal.id, value=None, unit=signal.unit, window=signal.window, quality=SignalQuality.MISSING, labels=labels)
        sample = result[0]
        metric = sample.get("metric", {})
        value = sample.get("value", [labels["sample_timestamp"], None])
        labels.update({key: str(value) for key, value in metric.items()})
        if value and value[0]:
            labels["sample_timestamp"] = str(value[0])
        return Observation(signal_id=signal.id, value=value[1], unit=signal.unit, window=signal.window, quality=SignalQuality.UNQUALIFIED, labels=labels)
