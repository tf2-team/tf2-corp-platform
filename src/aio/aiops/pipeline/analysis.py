#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from statistics import median

from aiops.schemas import AnomalyFinding, Incident, MetricSeries, RuntimeConfig, TelemetryCorroboration


def apply_corroboration(
    findings: list[AnomalyFinding],
    series: list[MetricSeries],
    corroboration: dict[str, TelemetryCorroboration],
    no_evidence_multiplier: float,
    single_evidence_bonus: float,
    dual_evidence_bonus: float,
) -> list[AnomalyFinding]:
    adjusted = []
    for finding in findings:
        evidence = corroboration.get(finding.service)
        if hard_failure(finding, series) or evidence is None or not evidence.available_sources:
            adjusted.append(finding)
            continue
        sources = int(evidence.log_failure) + int(evidence.trace_failure)
        score = min(1.0, finding.score + (dual_evidence_bonus if sources == 2 else single_evidence_bonus)) if sources else finding.score * no_evidence_multiplier
        adjusted.append(finding.model_copy(update={"score": score}))
    return adjusted


def hard_failure(finding: AnomalyFinding, series: list[MetricSeries]) -> bool:
    if "error_rate" in finding.metric or "error_ratio" in finding.metric or "oom" in finding.metric:
        return True
    if "ready_pods" not in finding.metric:
        return False
    metric = next((item for item in series if item.signal_id == finding.signal_id), None)
    if metric is None:
        return False
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= finding.timestamp), len(metric.points) - 1)
    return index >= 4 and metric.points[index].value < median(point.value for point in metric.points[:index])


def slo_impact_findings(incidents: list[Incident]) -> list[AnomalyFinding]:
    events = {
        (event.service, event.signal_id): event
        for incident in incidents
        for event in incident.events
        if event.reason == "threshold_breached" and any(marker in event.signal_id for marker in ("latency", "error_rate", "error_ratio"))
    }
    return [
        AnomalyFinding(
            algorithm="slo_threshold",
            service=event.service,
            metric=event.signal_id.removeprefix(f"{event.service.replace('-', '_')}_"),
            signal_id=event.signal_id,
            score=1.0,
            timestamp=event.timestamp,
        )
        for event in events.values()
    ]


def blast_radius_services(config: RuntimeConfig, root_service: str, max_hops: int = 2) -> set[str]:
    services = {service.name: service for service in config.topology.services}
    if root_service not in services:
        return {root_service}
    graph = {name: set(service.dependencies) for name, service in services.items()}
    for service in services.values():
        for dependency in service.dependencies:
            graph.setdefault(dependency, set()).add(service.name)
    seen = {root_service}
    frontier = {root_service}
    for _ in range(max_hops):
        frontier = {neighbor for service in frontier for neighbor in graph.get(service, set()) if neighbor not in seen}
        seen.update(frontier)
        if not frontier:
            break
    return seen


def dependency_path_contains(config: RuntimeConfig, source: str, target: str) -> bool:
    graph = {service.name: service.dependencies for service in config.topology.services}
    pending = [source]
    seen = set()
    while pending:
        service = pending.pop()
        if service == target:
            return True
        if service not in seen:
            seen.add(service)
            pending.extend(graph.get(service, []))
    return False
