from __future__ import annotations

from typing import Protocol

from aiops.collectors import Collector
from aiops.correlation import Correlator
from aiops.detectors import Detector, DetectorEngine
from aiops.enrichment import Enricher
from aiops.features import FeatureBuilder
from aiops.schemas import PipelineResult, PolicyDecision
from aiops.normalization import Normalizer
from aiops.notifications import NotificationBuilder
from aiops.qualification import QualificationGate
from aiops.remediation import PolicyEngine
from aiops.schemas import CandidateEvent, Incident
from aiops.verification import VerificationEngine


class IncidentStore(Protocol):
    def upsert(self, candidate: CandidateEvent) -> Incident: ...


class AiopsPipeline:
    def __init__(
        self,
        collector: Collector,
        detectors: list[Detector],
        store: IncidentStore,
        policy: PolicyEngine,
    ):
        self.collector = collector
        self.qualification = QualificationGate()
        self.normalizer = Normalizer()
        self.feature_builder = FeatureBuilder()
        self.detector_engine = DetectorEngine(detectors)
        self.correlator = Correlator()
        self.enricher = Enricher()
        self.store = store
        self.notifier = NotificationBuilder()
        self.policy = policy
        self.verification = VerificationEngine()

    def run_once(self) -> PipelineResult:
        observations = self.collector.collect()
        qualified = self.qualification.evaluate(observations)
        normalized = self.normalizer.normalize(qualified)
        features = self.feature_builder.build(normalized)
        candidates = self.detector_engine.evaluate(features)
        correlated = self.correlator.correlate(candidates)
        enriched = self.enricher.enrich(correlated, features)
        incidents = [self.store.upsert(candidate) for candidate in enriched]
        notifications = self.notifier.build(incidents)

        decisions: list[PolicyDecision] = []
        for incident in incidents:
            proposal = self.policy.proposal_for(incident)
            if proposal is not None:
                decisions.append(self.policy.evaluate(proposal))
        verification_results = self.verification.verify(incidents, features)

        return PipelineResult(
            observations=observations,
            features=features,
            candidates=enriched,
            incidents=incidents,
            notifications=notifications,
            policy_decisions=decisions,
            verification_results=verification_results,
        )
