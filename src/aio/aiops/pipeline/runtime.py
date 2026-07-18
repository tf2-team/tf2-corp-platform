from __future__ import annotations

import logging
from typing import Protocol

from aiops.collectors import Collector
from aiops.correlation import Correlator
from aiops.detectors import Detector, DetectorEngine
from aiops.enrichment import Enricher
from aiops.features import FeatureBuilder
from aiops.anomaly import V001AnomalyEngine
from aiops.rca import V001RcaEngine
from aiops.schemas import MetricSeries, NotificationMessage, PipelineResult, PolicyDecision, RcaResult, RuntimeConfig
from aiops.normalization import Normalizer
from aiops.qualification import QualificationGate
from aiops.remediation import (
    ActionCatalog,
    HistoryRetriever,
    IncidentHistoryStore,
    PolicyEngine,
    RemediationAuditLog,
    RemediationDecisionEngine,
    RemediationFeatureExtractor,
)
from aiops.schemas import CandidateEvent, Incident, RemediationDecision, VerificationResult
from aiops.verification import VerificationEngine


logger = logging.getLogger(__name__)

RemediationComponents = tuple[
    RemediationFeatureExtractor,
    HistoryRetriever,
    RemediationDecisionEngine,
    ActionCatalog,
    IncidentHistoryStore,
    RemediationAuditLog,
]


class IncidentStore(Protocol):
    def upsert(self, candidate: CandidateEvent) -> Incident:
        ...

    def pending_notifications_for(self, incidents: list[Incident]) -> list[NotificationMessage]:
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
        qualification_schema: dict | None = None,
        normalization_schema: dict | None = None,
        qualification_dev: bool = False,
        qualification_max_sample_age_seconds: int = 300,
        correlation_hyperparameters: dict | None = None,
        remediation: RemediationComponents | None = None,
        enricher: Enricher | None = None,
    ):
        self.collector = collector
        self.qualification = QualificationGate(
            runtime_config,
            qualification_schema,
            dev=qualification_dev,
            max_sample_age_seconds=qualification_max_sample_age_seconds,
        )
        self.normalizer = Normalizer(normalization_schema)
        self.feature_builder = FeatureBuilder(runtime_config)
        self.detector_engine = DetectorEngine(detectors)
        self.correlator = Correlator(runtime_config, **correlation_hyperparameters) if correlation_hyperparameters else Correlator(runtime_config)
        self.enricher = enricher or Enricher(runtime_config=runtime_config)
        self.store = store
        self.policy = policy
        self.verification = VerificationEngine()
        self.runtime_config = runtime_config
        self.rca_hyperparameters = rca_hyperparameters or {}
        self.remediation = remediation

    def run_once(self, metric_series: list[MetricSeries] | None = None) -> PipelineResult:
        logger.info("AIOPS_BLOCK start metric_series=%s", len(metric_series or []))
        collected = self.collector.collect()
        logger.info("AIOPS_BLOCK collect observations=%s", len(collected))
        observations = self.qualification.evaluate(self.normalizer.normalize(collected))
        logger.info(
            "AIOPS_BLOCK qualify observations=%s quality_counts=%s",
            len(observations),
            _counts(observation.quality.value for observation in observations),
        )
        features = self.feature_builder.build(observations)
        logger.info(
            "AIOPS_BLOCK feature features=%s status_counts=%s",
            len(features),
            _counts(feature.status for feature in features),
        )
        candidates = self.detector_engine.evaluate(features)
        logger.info("AIOPS_BLOCK detect candidates=%s ids=%s", len(candidates), [candidate.detector_id for candidate in candidates])
        correlated = self.correlator.correlate(candidates)
        logger.info("AIOPS_BLOCK correlate candidates=%s ids=%s", len(correlated), [candidate.detector_id for candidate in correlated])
        enriched = self.enricher.enrich(correlated, features)
        logger.info("AIOPS_BLOCK enrich candidates=%s evidence=%s", len(enriched), [len(candidate.evidence) for candidate in enriched])
        incidents = [self.store.upsert(candidate) for candidate in enriched]
        logger.info("AIOPS_BLOCK incident incidents=%s ids=%s", len(incidents), [incident.incident_id for incident in incidents])
        notifications = self.store.pending_notifications_for(incidents)
        logger.info("AIOPS_BLOCK notify notifications=%s", len(notifications))

        decisions: list[PolicyDecision] = []
        for incident in incidents:
            proposal = self.policy.proposal_for(incident)
            if proposal is not None:
                decisions.append(self.policy.evaluate(proposal))
        logger.info("AIOPS_BLOCK policy decisions=%s results=%s", len(decisions), [decision.result for decision in decisions])
        verification_results = self.verification.verify(incidents, features)
        logger.info("AIOPS_BLOCK verify results=%s statuses=%s", len(verification_results), [result.status for result in verification_results])
        rca_result = self._run_v001_rca(metric_series or [])
        logger.info(
            "AIOPS_BLOCK rca anomalies=%s root_causes=%s",
            len(rca_result.anomalies),
            [root.service for root in rca_result.root_causes],
        )
        remediation_decisions = self._run_remediation_strategy(incidents, rca_result)
        logger.info(
            "AIOPS_BLOCK remediation decisions=%s selected=%s",
            len(remediation_decisions),
            [decision.selected_action for decision in remediation_decisions],
        )
        self._record_verified_history(incidents, verification_results, remediation_decisions, rca_result)

        return PipelineResult(
            observations=observations,
            features=features,
            candidates=enriched,
            incidents=incidents,
            notifications=notifications,
            policy_decisions=decisions,
            remediation_decisions=remediation_decisions,
            verification_results=verification_results,
            rca_result=rca_result,
        )

    def _run_v001_rca(self, metric_series: list[MetricSeries]) -> RcaResult:
        if self.runtime_config is None or not self.rca_hyperparameters.get("enabled", self.runtime_config.rca.enabled) or not metric_series:
            logger.info("AIOPS_BLOCK rca skipped enabled=%s metric_series=%s", self.rca_hyperparameters.get("enabled", None), len(metric_series))
            return RcaResult()
        config = self.rca_hyperparameters
        findings = V001AnomalyEngine(
            ewma_alpha=float(config["ewma_alpha"]),
            ewma_z_threshold=float(config["ewma_z_threshold"]),
            isolation_score_threshold=float(config["isolation_score_threshold"]),
            min_points=int(config["min_points"]),
            seasonal_period=int(config["seasonal_period"]),
            algorithm_weights=config["anomaly"]["algorithm_weights"],
            weighted_score_threshold=float(config["anomaly"]["weighted_score_threshold"]),
            bocpd_min_changed_metrics=int(config["anomaly"]["bocpd_min_changed_metrics"]),
        ).evaluate(metric_series)
        return V001RcaEngine(self.runtime_config, config["graph"]).rank(findings, metric_series, top_k=int(config["top_k"]))

    def _run_remediation_strategy(self, incidents: list[Incident], rca_result: RcaResult) -> list[RemediationDecision]:
        if self.remediation is None:
            return []
        extractor, retriever, decider, catalog, history, audit = self.remediation
        records = history.load()
        actions = catalog.load()
        decisions = []
        for incident in incidents:
            features = extractor.extract(incident, rca_result)
            decision = decider.decide(incident.incident_id, features, retriever.top_matches(features, records), actions)
            logger.info(
                "AIOPS_BLOCK remediation_decide incident=%s action=%s decision=%s reasons=%s",
                incident.incident_id,
                decision.selected_action,
                decision.decision,
                decision.reasons,
            )
            audit.append(decision)
            decisions.append(decision)
        return decisions

    def _record_verified_history(
        self,
        incidents: list[Incident],
        verification_results: list[VerificationResult],
        remediation_decisions: list[RemediationDecision],
        rca_result: RcaResult,
    ) -> None:
        if self.remediation is None:
            return
        extractor, _, _, _, history, _ = self.remediation
        recovered = {result.incident_id for result in verification_results if result.status == "recovered"}
        for incident in incidents:
            if incident.incident_id not in recovered:
                continue
            related_decisions = [decision for decision in remediation_decisions if decision.incident_id == incident.incident_id]
            logger.info("AIOPS_BLOCK history_append incident=%s decisions=%s", incident.incident_id, [decision.selected_action for decision in related_decisions])
            history.append_success(incident, extractor.extract(incident, rca_result), related_decisions)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
