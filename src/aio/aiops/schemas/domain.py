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
    labels: dict[str, str] = Field(default_factory=dict)


class EvidenceItem(AiopsModel):
    source: str
    reference: str
    summary: str


class CandidateEvent(AiopsModel):
    detector_id: str
    flow: str
    service: str
    severity: str
    signal_id: str
    value: float | None
    threshold: float | None
    quality: SignalQuality
    reason: str
    runbook_id: str
    likely_dependency: str = "unknown"
    confidence: float = 0.0
    contributing_signals: tuple[str, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()


class Incident(AiopsModel):
    incident_id: str
    fingerprint: str
    state: str
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
    verification_results: list[VerificationResult]
