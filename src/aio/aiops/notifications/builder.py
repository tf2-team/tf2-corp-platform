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
        summary = _rca_summary(incident, last_event, signals) if last_event.detector_id == "rca_root_cause" else f"{last_event.reason} on {', '.join(signals)}"
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
    lines.append(f"Action: {_action_hint(event.runbook_id)}")
    lines.append(f"Runbook: {event.runbook_id}")
    return "\n".join(lines)


def _important_evidence(event: CandidateEvent) -> list[str]:
    raw = [item.summary for item in event.evidence if item.summary]
    keep = []
    for marker in ("log_", "trace_", "graph_score", "earliest_drift_score", "downstream_coverage_score", "weighted_rrf_score", "evidence_strength"):
        keep.extend(item for item in raw if marker in item and item not in keep)
    return keep[:6]


def _action_hint(runbook_id: str) -> str:
    if "RESOURCE" in runbook_id:
        return "check pod restarts/OOMKilled, resource limits, recent deploy, and traffic context"
    if "LATENCY" in runbook_id:
        return "check slow dependency spans, saturation, and recent deploy"
    if "ERROR" in runbook_id:
        return "check recent errors, failing traces, and dependency health"
    return "follow runbook and validate with logs/traces before remediation"
