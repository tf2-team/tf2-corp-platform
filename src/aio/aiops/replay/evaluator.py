#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Callable

from aiops.schemas import (
    PipelineResult,
    PipelineRunRequest,
    ReplayCaseResult,
    ReplayMetrics,
    ReplayReport,
    ReplayRequest,
)


PipelineRunner = Callable[[PipelineRunRequest], PipelineResult]


def evaluate_replay(request: ReplayRequest, runner: PipelineRunner) -> ReplayReport:
    cases = [_evaluate_case(scenario, runner) for scenario in request.scenarios]
    tp = sum(case.expected_incident and case.detected for case in cases)
    fp = sum(not case.expected_incident and case.detected for case in cases)
    tn = sum(not case.expected_incident and not case.detected for case in cases)
    fn = sum(case.expected_incident and not case.detected for case in cases)
    lead_times = [
        case.lead_time_seconds
        for case in cases
        if case.expected_incident and case.detected and case.lead_time_seconds is not None
    ]
    after = sum(lead_times) / len(lead_times) if lead_times else None
    before = request.baseline_mttd_seconds
    return ReplayReport(
        cases=cases,
        metrics=ReplayMetrics(
            true_positive=tp,
            false_positive=fp,
            true_negative=tn,
            false_negative=fn,
            precision=tp / (tp + fp) if tp + fp else 0.0,
            recall=tp / (tp + fn) if tp + fn else 0.0,
            mean_lead_time_seconds=after,
            mttd_before_seconds=before,
            mttd_after_seconds=after,
            mttd_improvement_seconds=(before - after) if before is not None and after is not None else None,
        ),
    )


def _evaluate_case(scenario, runner: PipelineRunner) -> ReplayCaseResult:
    result = runner(
        PipelineRunRequest(
            observations=scenario.observations,
            metric_series=scenario.metric_series,
        )
    )
    detected = bool(result.incidents)
    timestamps = [
        timestamp
        for timestamp in (
            [event.timestamp for incident in result.incidents for event in incident.events]
            + [finding.timestamp for finding in result.rca_result.anomalies]
        )
        if timestamp > 0
    ]
    detected_at = min(timestamps) if timestamps else None
    lead_time = None
    if scenario.incident_start_timestamp is not None and detected_at is not None:
        lead_time = max(0.0, float(detected_at - scenario.incident_start_timestamp))
    services = {incident.service for incident in result.incidents}
    severities = {incident.severity for incident in result.incidents}
    return ReplayCaseResult(
        scenario_id=scenario.scenario_id,
        expected_incident=scenario.expected_incident,
        detected=detected,
        detection_timestamp=detected_at,
        lead_time_seconds=lead_time,
        service_correct=(scenario.expected_service in services) if scenario.expected_service else None,
        severity_correct=(scenario.expected_severity in severities) if scenario.expected_severity else None,
        incident_ids=[incident.incident_id for incident in result.incidents],
        summaries=[message.summary for message in result.notifications],
        pipeline_result=result,
    )
