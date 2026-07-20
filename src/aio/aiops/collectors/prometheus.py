#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import logging
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Protocol, TypeVar

from aiops.collectors.base import Collector
from aiops.schemas import (
    CompiledPrometheusQuery,
    MetricPoint,
    MetricSeries,
    Observation,
    PrometheusCollectionPlan,
    PrometheusMetricSeriesQuery,
    PrometheusObservationQuery,
    PrometheusPlanSelection,
    RuntimeConfig,
    SignalQuality,
)

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - keeps old envs working until dependencies are refreshed.
    tqdm = None


logger = logging.getLogger(__name__)
T = TypeVar("T")
_RANGE_CACHE: dict[tuple[str, str, int, str], list[MetricPoint]] = {}


def load_prometheus_collection_plan(path: Path) -> PrometheusCollectionPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "observation_queries" in raw:
        return PrometheusCollectionPlan.model_validate(raw)
    selection = PrometheusPlanSelection.model_validate(raw)
    from aiops.config.runtime import load_runtime_config

    runtime = load_runtime_config(path.with_name("runtime.json"), path.with_name("prometheus_queries.json"))
    observations = [_plan_observation(runtime, query_id) for query_id in selection.observation_query_ids]
    series = [_plan_series(runtime, query_id) for query_id in selection.metric_series_query_ids]
    return PrometheusCollectionPlan(schema_version=selection.schema_version, observation_queries=observations, metric_series_queries=series)


def _plan_observation(runtime: RuntimeConfig, query_id: str) -> PrometheusObservationQuery:
    spec = _spec(runtime, query_id, "instant")
    return PrometheusObservationQuery(
        query_id=query_id,
        signal_id=spec.signal_id,
        promql=spec.promql,
        unit=spec.unit,
        window=spec.window,
        labels={"service": spec.service, "flow": spec.flow, **spec.labels},
        max_series=spec.max_series,
        max_concurrency=spec.max_concurrency,
    )


def _plan_series(runtime: RuntimeConfig, query_id: str) -> PrometheusMetricSeriesQuery:
    spec = _spec(runtime, query_id, "range")
    return PrometheusMetricSeriesQuery(
        query_id=query_id,
        signal_id=spec.signal_id,
        service=spec.service,
        metric=spec.metric,
        promql=spec.promql,
        lookback_seconds=spec.lookback_seconds,
        step_seconds=spec.step_seconds,
        detector_bucket_seconds=spec.detector_bucket_seconds,
        max_series=spec.max_series,
        max_concurrency=spec.max_concurrency,
    )


def _spec(runtime: RuntimeConfig, query_id: str, mode: str) -> CompiledPrometheusQuery:
    try:
        spec = runtime.prometheus_query_specs[query_id]
    except KeyError as exc:
        raise ValueError(f"unknown prometheus query id: {query_id}") from exc
    if mode not in spec.modes:
        raise ValueError(f"prometheus query {query_id} does not support {mode} mode")
    return spec


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
        cache_namespace: str | None = None,
    ):
        self.client = client
        self.config = runtime_config_or_plan if isinstance(runtime_config_or_plan, RuntimeConfig) else None
        self.plan = runtime_config_or_plan if isinstance(runtime_config_or_plan, PrometheusCollectionPlan) else None
        self.captured_at = (captured_at or datetime.now(UTC)).astimezone(UTC)
        self.cache_namespace = cache_namespace
        self._dependencies = {
            detector.signal_id: detector.dependency
            for detector in (self.config.detectors if self.config else [])
            if detector.type == "dependency" and detector.signal_id and detector.dependency
        }

    def collect(self) -> list[Observation]:
        if self.plan is not None:
            queries = self.plan.observation_queries
            return _parallel_collect(queries, self._collect_plan_observation, _max_workers(queries), "prometheus observations")
        assert self.config is not None
        signals = [
            signal
            for signal in self.config.signals
            if signal.source == "prometheus" and "instant" in self.config.prometheus_query_specs[signal.query_id].modes
        ]
        workers = max((self.config.prometheus_query_specs[signal.query_id].max_concurrency for signal in signals), default=1)
        return _parallel_collect(signals, self._collect_one, workers, "prometheus observations")

    def collect_metric_series(self, *, lookback_seconds: int | None = None, step_seconds: int | None = None) -> list[MetricSeries]:
        if self.plan is not None:
            queries = self.plan.metric_series_queries
            return _parallel_collect(queries, self._collect_plan_series, _max_workers(queries), "prometheus metric series")
        assert self.config is not None
        signals = [
            signal
            for signal in self.config.signals
            if signal.source == "prometheus"
            and signal.feature_role == "anomaly_input"
            and "range" in self.config.prometheus_query_specs[signal.query_id].modes
        ]
        if lookback_seconds is not None or step_seconds is not None:
            logger.warning("runtime Prometheus range settings come from prometheus_queries.json; call overrides are ignored")
        workers = max((self.config.prometheus_query_specs[signal.query_id].max_concurrency for signal in signals), default=1)
        return _parallel_collect(signals, self._collect_runtime_series, workers, "prometheus metric series")

    def _collect_plan_observation(self, query: PrometheusObservationQuery) -> Observation:
        labels = {"query_id": query.query_id, **query.labels}
        try:
            result = self.client.query(query.promql, time=str(int(self.captured_at.timestamp()))).get("data", {}).get("result", [])
        except Exception as exc:
            return _missing_observation(query.signal_id, query.unit, query.window, labels, type(exc).__name__)
        return _observation_from_result(query.signal_id, query.unit, query.window, labels, result, query.max_series, SignalQuality.VERIFIED)

    def _collect_plan_series(self, query: PrometheusMetricSeriesQuery) -> MetricSeries:
        end = int(self.captured_at.timestamp())
        start = end - query.lookback_seconds
        try:
            result = self.client.query_range(query.promql, start=str(start), end=str(end), step=str(query.step_seconds)).get("data", {}).get("result", [])
        except Exception as exc:
            return _invalid_series(query.service, query.metric, query.signal_id, query.step_seconds, query.detector_bucket_seconds, SignalQuality.MISSING, type(exc).__name__)
        return _series_from_result(
            query.service,
            query.metric,
            query.signal_id,
            result,
            query.step_seconds,
            query.detector_bucket_seconds,
            query.max_series,
        )

    def _collect_runtime_series(self, signal) -> MetricSeries:
        assert self.config is not None
        spec = self.config.prometheus_query_specs[signal.query_id]
        end = int(self.captured_at.timestamp())
        cutoff = end - spec.lookback_seconds
        cache_key = (
            (self.cache_namespace, signal.query_id, spec.step_seconds, spec.promql)
            if self.cache_namespace and spec.incremental
            else None
        )
        cached = (
            [point for point in _RANGE_CACHE.get(cache_key, []) if cutoff <= point.timestamp <= end]
            if cache_key
            else []
        )
        start = cached[-1].timestamp + spec.step_seconds if cached else cutoff
        if start > end:
            return _metric_series(spec, cached)
        try:
            result = self.client.query_range(spec.promql, start=str(start), end=str(end), step=str(spec.step_seconds)).get("data", {}).get("result", [])
        except Exception as exc:
            return _invalid_series(spec.service, spec.metric, spec.signal_id, spec.step_seconds, spec.detector_bucket_seconds, SignalQuality.MISSING, type(exc).__name__)
        fresh = _series_from_result(
            spec.service,
            spec.metric,
            spec.signal_id,
            result,
            spec.step_seconds,
            spec.detector_bucket_seconds,
            spec.max_series,
        )
        if fresh.quality != SignalQuality.VERIFIED:
            return fresh
        points = _merge_points(cached, fresh.points, cutoff)
        error = _gap_error(points, spec.step_seconds)
        if error:
            return _invalid_series(spec.service, spec.metric, spec.signal_id, spec.step_seconds, spec.detector_bucket_seconds, SignalQuality.INVALID, error, points)
        if cache_key:
            _RANGE_CACHE[cache_key] = points
        return _metric_series(spec, points, labels=fresh.labels)

    def _collect_one(self, signal) -> Observation:
        assert self.config is not None
        spec = self.config.prometheus_query_specs[signal.query_id]
        labels = {"query_id": signal.query_id, "service": signal.service, "flow": signal.flow, **spec.labels}
        dependency = self._dependencies.get(signal.id)
        if dependency:
            labels["dependency"] = dependency
        try:
            result = self.client.query(spec.promql).get("data", {}).get("result", [])
        except Exception as exc:
            return _missing_observation(signal.id, signal.unit, signal.window, labels, type(exc).__name__)
        return _observation_from_result(signal.id, signal.unit, signal.window, labels, result, spec.max_series, SignalQuality.UNQUALIFIED)


def _observation_from_result(signal_id, unit, window, labels, result, max_series, success_quality) -> Observation:
    labels = {**labels, "series_count": str(len(result))}
    if not result:
        return _missing_observation(signal_id, unit, window, labels)
    if len(result) > max_series:
        return Observation(signal_id=signal_id, value=None, unit=unit, window=window, quality=SignalQuality.INVALID, labels={**labels, "error": "CardinalityExceeded"})
    sample = result[0]
    metric_labels = {key: str(value) for key, value in sample.get("metric", {}).items()}
    value = sample.get("value", [None, None])
    try:
        timestamp = str(value[0])
        parsed = float(value[1])
    except (IndexError, TypeError, ValueError):
        return Observation(signal_id=signal_id, value=None, unit=unit, window=window, quality=SignalQuality.INVALID, labels={**labels, "error": "InvalidSample"})
    if not math.isfinite(parsed):
        return Observation(signal_id=signal_id, value=None, unit=unit, window=window, quality=SignalQuality.INVALID, labels={**labels, "error": "NonFiniteSample"})
    return Observation(
        signal_id=signal_id,
        value=parsed,
        unit=unit,
        window=window,
        quality=success_quality,
        labels={**labels, **metric_labels, "sample_timestamp": timestamp},
    )


def _missing_observation(signal_id, unit, window, labels, error: str | None = None) -> Observation:
    return Observation(
        signal_id=signal_id,
        value=None,
        unit=unit,
        window=window,
        quality=SignalQuality.MISSING,
        labels={**labels, **({"error": error} if error else {})},
    )


def _series_from_result(service, metric, signal_id, result, step_seconds, detector_bucket_seconds, max_series) -> MetricSeries:
    labels = {"series_count": str(len(result))}
    if not result:
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.MISSING, "NoData", labels=labels)
    if len(result) > max_series:
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.INVALID, "CardinalityExceeded", labels=labels)
    labels.update({key: str(value) for key, value in result[0].get("metric", {}).items()})
    try:
        points = [MetricPoint(timestamp=int(float(timestamp)), value=float(value)) for timestamp, value in result[0].get("values", [])]
    except (TypeError, ValueError):
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.INVALID, "InvalidSample", labels=labels)
    points = _merge_points([], points, -1)
    if not points:
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.MISSING, "NoSamples", labels=labels)
    if any(not math.isfinite(point.value) for point in points):
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.INVALID, "NonFiniteSample", points, labels)
    error = _gap_error(points, step_seconds)
    if error:
        return _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, SignalQuality.INVALID, error, points, labels)
    return MetricSeries(
        service=service,
        metric=metric,
        signal_id=signal_id,
        points=points,
        quality=SignalQuality.VERIFIED,
        labels=labels,
        step_seconds=step_seconds,
        detector_bucket_seconds=detector_bucket_seconds,
    )


def _invalid_series(service, metric, signal_id, step_seconds, detector_bucket_seconds, quality, error, points=None, labels=None) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=metric,
        signal_id=signal_id,
        points=points or [],
        quality=quality,
        labels=labels or {},
        step_seconds=step_seconds,
        detector_bucket_seconds=detector_bucket_seconds,
        error=error,
    )


def _metric_series(spec: CompiledPrometheusQuery, points: list[MetricPoint], labels=None) -> MetricSeries:
    return MetricSeries(
        service=spec.service,
        metric=spec.metric,
        signal_id=spec.signal_id,
        points=points,
        quality=SignalQuality.VERIFIED if points else SignalQuality.MISSING,
        labels=labels or {},
        step_seconds=spec.step_seconds,
        detector_bucket_seconds=spec.detector_bucket_seconds,
        error=None if points else "NoData",
    )


def _merge_points(existing: list[MetricPoint], fresh: list[MetricPoint], cutoff: int) -> list[MetricPoint]:
    by_timestamp = {point.timestamp: point for point in [*existing, *fresh] if point.timestamp >= cutoff}
    return [by_timestamp[timestamp] for timestamp in sorted(by_timestamp)]


def _gap_error(points: list[MetricPoint], step_seconds: int) -> str | None:
    for previous, current in zip(points, points[1:]):
        gap = current.timestamp - previous.timestamp
        if gap != step_seconds:
            return f"UnexpectedGap:{gap}"
    return None


def _progress(items: Iterable[T], desc: str) -> Iterable[T]:
    if tqdm is None:
        return items
    return tqdm(items, desc=desc, unit="query", leave=False, disable=not sys.stderr.isatty())


def _max_workers(queries) -> int:
    return max((query.max_concurrency for query in queries), default=1)


def _parallel_collect(items: list[T], collect_one, max_workers: int, desc: str) -> list:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items)), thread_name_prefix="prometheus") as executor:
        return list(_progress(executor.map(collect_one, items), desc))
