from __future__ import annotations

from pydantic import Field

from aiops.schemas.base import AiopsModel
from aiops.schemas.domain import Observation


class PipelineRunRequest(AiopsModel):
    observations: list[Observation] = Field(default_factory=list)


class HealthResponse(AiopsModel):
    status: str


class GrafanaAlert(AiopsModel):
    status: str
    labels: dict[str, str]
    starts_at: str = Field(alias="startsAt")
    annotations: dict[str, str] = Field(default_factory=dict)


class GrafanaWebhookEvent(AiopsModel):
    receiver: str
    status: str
    alerts: list[GrafanaAlert]


class GrafanaNormalizedEvent(AiopsModel):
    source: str
    status: str
    alert_count: int
    alert_names: list[str]
