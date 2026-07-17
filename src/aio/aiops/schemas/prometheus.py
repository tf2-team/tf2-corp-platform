from __future__ import annotations

from pydantic import Field

from aiops.schemas.base import AiopsModel


class PrometheusObservationQuery(AiopsModel):
    query_id: str
    signal_id: str
    promql: str
    unit: str
    window: str
    labels: dict[str, str] = Field(default_factory=dict)


class PrometheusMetricSeriesQuery(AiopsModel):
    query_id: str
    signal_id: str
    service: str
    metric: str
    promql: str
    lookback_seconds: int
    step_seconds: int


class PrometheusCollectionPlan(AiopsModel):
    schema_version: str
    observation_queries: list[PrometheusObservationQuery]
    metric_series_queries: list[PrometheusMetricSeriesQuery] = Field(default_factory=list)
