#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from aiops.schemas.base import AiopsModel


class PrometheusObservationQuery(AiopsModel):
    query_id: str
    signal_id: str
    promql: str
    unit: str
    window: str
    labels: dict[str, str] = Field(default_factory=dict)
    max_series: int = Field(default=1, ge=1, le=1000)
    max_concurrency: int = Field(default=8, ge=1, le=32)


class PrometheusMetricSeriesQuery(AiopsModel):
    query_id: str
    signal_id: str
    service: str
    metric: str
    promql: str
    lookback_seconds: int
    step_seconds: int
    detector_bucket_seconds: int = 60
    max_series: int = Field(default=1, ge=1, le=1000)
    max_concurrency: int = Field(default=8, ge=1, le=32)


class PrometheusCollectionPlan(AiopsModel):
    schema_version: str
    observation_queries: list[PrometheusObservationQuery]
    metric_series_queries: list[PrometheusMetricSeriesQuery] = Field(default_factory=list)


class PrometheusCollectionProfile(AiopsModel):
    step_seconds: int = Field(default=1, ge=1, le=3600)
    lookback_seconds: int = Field(ge=1)
    detector_bucket_seconds: int = Field(default=60, ge=1)
    required_source_resolution_seconds: int = Field(default=1, ge=1)
    incremental: bool = True
    max_concurrency: int = Field(default=8, ge=1, le=32)

    @model_validator(mode="after")
    def validate_bucket(self) -> "PrometheusCollectionProfile":
        if self.detector_bucket_seconds % self.step_seconds:
            raise ValueError("detector_bucket_seconds must be a multiple of step_seconds")
        return self


class PrometheusResultContract(AiopsModel):
    max_series: int = Field(default=1, ge=1, le=1000)
    on_empty: Literal["missing", "zero"] = "missing"
    finite_only: Literal[True] = True


class PrometheusQueryTemplate(AiopsModel):
    query_id_template: str
    signal_id_template: str
    promql: str
    unit: str
    window: str
    metric: str
    feature_role: Literal["official_slo", "diagnostic", "anomaly_input", "dependency_signal"]
    collection_profile: str = "one_second"
    modes: set[Literal["instant", "range"]] = Field(default_factory=lambda: {"instant", "range"})
    required_labels: list[str] = Field(default_factory=list)
    result: PrometheusResultContract | None = None
    required_for_monitoring: bool = True


class PrometheusServiceGroup(AiopsModel):
    services: list[str]
    template_ids: list[str]
    parameters: dict[str, str] = Field(default_factory=dict)


class PrometheusQueryInstance(AiopsModel):
    query_id: str
    signal_id: str
    template_id: str
    service: str
    parameters: dict[str, str] = Field(default_factory=dict)
    feature_role: Literal["official_slo", "diagnostic", "anomaly_input", "dependency_signal"] | None = None
    required_labels: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    required_for_monitoring: bool | None = None


class PrometheusQueryRegistry(AiopsModel):
    schema_version: Literal["2.0"]
    collection_profiles: dict[str, PrometheusCollectionProfile]
    result_defaults: PrometheusResultContract = Field(default_factory=PrometheusResultContract)
    templates: dict[str, PrometheusQueryTemplate]
    service_groups: list[PrometheusServiceGroup] = Field(default_factory=list)
    instances: list[PrometheusQueryInstance] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "PrometheusQueryRegistry":
        referenced_templates = {
            template_id
            for group in self.service_groups
            for template_id in group.template_ids
        } | {instance.template_id for instance in self.instances}
        missing_templates = referenced_templates - set(self.templates)
        if missing_templates:
            raise ValueError(f"unknown prometheus templates: {sorted(missing_templates)}")
        missing_profiles = {
            template.collection_profile for template in self.templates.values()
        } - set(self.collection_profiles)
        if missing_profiles:
            raise ValueError(f"unknown prometheus collection profiles: {sorted(missing_profiles)}")
        return self


class CompiledPrometheusQuery(AiopsModel):
    query_id: str
    signal_id: str
    promql: str
    unit: str
    window: str
    service: str
    flow: str
    metric: str
    feature_role: Literal["official_slo", "diagnostic", "anomaly_input", "dependency_signal"]
    modes: set[Literal["instant", "range"]]
    required_labels: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    max_series: int = Field(default=1, ge=1, le=1000)
    lookback_seconds: int = Field(ge=1)
    step_seconds: int = Field(default=1, ge=1, le=3600)
    detector_bucket_seconds: int = Field(default=60, ge=1)
    required_source_resolution_seconds: int = Field(default=1, ge=1)
    incremental: bool = True
    max_concurrency: int = Field(default=8, ge=1, le=32)
    required_for_monitoring: bool = True


class PrometheusPlanSelection(AiopsModel):
    schema_version: Literal["2.0"]
    observation_query_ids: list[str]
    metric_series_query_ids: list[str] = Field(default_factory=list)
