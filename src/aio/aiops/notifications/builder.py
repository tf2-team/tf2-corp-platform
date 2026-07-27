#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import CandidateEvent, Incident, NotificationMessage
from aiops.shared.metrics import is_error_metric


def is_slo_notification(event: CandidateEvent) -> bool:
    return event.reason == "threshold_breached" and (
        "slo" in event.detector_id.lower()
        or "latency" in event.signal_id
        or "burn_rate" in event.signal_id
        or is_error_metric(event.signal_id)
    )


class NotificationBuilder:
    def build(self, incidents: list[Incident]) -> list[NotificationMessage]:
        return [self._build_one(incident) for incident in incidents]

    def _build_one(self, incident: Incident) -> NotificationMessage:
        last_event = incident.events[-1]
        dependency = incident.likely_dependency
        title = f"RCA root cause: {incident.service}" if last_event.detector_id == "rca_root_cause" else f"{incident.flow} incident"
        if last_event.detector_id != "rca_root_cause" and dependency != "unknown":
            title = f"{incident.flow} likely dependency: {dependency}"
        signals = tuple(dict.fromkeys(signal for event in incident.events for signal in (event.contributing_signals or (event.signal_id,))))
        if last_event.detector_id == "rca_root_cause":
            summary = _rca_summary(incident, last_event, signals)
        elif last_event.reason == "threshold_breached":
            summary = _threshold_summary(last_event, signals)
        else:
            summary = f"{last_event.reason} on {', '.join(signals)}"
        return NotificationMessage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            state=incident.state,
            title=title,
            summary=summary,
            flow=incident.flow,
            service=incident.service,
            likely_dependency=dependency,
            runbook_id=last_event.runbook_id,
        )


def _rca_summary(incident: Incident, event: CandidateEvent, signals: tuple[str, ...]) -> str:
    lines = [
        f"Root: {incident.service}",
        f"Metric: {', '.join(signals)}",
        f"RCA score: {event.confidence:.3f}",
    ]
    evidence = _important_evidence(event)
    if evidence:
        lines.append("Evidence:")
        lines.extend(f"- {item}" for item in evidence)
    lines.append(f"Action: {_action_hint(event.runbook_id, ','.join(signals))}")
    lines.append(f"Runbook: {event.runbook_id}")
    return "\n".join(lines)


def _threshold_summary(event: CandidateEvent, signals: tuple[str, ...]) -> str:
    lines = [
        "Detected: threshold_breached",
        f"Signal: {', '.join(signals)}",
        f"Value: {_format_number(event.value)}{_unit_suffix(event.unit)}",
        f"Threshold: {_format_number(event.threshold)}{_unit_suffix(event.unit)}",
        f"Window: {event.window}",
        f"Action: {_action_hint(event.runbook_id, ','.join(signals))}",
        f"Runbook: {event.runbook_id}",
    ]
    return "\n".join(lines)


def _important_evidence(event: CandidateEvent) -> list[str]:
    raw = [item.summary for item in event.evidence if item.summary]
    keep = []
    for marker in ("log_", "trace_", "graph_score", "earliest_drift_score", "downstream_coverage_score", "weighted_rrf_score", "evidence_strength", "support_score"):
        keep.extend(item for item in raw if marker in item and item not in keep)
    return keep[:6]


def _action_hint(runbook_id: str, context: str = "") -> str:
    text = f"{runbook_id} {context}".upper()
    if "RESOURCE" in text or "CPU" in text or "MEMORY" in text or "OOM" in text:
        return "check pod restarts/OOMKilled, resource limits, recent deploy, and traffic context"
    if "LATENCY" in text or "P95" in text or "P99" in text:
        return "check slow dependency spans, saturation, and recent deploy"
    if "ERROR" in text or "BAD_RATIO" in text or "BURN_RATE" in text:
        return "check recent errors, failing traces, and dependency health"
    return "follow runbook and validate with logs/traces before remediation"


def _format_number(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _unit_suffix(unit: str) -> str:
    return f" {unit}" if unit else ""
