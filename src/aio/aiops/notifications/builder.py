#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from aiops.config.hyperparameters import load_hyperparameters
from aiops.schemas import CandidateEvent, Incident, NotificationMessage
from aiops.shared.metrics import is_error_metric

DEFAULT_IMPORTANT_EVIDENCE_MARKERS = (
    "Trace/log enrichment",
    "log_",
    "trace_",
    "graph_score",
    "earliest_drift_score",
    "shape_correlation_score",
    "downstream_coverage_score",
    "weighted_rrf_score",
    "evidence_strength",
    "support_score",
)


def is_slo_notification(event: CandidateEvent) -> bool:
    return event.reason == "threshold_breached" and (
        "slo" in event.detector_id.lower()
        or "latency" in event.signal_id
        or "burn_rate" in event.signal_id
        or is_error_metric(event.signal_id)
    )


class NotificationBuilder:
    def __init__(self, hyperparameters: dict | None = None):
        config = hyperparameters or load_hyperparameters(Path("config/hyperparameters.json")).get("notification", {})
        self.important_evidence_limit = int(config.get("important_evidence_limit", 8))
        self.important_evidence_markers = tuple(config.get("important_evidence_markers", DEFAULT_IMPORTANT_EVIDENCE_MARKERS))

    def build(self, incidents: list[Incident]) -> list[NotificationMessage]:
        return [self._build_one(incident) for incident in incidents]

    def _build_one(self, incident: Incident) -> NotificationMessage:
        last_event = incident.events[-1]
        dependency = incident.likely_dependency
        title = f"RCA root cause: {incident.service}" if last_event.detector_id == "rca_root_cause" else f"{incident.flow} incident"
        if incident.state == "recovered":
            title = f"Recovered: {incident.service}"
        if last_event.detector_id != "rca_root_cause" and dependency != "unknown":
            title = f"{incident.flow} likely dependency: {dependency}"
        signals = tuple(dict.fromkeys(signal for event in incident.events for signal in (event.contributing_signals or (event.signal_id,))))
        return NotificationMessage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            state=incident.state,
            title=title,
            summary=_event_summary(
                incident,
                last_event,
                signals,
                self.important_evidence_limit,
                self.important_evidence_markers,
            ),
            flow=incident.flow,
            service=incident.service,
            likely_dependency=dependency,
            runbook_id=last_event.runbook_id,
        )


def _event_summary(
    incident: Incident,
    event: CandidateEvent,
    signals: tuple[str, ...],
    important_evidence_limit: int,
    important_evidence_markers: tuple[str, ...],
) -> str:
    signal_label = "Metric" if event.detector_id == "rca_root_cause" else "Signal"
    lines = [f"Detected: {event.reason}", f"{signal_label}: {', '.join(signals)}"]
    if event.detector_id == "rca_root_cause":
        lines.insert(0, f"Root: {incident.service}")
        lines.append(f"RCA score: {event.confidence:.3f}")
    if event.value is not None:
        lines.append(f"Value: {_format_number(event.value)}{_unit_suffix(event.unit)}")
    if event.threshold is not None:
        lines.append(f"Threshold: {_format_number(event.threshold)}{_unit_suffix(event.unit)}")
    if event.window:
        lines.append(f"Window: {event.window}")
    if evidence := _important_evidence(event, important_evidence_limit, important_evidence_markers):
        lines.append("Evidence:")
        lines.extend(f"- {item}" for item in evidence)
    lines.append(f"Action: {_action_hint(event.runbook_id, ','.join(signals))}")
    lines.append(f"Runbook: {event.runbook_id}")
    return "\n".join(lines)


def _important_evidence(event: CandidateEvent, limit: int, markers: tuple[str, ...]) -> list[str]:
    raw = [item.summary for item in event.evidence if item.summary]
    keep = []
    for marker in markers:
        keep.extend(item for item in raw if marker in item and item not in keep)
    return keep[:limit]


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
