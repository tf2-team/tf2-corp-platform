#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pydantic import Field

from aiops.schemas.base import AiopsModel
from aiops.schemas.domain import MetricSeries, Observation, PipelineResult


class PipelineRunRequest(AiopsModel):
    observations: list[Observation] = Field(default_factory=list)
    metric_series: list[MetricSeries] = Field(default_factory=list)


class ReplayScenario(AiopsModel):
    scenario_id: str
    expected_incident: bool
    incident_start_timestamp: int | None = None
    expected_service: str | None = None
    expected_severity: str | None = None
    observations: list[Observation] = Field(default_factory=list)
    metric_series: list[MetricSeries] = Field(default_factory=list)


class ReplayRequest(AiopsModel):
    scenarios: list[ReplayScenario] = Field(min_length=1)
    baseline_mttd_seconds: float | None = Field(default=None, ge=0)
    execute_remediation: bool = False


class ReplayCaseResult(AiopsModel):
    scenario_id: str
    expected_incident: bool
    detected: bool
    detection_timestamp: int | None = None
    lead_time_seconds: float | None = None
    service_correct: bool | None = None
    severity_correct: bool | None = None
    incident_ids: list[str] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    pipeline_result: PipelineResult


class ReplayMetrics(AiopsModel):
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    mean_lead_time_seconds: float | None = None
    mttd_before_seconds: float | None = None
    mttd_after_seconds: float | None = None
    mttd_improvement_seconds: float | None = None


class ReplayReport(AiopsModel):
    cases: list[ReplayCaseResult]
    metrics: ReplayMetrics


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
