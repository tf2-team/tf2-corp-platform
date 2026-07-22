#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from aiops.schemas.base import AiopsModel
from aiops.schemas.prometheus import CompiledPrometheusQuery


PLACEHOLDER_TOKENS = ("<", "TODO", "TBD", "REPLACE_ME")


class TopologyService(AiopsModel):
    name: str
    namespace: str
    kind: str
    owner: str
    flow: str
    dependencies: list[str] = Field(
        default_factory=list,
        description="RCA-impacting dependencies, directed from the service to the dependency.",
    )


class TopologyConfig(AiopsModel):
    services: list[TopologyService]


class SignalDefinition(AiopsModel):
    id: str
    source: Literal["prometheus", "grafana", "jaeger", "opensearch", "kubernetes", "aie", "cost"]
    query_id: str
    unit: Literal["ratio", "seconds", "milliseconds", "count", "requests_per_second", "bytes", "bytes_per_second", "millicores", "percent", "boolean"]
    window: str
    flow: str
    service: str
    feature_role: Literal["official_slo", "diagnostic", "anomaly_input", "dependency_signal"]
    required_labels: list[str] = Field(default_factory=list)


class DetectorDefinition(AiopsModel):
    id: str
    type: Literal["threshold", "dependency", "no-data"]
    enabled: bool = True
    signal_id: str | None = None
    signal_ids: list[str] = Field(default_factory=list)
    flow: str
    service: str
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]
    runbook_id: str
    dependency: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "DetectorDefinition":
        if self.type in {"threshold", "dependency"} and self.signal_id is None:
            raise ValueError(f"{self.type} detector requires signal_id")
        if self.type == "dependency" and self.dependency is None:
            raise ValueError("dependency detector requires dependency")
        if self.type == "no-data" and not self.signal_ids:
            raise ValueError("no-data detector requires signal_ids")
        return self


class RuntimePolicyConfig(AiopsModel):
    protected_targets: set[str]
    stateful_kinds: set[str]
    non_actionable_flows: set[str]


class RcaConfig(AiopsModel):
    enabled: bool = True


class RuntimeConfig(AiopsModel):
    schema_version: Literal["1.0"]
    environment: str
    topology: TopologyConfig
    prometheus_queries: dict[str, str] = Field(default_factory=dict)
    prometheus_query_specs: dict[str, CompiledPrometheusQuery] = Field(default_factory=dict)
    prometheus_services: list[str] = Field(default_factory=list)
    signals: list[SignalDefinition]
    detectors: list[DetectorDefinition]
    detector_thresholds: dict[str, float] = Field(default_factory=dict)
    detector_confidences: dict[str, float] = Field(default_factory=dict)
    policy: RuntimePolicyConfig
    rca: RcaConfig = Field(default_factory=RcaConfig)

    @model_validator(mode="after")
    def validate_references(self) -> "RuntimeConfig":
        signal_ids = {signal.id for signal in self.signals}
        service_names = [service.name for service in self.topology.services]
        duplicate_services = sorted(name for name, count in Counter(service_names).items() if count > 1)
        if duplicate_services:
            raise ValueError(f"duplicate topology services: {duplicate_services}")
        service_name_set = set(service_names)
        unknown_prometheus_services = set(self.prometheus_services) - service_name_set
        if unknown_prometheus_services:
            raise ValueError(f"unknown prometheus services: {sorted(unknown_prometheus_services)}")
        missing_prometheus_queries = {signal.query_id for signal in self.signals if signal.source == "prometheus"} - set(self.prometheus_queries)
        if missing_prometheus_queries:
            raise ValueError(f"missing prometheus queries: {sorted(missing_prometheus_queries)}")
        missing_prometheus_specs = {signal.query_id for signal in self.signals if signal.source == "prometheus"} - set(self.prometheus_query_specs)
        if missing_prometheus_specs:
            raise ValueError(f"missing prometheus query specs: {sorted(missing_prometheus_specs)}")
        for service in self.topology.services:
            duplicate_dependencies = sorted(
                name for name, count in Counter(service.dependencies).items() if count > 1
            )
            if duplicate_dependencies:
                raise ValueError(f"duplicate dependencies for {service.name}: {duplicate_dependencies}")
            if service.name in service.dependencies:
                raise ValueError(f"self dependency for {service.name}")
            missing = set(service.dependencies) - service_name_set
            if missing:
                raise ValueError(f"unknown dependencies for {service.name}: {sorted(missing)}")
        for detector in self.detectors:
            referenced = [detector.signal_id] if detector.signal_id else detector.signal_ids
            missing = set(referenced) - signal_ids
            if missing:
                raise ValueError(f"unknown detector signals for {detector.id}: {sorted(missing)}")
        reject_unresolved_placeholders(self.model_dump())
        return self


def reject_unresolved_placeholders(value: object) -> None:
    if isinstance(value, str) and any(token in value for token in PLACEHOLDER_TOKENS):
        raise ValueError(f"unresolved placeholder: {value}")
    if isinstance(value, dict):
        for child in value.values():
            reject_unresolved_placeholders(child)
    if isinstance(value, (list, tuple, set)):
        for child in value:
            reject_unresolved_placeholders(child)
