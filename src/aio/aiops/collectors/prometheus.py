from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from aiops.collectors.base import Collector
from aiops.integrations.prometheus import PrometheusClient
from aiops.schemas import MetricPoint, MetricSeries, Observation, SignalQuality
from aiops.schemas.base import AiopsModel


class PrometheusObservationQuery(AiopsModel):
    query_id: str = Field(min_length=3)
    signal_id: str = Field(min_length=3)
    promql: str = Field(min_length=1)
    unit: str
    window: str
    labels: dict[str, str] = Field(default_factory=dict)


class PrometheusMetricQuery(AiopsModel):
    query_id: str = Field(min_length=3)
    signal_id: str = Field(min_length=3)
    service: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    promql: str = Field(min_length=1)
    lookback_seconds: int = Field(default=3600, ge=60)
    step_seconds: int = Field(default=60, ge=1)


class PrometheusCollectionPlan(AiopsModel):
    schema_version: Literal["1.0"]
    observation_queries: list[PrometheusObservationQuery] = Field(min_length=1)
    metric_series_queries: list[PrometheusMetricQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "PrometheusCollectionPlan":
        query_ids = [query.query_id for query in [*self.observation_queries, *self.metric_series_queries]]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("Prometheus query_id values must be unique")
        signal_ids = [query.signal_id for query in self.observation_queries]
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("Prometheus observation signal_id values must be unique")
        return self


def load_prometheus_collection_plan(path: Path) -> PrometheusCollectionPlan:
    return PrometheusCollectionPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))


class PrometheusCollector(Collector):
    def __init__(
        self,
        client: PrometheusClient,
        plan: PrometheusCollectionPlan,
        captured_at: datetime | None = None,
    ):
        self.client = client
        self.plan = plan
        self.captured_at = (captured_at or datetime.now(UTC)).astimezone(UTC)

    def collect(self) -> list[Observation]:
        observations: list[Observation] = []
        evaluation_time = str(self.captured_at.timestamp())
        for query in self.plan.observation_queries:
            payload = self.client.query(query.promql, time=evaluation_time)
            value, response_labels, quality = parse_instant_result(payload, query.query_id)
            observations.append(
                Observation(
                    signal_id=query.signal_id,
                    value=value,
                    unit=query.unit,
                    window=query.window,
                    quality=quality,
                    labels={**response_labels, **query.labels},
                )
            )
        return observations

    def collect_metric_series(self) -> list[MetricSeries]:
        series: list[MetricSeries] = []
        end = self.captured_at
        for query in self.plan.metric_series_queries:
            start = end - timedelta(seconds=query.lookback_seconds)
            payload = self.client.query_range(
                query.promql,
                str(start.timestamp()),
                str(end.timestamp()),
                str(query.step_seconds),
            )
            points = parse_range_result(payload, query.query_id)
            if points:
                series.append(
                    MetricSeries(
                        service=query.service,
                        metric=query.metric,
                        signal_id=query.signal_id,
                        points=points,
                    )
                )
        return series


def parse_instant_result(payload: dict, query_id: str) -> tuple[float | None, dict[str, str], SignalQuality]:
    data = _successful_data(payload, query_id)
    result_type = data.get("resultType")
    result = data.get("result")

    if result_type == "scalar":
        value = _sample_value(result, query_id)
        return _quality_value(value), {}, _quality(value)
    if result_type != "vector" or not isinstance(result, list):
        raise ValueError(f"Prometheus query {query_id} returned unsupported instant result type {result_type!r}")
    if not result:
        return None, {}, SignalQuality.MISSING
    if len(result) != 1:
        raise ValueError(f"Prometheus query {query_id} must aggregate to one series; got {len(result)}")

    item = result[0]
    if not isinstance(item, dict):
        raise ValueError(f"Prometheus query {query_id} returned an invalid vector item")
    value = _sample_value(item.get("value"), query_id)
    labels = item.get("metric", {})
    if not isinstance(labels, dict):
        raise ValueError(f"Prometheus query {query_id} returned invalid metric labels")
    return _quality_value(value), {str(key): str(item) for key, item in labels.items()}, _quality(value)


def parse_range_result(payload: dict, query_id: str) -> list[MetricPoint]:
    data = _successful_data(payload, query_id)
    result_type = data.get("resultType")
    result = data.get("result")
    if result_type != "matrix" or not isinstance(result, list):
        raise ValueError(f"Prometheus query {query_id} returned unsupported range result type {result_type!r}")
    if not result:
        return []
    if len(result) != 1:
        raise ValueError(f"Prometheus query {query_id} must aggregate to one series; got {len(result)}")

    values = result[0].get("values") if isinstance(result[0], dict) else None
    if not isinstance(values, list):
        raise ValueError(f"Prometheus query {query_id} returned invalid range values")

    points: list[MetricPoint] = []
    for sample in values:
        if not isinstance(sample, list) or len(sample) != 2:
            raise ValueError(f"Prometheus query {query_id} returned an invalid range sample")
        value = _sample_value(sample, query_id)
        if not isfinite(value):
            continue
        points.append(MetricPoint(timestamp=int(float(sample[0])), value=value))
    return points


def _successful_data(payload: dict, query_id: str) -> dict:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        error = payload.get("error", "unknown error") if isinstance(payload, dict) else "invalid response"
        raise ValueError(f"Prometheus query {query_id} failed: {error}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"Prometheus query {query_id} returned invalid data")
    return data


def _sample_value(sample: object, query_id: str) -> float:
    if not isinstance(sample, list) or len(sample) != 2:
        raise ValueError(f"Prometheus query {query_id} returned an invalid sample")
    try:
        return float(sample[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Prometheus query {query_id} returned a non-numeric sample") from exc


def _quality(value: float) -> SignalQuality:
    return SignalQuality.VERIFIED if isfinite(value) else SignalQuality.INVALID


def _quality_value(value: float) -> float | None:
    return value if isfinite(value) else None
