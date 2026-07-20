#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from aiops.schemas.base import AiopsModel


class SignalQuality(StrEnum):
    UNQUALIFIED = "unqualified"
    VERIFIED = "verified"
    FALLBACK_ONLY = "fallback-only"
    MISSING = "missing"
    STALE = "stale"
    INVALID = "invalid"


class Observation(AiopsModel):
    signal_id: str
    value: float | None
    unit: str
    window: str
    quality: SignalQuality
    labels: dict[str, str] = Field(default_factory=dict)


class Feature(AiopsModel):
    signal_id: str
    value: float | None
    unit: str
    window: str
    quality: SignalQuality
    status: str
    feature_role: str = "unknown"
    labels: dict[str, str] = Field(default_factory=dict)


class MetricPoint(AiopsModel):
    timestamp: int
    value: float


class MetricSeries(AiopsModel):
    service: str
    metric: str
    signal_id: str
    points: list[MetricPoint]


class AnomalyFinding(AiopsModel):
    algorithm: str
    service: str
    metric: str
    signal_id: str
    score: float
    timestamp: int


class RootCauseCandidate(AiopsModel):
    service: str
    score: float
    root_cause_metrics: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class RcaResult(AiopsModel):
    anomalies: list[AnomalyFinding] = Field(default_factory=list)
    root_causes: list[RootCauseCandidate] = Field(default_factory=list)


class IncidentFeatures(AiopsModel):
    affected_services: set[str] = Field(default_factory=set)
    log_signatures: set[str] = Field(default_factory=set)
    trace_signatures: set[str] = Field(default_factory=set)
    metric_ratios: dict[str, float] = Field(default_factory=dict)


class HistoryAction(AiopsModel):
    action_id: str
    target: str
    outcome: str


class IncidentHistoryRecord(AiopsModel):
    incident_id: str
    affected_services: set[str] = Field(default_factory=set)
    log_signatures: set[str] = Field(default_factory=set)
    trace_signatures: set[str] = Field(default_factory=set)
    metric_ratios: dict[str, float] = Field(default_factory=dict)
    actions_taken: list[HistoryAction] = Field(default_factory=list)


class ActionCatalogItem(AiopsModel):
    action_id: str
    action_type: str
    target: str
    target_kind: str
    cost_min: float
    downtime_min: float
    blast_radius_services: list[str] = Field(default_factory=list)
    replicas: int = 3


class RemediationDecision(AiopsModel):
    incident_id: str
    selected_action: str
    target: str
    confidence: float
    expected_cost: float
    decision: str
    fallback: bool
    reasons: list[str] = Field(default_factory=list)
    matched_history: list[str] = Field(default_factory=list)


class EvidenceItem(AiopsModel):
    source: str
    reference: str
    summary: str


class CandidateEvent(AiopsModel):
    environment: str = "unknown"
    timestamp: int = 0
    detector_id: str
    flow: str
    service: str
    severity: str
    signal_id: str
    value: float | None
    unit: str
    window: str
    threshold: float | None
    quality: SignalQuality
    reason: str
    runbook_id: str
    likely_dependency: str = "unknown"
    confidence: float = 0.0
    contributing_signals: tuple[str, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict)
    correlation_components: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[EvidenceItem, ...] = ()


class Incident(AiopsModel):
    incident_id: str
    fingerprint: str
    state: str
    last_seen: str | None = None
    recovered_at: str | None = None
    cooldown_until: str | None = None
    severity: str
    flow: str
    service: str
    likely_dependency: str
    occurrence_count: int = 1
    events: list[CandidateEvent] = Field(default_factory=list)


class NotificationMessage(AiopsModel):
    incident_id: str
    severity: str
    state: str
    title: str
    summary: str
    flow: str
    service: str
    likely_dependency: str
    runbook_id: str


class ActionProposal(AiopsModel):
    action_type: str
    target: str
    target_kind: str
    replicas: int
    mutating: bool
    verification_defined: bool
    rollback_defined: bool
    cost_changing: bool = False
    cost_status_current: bool = True
    approved: bool = False


class PolicyDecision(AiopsModel):
    allowed: bool
    result: str
    reasons: tuple[str, ...] = ()
    executed: bool = False


class VerificationResult(AiopsModel):
    incident_id: str
    status: str
    reason: str


class PipelineResult(AiopsModel):
    observations: list[Observation]
    features: list[Feature]
    candidates: list[CandidateEvent]
    incidents: list[Incident]
    notifications: list[NotificationMessage]
    policy_decisions: list[PolicyDecision]
    remediation_decisions: list[RemediationDecision] = Field(default_factory=list)
    verification_results: list[VerificationResult]
    rca_result: RcaResult = Field(default_factory=RcaResult)
