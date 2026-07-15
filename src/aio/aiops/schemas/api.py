from __future__ import annotations

from pydantic import Field

from aiops.schemas.base import AiopsModel
from aiops.schemas.domain import MetricSeries, Observation


class PipelineRunRequest(AiopsModel):
    observations: list[Observation] = Field(default_factory=list)
    metric_series: list[MetricSeries] = Field(default_factory=list)


class HealthResponse(AiopsModel):
    status: str


class GrafanaAlert(AiopsModel):
    status: str
    labels: dict[str, str]
    starts_at: str = Field(alias="startsAt")
    ends_at: str | None = Field(default=None, alias="endsAt")
    annotations: dict[str, str] = Field(default_factory=dict)
    fingerprint: str | None = None
    generator_url: str | None = Field(default=None, alias="generatorURL")
    dashboard_url: str | None = Field(default=None, alias="dashboardURL")
    panel_url: str | None = Field(default=None, alias="panelURL")


class GrafanaWebhookEvent(AiopsModel):
    receiver: str
    status: str
    alerts: list[GrafanaAlert]


class GrafanaNormalizedEvent(AiopsModel):
    schema_version: str = "1.0"
    source: str
    status: str
    alert_id: str
    received_at: str
    starts_at: str
    ends_at: str | None = None
    labels: dict[str, str]
    annotations_redacted: dict[str, str] = Field(default_factory=dict)
    links: dict[str, str | None] = Field(default_factory=dict)
