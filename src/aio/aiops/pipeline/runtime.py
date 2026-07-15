from __future__ import annotations

from typing import Protocol

from aiops.collectors import Collector
from aiops.correlation import Correlator
from aiops.detectors import Detector, DetectorEngine
from aiops.enrichment import Enricher
from aiops.features import FeatureBuilder
from aiops.anomaly import V001AnomalyEngine
from aiops.rca import V001RcaEngine
from aiops.schemas import MetricSeries, PipelineResult, PolicyDecision, RcaResult, RuntimeConfig
from aiops.normalization import Normalizer
from aiops.notifications import NotificationBuilder
from aiops.qualification import QualificationGate
from aiops.remediation import PolicyEngine
from aiops.schemas import CandidateEvent, Incident
from aiops.verification import VerificationEngine


class IncidentStore(Protocol):
    def upsert(self, candidate: CandidateEvent) -> Incident:
        ...


class AiopsPipeline:
    def __init__(
        self,
        collector: Collector,
        detectors: list[Detector],
        store: IncidentStore,
        policy: PolicyEngine,
        runtime_config: RuntimeConfig | None = None,
        rca_hyperparameters: dict[str, float | int | bool] | None = None,
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
        self.runtime_config = runtime_config
        self.rca_hyperparameters = rca_hyperparameters or {}

    def run_once(self, metric_series: list[MetricSeries] | None = None) -> PipelineResult:
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
        rca_result = self._run_v001_rca(metric_series or [])

        return PipelineResult(
            observations=observations,
            features=features,
            candidates=enriched,
            incidents=incidents,
            notifications=notifications,
            policy_decisions=decisions,
            verification_results=verification_results,
            rca_result=rca_result,
        )

    def _run_v001_rca(self, metric_series: list[MetricSeries]) -> RcaResult:
        if self.runtime_config is None or not self.rca_hyperparameters.get("enabled", self.runtime_config.rca.enabled) or not metric_series:
            return RcaResult()
        config = self.rca_hyperparameters
        findings = V001AnomalyEngine(
            ewma_alpha=float(config["ewma_alpha"]),
            ewma_z_threshold=float(config["ewma_z_threshold"]),
            isolation_score_threshold=float(config["isolation_score_threshold"]),
            bocpd_score_threshold=float(config["bocpd_score_threshold"]),
            min_points=int(config["min_points"]),
            seasonal_period=int(config["seasonal_period"]),
        ).evaluate(metric_series)
        return V001RcaEngine(self.runtime_config, fallback_split_ratio=float(config["fallback_split_ratio"])).rank(
            findings, metric_series, top_k=int(config["top_k"])
        )
