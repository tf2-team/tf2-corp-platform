from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Protocol, TypeVar

from aiops.collectors.base import Collector
from aiops.schemas import (
    MetricPoint,
    MetricSeries,
    Observation,
    PrometheusCollectionPlan,
    PrometheusMetricSeriesQuery,
    PrometheusObservationQuery,
    RuntimeConfig,
    SignalQuality,
)

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - keeps old envs working until dependencies are refreshed.
    tqdm = None

T = TypeVar("T")


def load_prometheus_collection_plan(path: Path) -> PrometheusCollectionPlan:
    return PrometheusCollectionPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))


class PrometheusClientLike(Protocol):
    def query(self, query: str, time: str | None = None) -> dict: ...

    def query_range(self, query: str, start: str, end: str, step: str) -> dict: ...


class PrometheusCollector(Collector):
    def __init__(
        self,
        client: PrometheusClientLike,
        runtime_config_or_plan: RuntimeConfig | PrometheusCollectionPlan,
        *,
        captured_at: datetime | None = None,
    ):
        self.client = client
        self.config = runtime_config_or_plan if isinstance(runtime_config_or_plan, RuntimeConfig) else None
        self.plan = runtime_config_or_plan if isinstance(runtime_config_or_plan, PrometheusCollectionPlan) else None
        self.captured_at = (captured_at or datetime.now(UTC)).astimezone(UTC)
        self._dependencies = {
            detector.signal_id: detector.dependency
            for detector in (self.config.detectors if self.config else [])
            if detector.type == "dependency" and detector.signal_id and detector.dependency
        }

    def collect(self) -> list[Observation]:
        if self.plan is not None:
            return [self._collect_plan_observation(query) for query in _progress(self.plan.observation_queries, "prometheus observations")]
        assert self.config is not None
        signals = [signal for signal in self.config.signals if signal.source == "prometheus"]
        return [self._collect_one(signal) for signal in _progress(signals, "prometheus observations")]

    def collect_metric_series(self, *, lookback_seconds: int | None = None, step_seconds: int | None = None) -> list[MetricSeries]:
        if self.plan is None:
            assert self.config is not None
            if lookback_seconds is None or step_seconds is None:
                raise ValueError("runtime metric series collection requires lookback_seconds and step_seconds")
            signals = [
                signal
                for signal in self.config.signals
                if signal.source == "prometheus" and signal.feature_role == "anomaly_input"
            ]
            return [
                self._collect_runtime_series(signal, lookback_seconds, step_seconds)
                for signal in _progress(signals, "prometheus metric series")
            ]
        return [self._collect_plan_series(query) for query in _progress(self.plan.metric_series_queries, "prometheus metric series")]

    def _collect_plan_observation(self, query: PrometheusObservationQuery) -> Observation:
        labels = {"query_id": query.query_id, **query.labels}
        try:
            result = self.client.query(query.promql, time=str(self.captured_at.timestamp())).get("data", {}).get("result", [])
        except Exception as exc:
            return Observation(
                signal_id=query.signal_id,
                value=None,
                unit=query.unit,
                window=query.window,
                quality=SignalQuality.MISSING,
                labels={**labels, "error": type(exc).__name__},
            )
        if not result:
            return Observation(signal_id=query.signal_id, value=None, unit=query.unit, window=query.window, quality=SignalQuality.MISSING, labels=labels)
        sample = result[0].get("value", [self.captured_at.timestamp(), None])
        if sample and sample[0]:
            labels["sample_timestamp"] = str(sample[0])
        return Observation(signal_id=query.signal_id, value=sample[1], unit=query.unit, window=query.window, quality=SignalQuality.VERIFIED, labels=labels)

    def _collect_plan_series(self, query: PrometheusMetricSeriesQuery) -> MetricSeries:
        end = self.captured_at
        start = end - timedelta(seconds=query.lookback_seconds)
        result = self.client.query_range(
            query.promql,
            start=str(start.timestamp()),
            end=str(end.timestamp()),
            step=str(query.step_seconds),
        ).get("data", {}).get("result", [])
        values = result[0].get("values", []) if result else []
        return MetricSeries(
            service=query.service,
            metric=query.metric,
            signal_id=query.signal_id,
            points=[MetricPoint(timestamp=int(float(timestamp)), value=float(value)) for timestamp, value in values],
        )

    def _collect_runtime_series(self, signal, lookback_seconds: int, step_seconds: int) -> MetricSeries:
        assert self.config is not None
        end = self.captured_at
        start = end - timedelta(seconds=lookback_seconds)
        try:
            result = self.client.query_range(
                self.config.prometheus_queries[signal.query_id],
                start=str(start.timestamp()),
                end=str(end.timestamp()),
                step=str(step_seconds),
            ).get("data", {}).get("result", [])
        except Exception:
            result = []
        values = result[0].get("values", []) if result else []
        return MetricSeries(
            service=signal.service,
            metric=self._metric_name(signal.service, signal.id),
            signal_id=signal.id,
            points=[MetricPoint(timestamp=int(float(timestamp)), value=float(value)) for timestamp, value in values],
        )

    def _metric_name(self, service: str, signal_id: str) -> str:
        prefix = f"{service.replace('-', '_')}_"
        return signal_id.removeprefix(prefix)

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


def _progress(items: Iterable[T], desc: str) -> Iterable[T]:
    if tqdm is None:
        return items
    return tqdm(items, desc=desc, unit="query", leave=False, disable=not sys.stderr.isatty())
