#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from string import Template

from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.config.settings import Settings
from aiops.schemas import CompiledPrometheusQuery, PrometheusQueryRegistry, RuntimeConfig


def load_prometheus_query_registry(path: Path) -> PrometheusQueryRegistry:
    return PrometheusQueryRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_runtime_config(path: Path, registry_path: Path | None = None) -> RuntimeConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    registry = load_prometheus_query_registry(_registry_path(path, registry_path))
    specs = _compile_prometheus_registry(raw, registry)
    raw["prometheus_queries"] = {query_id: spec.promql for query_id, spec in specs.items()}
    raw["prometheus_query_specs"] = {query_id: spec.model_dump(mode="json") for query_id, spec in specs.items()}
    raw["prometheus_services"] = sorted({spec.service for spec in specs.values()})
    raw["signals"] = [
        *[signal for signal in raw.get("signals", []) if signal.get("source") != "prometheus"],
        *[_signal_from_spec(spec) for spec in specs.values()],
    ]
    _expand_detector_signal_groups(raw)
    return RuntimeConfig.model_validate(raw)


def _registry_path(runtime_path: Path, configured_path: Path | None) -> Path:
    candidates = [configured_path, runtime_path.with_name("prometheus_queries.json"), Path("config/prometheus_queries.json")]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("prometheus query registry not found")


def _compile_prometheus_registry(raw: dict, registry: PrometheusQueryRegistry) -> dict[str, CompiledPrometheusQuery]:
    topology = {service["name"]: service for service in raw["topology"]["services"]}
    specs: dict[str, CompiledPrometheusQuery] = {}
    signal_ids: set[str] = set()
    for group in registry.service_groups:
        for service in group.services:
            if service not in topology:
                raise ValueError(f"unknown prometheus service: {service}")
            parameters = {
                "service": service,
                "service_id": service.replace("-", "_"),
                "flow": topology[service]["flow"],
                **group.parameters,
            }
            for template_id in group.template_ids:
                template = registry.templates[template_id]
                query_id = _render(template.query_id_template, parameters, f"query id for {template_id}")
                signal_id = _render(template.signal_id_template, parameters, f"signal id for {template_id}")
                spec = _compiled_query(query_id, signal_id, service, topology[service]["flow"], template, parameters, registry)
                _register_spec(specs, signal_ids, spec)
    for instance in registry.instances:
        if instance.service not in topology:
            raise ValueError(f"unknown prometheus instance service: {instance.service}")
        template = registry.templates[instance.template_id]
        parameters = {
            "service": instance.service,
            "service_id": instance.service.replace("-", "_"),
            "flow": topology[instance.service]["flow"],
            **instance.parameters,
        }
        spec = _compiled_query(
            instance.query_id,
            instance.signal_id,
            instance.service,
            topology[instance.service]["flow"],
            template,
            parameters,
            registry,
            feature_role=instance.feature_role,
            required_labels=instance.required_labels,
            labels=instance.labels,
            required_for_monitoring=instance.required_for_monitoring,
        )
        _register_spec(specs, signal_ids, spec)
    return specs


def _compiled_query(
    query_id,
    signal_id,
    service,
    flow,
    template,
    parameters,
    registry,
    *,
    feature_role=None,
    required_labels=None,
    labels=None,
    required_for_monitoring=None,
) -> CompiledPrometheusQuery:
    profile = registry.collection_profiles[template.collection_profile]
    result = template.result or registry.result_defaults
    promql = _render(template.promql, parameters, f"PromQL for {query_id}")
    return CompiledPrometheusQuery(
        query_id=query_id,
        signal_id=signal_id,
        promql=_apply_empty_result_policy(promql, result.on_empty),
        unit=template.unit,
        window=template.window,
        service=service,
        flow=flow,
        metric=_render(template.metric, parameters, f"metric for {query_id}"),
        feature_role=feature_role or template.feature_role,
        modes=template.modes,
        required_labels=list(dict.fromkeys([*template.required_labels, *(required_labels or [])])),
        labels=labels or {},
        max_series=result.max_series,
        lookback_seconds=profile.lookback_seconds,
        step_seconds=profile.step_seconds,
        detector_bucket_seconds=profile.detector_bucket_seconds,
        required_source_resolution_seconds=profile.required_source_resolution_seconds,
        incremental=profile.incremental,
        max_concurrency=profile.max_concurrency,
        required_for_monitoring=template.required_for_monitoring if required_for_monitoring is None else required_for_monitoring,
    )


def _apply_empty_result_policy(promql: str, on_empty: str) -> str:
    if on_empty == "zero":
        return f"(({promql}) or on() vector(0))"
    return promql


def _render(value: str, parameters: dict[str, str], description: str) -> str:
    try:
        rendered = Template(value).substitute(parameters)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"cannot render {description}: {exc}") from exc
    if "$" in rendered:
        raise ValueError(f"unresolved template placeholder in {description}")
    return rendered


def _register_spec(specs: dict[str, CompiledPrometheusQuery], signal_ids: set[str], spec: CompiledPrometheusQuery) -> None:
    if spec.query_id in specs:
        raise ValueError(f"duplicate prometheus query id: {spec.query_id}")
    if spec.signal_id in signal_ids:
        raise ValueError(f"duplicate prometheus signal id: {spec.signal_id}")
    specs[spec.query_id] = spec
    signal_ids.add(spec.signal_id)


def _signal_from_spec(spec: CompiledPrometheusQuery) -> dict:
    return {
        "id": spec.signal_id,
        "source": "prometheus",
        "query_id": spec.query_id,
        "unit": spec.unit,
        "window": spec.window,
        "flow": spec.flow,
        "service": spec.service,
        "feature_role": spec.feature_role,
        "required_labels": spec.required_labels,
    }


def _expand_detector_signal_groups(raw: dict) -> None:
    required_query_ids = {
        query_id
        for query_id, spec in raw.get("prometheus_query_specs", {}).items()
        if spec.get("required_for_monitoring", True)
    }
    prometheus_signal_ids = [
        signal["id"]
        for signal in raw.get("signals", [])
        if signal.get("source") == "prometheus" and signal.get("query_id") in required_query_ids
    ]
    for detector in raw.get("detectors", []):
        if "__all_prometheus__" in detector.get("signal_ids", []):
            detector["signal_ids"] = prometheus_signal_ids
    existing_signal_ids = {detector.get("signal_id") for detector in raw.get("detectors", [])}
    raw.setdefault("detectors", []).extend(
        {
            "id": f"auto_{spec['service'].replace('-', '_')}_latency_p95",
            "type": "threshold",
            "enabled": True,
            "signal_id": spec["signal_id"],
            "flow": spec["flow"],
            "service": spec["service"],
            "severity": "SEV1",
            "runbook_id": "RB-SERVICE-LATENCY",
        }
        for spec in raw.get("prometheus_query_specs", {}).values()
        if spec.get("metric") == "p95_latency_5m" and spec.get("signal_id") not in existing_signal_ids
    )


def build_detectors(
    config: RuntimeConfig,
    settings: Settings | None,
    no_data_hyperparameters: dict[str, float],
    detector_hyperparameters: dict | None = None,
) -> list[Detector]:
    detectors: list[Detector] = []
    detector_hyperparameters = detector_hyperparameters or {}
    thresholds = detector_hyperparameters.get("thresholds") or config.detector_thresholds
    confidences = detector_hyperparameters.get("confidences") or config.detector_confidences
    for item in config.detectors:
        if not item.enabled:
            continue
        if item.type == "threshold":
            threshold = (
                detector_hyperparameters["latency_slo_overrides"].get(item.service, detector_hyperparameters["latency_slo_seconds"])
                if item.id.endswith("_latency_p95")
                else thresholds[item.id]
            )
            detectors.append(
                ThresholdDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=threshold,
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "dependency":
            detectors.append(
                DependencyDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    dependency=item.dependency or "unknown",
                    severity=item.severity,
                    confidence=confidences[item.id],
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "no-data":
            detectors.append(
                NoDataDetector(
                    item.signal_ids,
                    detector_id=item.id,
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                    missing_confidence=no_data_hyperparameters["missing_confidence"],
                    unknown_confidence=no_data_hyperparameters["unknown_confidence"],
                )
            )
    return detectors
