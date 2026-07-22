#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import ast
import json
import logging
import re
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from aiops.collectors import Collector
from aiops.correlation import Correlator
from aiops.detectors import Detector, DetectorEngine
from aiops.enrichment import Enricher
from aiops.features import FeatureBuilder
from aiops.anomaly import build_v001_anomaly_engine
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricSeries, NotificationMessage, PipelineResult, PolicyDecision, RcaResult, RuntimeConfig
from aiops.normalization import Normalizer
from aiops.notifications import NotificationBuilder
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
from aiops.shared.series import prepare_detector_series
from aiops.verification import VerificationEngine
from aiops.pipeline.analysis import (
    apply_corroboration as _apply_corroboration,
    blast_radius_services as _blast_radius_services,
    slo_impact_findings as _slo_impact_findings,
)


logger = logging.getLogger(__name__)
_RUN_COUNTER = count(1)

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

    def pending_notifications_for(self, incidents: list[Incident]) -> list[NotificationMessage]: ...

    def due_notifications(self, limit: int = 100) -> list[NotificationMessage]: ...

    def mark_notification_sent(self, incident_id: str) -> None: ...

    def mark_notification_failed(self, incident_id: str, error: str) -> None: ...


class NotificationSender(Protocol):
    def send(self, message: NotificationMessage) -> dict:
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
        notification_sender: NotificationSender | None = None,
        rca_history_path: Path | None = None,
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
        self.correlation_hyperparameters = correlation_hyperparameters or {}
        self.remediation = remediation
        self.notification_sender = notification_sender
        self.rca_history_path = rca_history_path

    def run_once(self, metric_series: list[MetricSeries] | None = None) -> PipelineResult:
        run_number = next(_RUN_COUNTER)
        logger.info("---------- AIOPS_RUN_START run=%s ----------", run_number)
        logger.debug("AIOPS_BLOCK start metric_series=%s", len(metric_series or []))
        collected = self.collector.collect()
        logger.debug("AIOPS_BLOCK collect observations=%s", len(collected))
        observations = self.qualification.evaluate(self.normalizer.normalize(collected))
        logger.debug(
            "AIOPS_BLOCK qualify observations=%s quality_counts=%s",
            len(observations),
            _counts(observation.quality.value for observation in observations),
        )
        features = self.feature_builder.build(observations)
        logger.debug(
            "AIOPS_BLOCK feature features=%s status_counts=%s",
            len(features),
            _counts(feature.status for feature in features),
        )
        candidates = self.detector_engine.evaluate(features)
        (logger.info if candidates else logger.debug)("AIOPS_BLOCK detect candidates=%s ids=%s", len(candidates), [candidate.detector_id for candidate in candidates])
        correlated = self.correlator.correlate(candidates)
        logger.debug("AIOPS_BLOCK correlate candidates=%s ids=%s", len(correlated), [candidate.detector_id for candidate in correlated])
        enriched = self.enricher.enrich(correlated, features)
        logger.debug("AIOPS_BLOCK enrich candidates=%s evidence=%s", len(enriched), [len(candidate.evidence) for candidate in enriched])
        slo_candidates = [candidate for candidate in enriched if _is_slo_candidate(candidate)]
        persisted_candidates = [candidate for candidate in enriched if not _is_slo_candidate(candidate)]
        slo_incidents = [_transient_slo_incident(candidate) for candidate in slo_candidates]
        direct_notifications = self._dispatch_slo_notifications(slo_incidents)
        incidents = [self.store.upsert(candidate) for candidate in persisted_candidates]
        analysis_incidents = [*incidents, *slo_incidents]
        deduped_incidents = _unique_incidents(incidents)
        logger.debug("AIOPS_BLOCK incident persisted=%s transient_slo=%s ids=%s", len(incidents), len(slo_incidents), [incident.incident_id for incident in analysis_incidents])

        rca_result = self._run_v001_rca(metric_series or [], analysis_incidents)
        logger.info(
            "AIOPS_DEDUP_RESULT input_candidates=%s incidents=%s ids=%s services=%s occurrences=%s",
            len(enriched),
            len(deduped_incidents),
            [incident.incident_id for incident in deduped_incidents],
            [incident.service for incident in deduped_incidents],
            [incident.occurrence_count for incident in deduped_incidents],
        )
        verification_results = self.verification.verify(analysis_incidents, features)
        logger.debug("AIOPS_BLOCK verify results=%s statuses=%s", len(verification_results), [result.status for result in verification_results])
        logger.info(
            "AIOPS_BLOCK rca anomalies=%s root_causes=%s",
            len(rca_result.anomalies),
            [root.service for root in rca_result.root_causes],
        )
        self._log_failure_conclusion(rca_result, analysis_incidents)
        suppressed_incident_ids = self._suppress_related_notifications(deduped_incidents, rca_result)
        actionable_incidents = [incident for incident in incidents if incident.incident_id not in suppressed_incident_ids]
        self._record_rca_history(rca_result, incidents, enriched, metric_series or [])
        notifications = [*direct_notifications, *self._flush_notifications(incidents)]
        logger.debug("AIOPS_BLOCK notify notifications=%s", len(notifications))
        decisions: list[PolicyDecision] = []
        for incident in actionable_incidents:
            proposal = self.policy.proposal_for(incident)
            if proposal is not None:
                decisions.append(self.policy.evaluate(proposal))
        logger.debug("AIOPS_BLOCK policy decisions=%s results=%s suppressed=%s", len(decisions), [decision.result for decision in decisions], len(suppressed_incident_ids))
        remediation_decisions = self._run_remediation_strategy(actionable_incidents, rca_result)
        logger.debug(
            "AIOPS_BLOCK remediation decisions=%s selected=%s",
            len(remediation_decisions),
            [decision.selected_action for decision in remediation_decisions],
        )
        self._record_verified_history(incidents, verification_results, remediation_decisions, rca_result)

        result = PipelineResult(
            observations=observations,
            features=features,
            candidates=enriched,
            incidents=analysis_incidents,
            notifications=notifications,
            policy_decisions=decisions,
            remediation_decisions=remediation_decisions,
            verification_results=verification_results,
            rca_result=rca_result,
        )
        logger.info(
            "---------- AIOPS_RUN_END run=%s candidates=%s incidents=%s root_causes=%s ----------",
            run_number,
            len(enriched),
            len(deduped_incidents),
            len(rca_result.root_causes),
        )
        return result

    def _dispatch_slo_notifications(self, incidents: list[Incident]) -> list[NotificationMessage]:
        notifications = NotificationBuilder().build(incidents)
        for message in notifications:
            logger.info(
                "AIOPS_SLO_NOTIFY_DIRECT incident=%s service=%s severity=%s runbook=%s",
                message.incident_id,
                message.service,
                message.severity,
                message.runbook_id,
            )
            if self.notification_sender is None:
                continue
            try:
                self.notification_sender.send(message)
            except Exception as exc:
                logger.warning("AIOPS_SLO_NOTIFY_FAILED incident=%s error=%s", message.incident_id, exc)
        return notifications

    def _flush_notifications(self, incidents: list[Incident]) -> list[NotificationMessage]:
        if self.notification_sender is None:
            notifications = self.store.pending_notifications_for(incidents)
            for message in notifications:
                logger.info(
                    "AIOPS_NOTIFY_READY incident=%s service=%s severity=%s runbook=%s route=outbox status=pending",
                    message.incident_id,
                    message.service,
                    message.severity,
                    message.runbook_id,
                )
            return notifications

        notifications = self.store.due_notifications()
        for message in notifications:
            logger.info(
                "AIOPS_NOTIFY_READY incident=%s service=%s severity=%s runbook=%s route=outbox status=dispatching",
                message.incident_id,
                message.service,
                message.severity,
                message.runbook_id,
            )
            try:
                self.notification_sender.send(message)
            except Exception as exc:
                logger.warning("AIOPS_BLOCK notify_failed incident=%s error=%s", message.incident_id, exc)
                self.store.mark_notification_failed(message.incident_id, str(exc))
            else:
                self.store.mark_notification_sent(message.incident_id)
                logger.info(
                    "AIOPS_NOTIFY_SENT incident=%s service=%s severity=%s runbook=%s",
                    message.incident_id,
                    message.service,
                    message.severity,
                    message.runbook_id,
                )
        return notifications

    def _run_v001_rca(self, metric_series: list[MetricSeries], incidents: list[Incident] | None = None) -> RcaResult:
        log_messages = self._log_messages(incidents or [])
        detector_series = prepare_detector_series(metric_series)
        impact_findings = _slo_impact_findings(incidents or [])
        if self.runtime_config is None or not self.rca_hyperparameters or not self.rca_hyperparameters.get("enabled", self.runtime_config.rca.enabled) or (not detector_series and not log_messages and not impact_findings):
            logger.info(
                "AIOPS_BLOCK rca skipped enabled=%s metric_series=%s log_messages=%s",
                self.rca_hyperparameters.get("enabled", None),
                len(metric_series),
                len(log_messages),
            )
            return RcaResult()
        config = self.rca_hyperparameters
        anomaly_engine = build_v001_anomaly_engine(config)
        findings = anomaly_engine.evaluate(detector_series, logs=log_messages) if log_messages else anomaly_engine.evaluate(detector_series)
        anomaly_config = config["anomaly"]
        corroboration = self.enricher.corroborate(impact_findings + findings, int(anomaly_config["evidence_window_seconds"]))
        findings = impact_findings + _apply_corroboration(
            findings,
            detector_series,
            corroboration,
            float(anomaly_config["no_evidence_multiplier"]),
            float(anomaly_config["single_evidence_bonus"]),
            float(anomaly_config["dual_evidence_bonus"]),
        )
        rca_engine = V001RcaEngine(self.runtime_config, config["graph"], _combined_rca_hyperparameters(config))
        result = rca_engine.rank(findings, detector_series, top_k=int(config["top_k"]), corroboration=corroboration)
        _log_final_root_cause_algorithm_scores(result, getattr(anomaly_engine, "last_algorithm_findings", findings))
        return result

    def _record_rca_history(
        self,
        rca_result: RcaResult,
        incidents: list[Incident],
        candidates: list[CandidateEvent],
        metric_series: list[MetricSeries],
    ) -> None:
        if self.rca_history_path is None or (not rca_result.root_causes and not rca_result.anomalies):
            return
        point_counts = [len(series.points) for series in metric_series]
        incident_rows = [
            {
                "incident_id": incident.incident_id,
                "service": incident.service,
                "severity": incident.severity,
                "occurrence_count": incident.occurrence_count,
                "detectors": [event.detector_id for event in incident.events],
            }
            for incident in _unique_incidents(incidents)
        ]
        payload = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "detectors": [candidate.detector_id for candidate in candidates],
            "incidents": incident_rows,
            "parameters": self.rca_hyperparameters,
            "series_point_count": {
                "min": min(point_counts) if point_counts else 0,
                "max": max(point_counts) if point_counts else 0,
                "total": sum(point_counts),
            },
            "metric_series_count": len(metric_series),
            "root_causes": [root.model_dump(mode="json") for root in rca_result.root_causes],
            "anomalies": [anomaly.model_dump(mode="json") for anomaly in rca_result.anomalies],
        }
        self.rca_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.rca_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        logger.info(
            "AIOPS_RCA_HISTORY path=%s root_causes=%s anomalies=%s",
            self.rca_history_path,
            len(rca_result.root_causes),
            len(rca_result.anomalies),
        )

    def _log_failure_conclusion(self, rca_result: RcaResult, incidents: list[Incident]) -> None:
        if rca_result.root_causes:
            root = rca_result.root_causes[0]
            logger.info(
                "AIOPS_CONCLUSION source=rca failed_service=%s score=%.3f metrics=%s",
                root.service,
                root.score,
                ",".join(root.root_cause_metrics),
            )
            return
        if incidents:
            logger.info(
                "AIOPS_CONCLUSION source=incident failed_service=%s score=none metrics=none",
                ",".join(dict.fromkeys(incident.service for incident in incidents)),
            )

    def _log_messages(self, incidents: list[Incident]) -> list[tuple[str, int, str]]:
        messages = []
        max_events = int(self.rca_hyperparameters.get("anomaly", {}).get("log_max_events_per_evidence", 100))
        for incident in incidents:
            for event in incident.events:
                service = incident.likely_dependency if incident.likely_dependency != "unknown" else event.likely_dependency
                if service == "unknown":
                    service = event.service
                for item in event.evidence:
                    if item.source != "log":
                        continue
                    for text in _log_excerpts(item.summary, max_events):
                        messages.append((service, event.timestamp, text))
        return messages

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

    def _suppress_related_notifications(self, incidents: list[Incident], rca_result: RcaResult) -> set[str]:
        suppressed = set()
        current_root_service = None
        if self.runtime_config is not None and rca_result.root_causes:
            root = rca_result.root_causes[0]
            if root.score >= float(self.correlation_hyperparameters.get("suppress_min_root_score", 0.8)):
                root_service = root.service
                current_root_service = root_service
                affected_services = _blast_radius_services(
                    self.runtime_config,
                    root_service,
                    int(self.correlation_hyperparameters.get("topology_max_hops", 2)),
                )
                affected_services -= {incident.service for incident in incidents if incident.severity == "SEV1"}
                register = getattr(self.store, "register_active_root_cause", None)
                suppress = getattr(self.store, "suppress_related_notifications", None)
                if register is not None:
                    register(root_service, affected_services, int(self.correlation_hyperparameters.get("suppress_window_seconds", 900)))
                if suppress is not None:
                    suppressed.update(suppress(incidents, root_service, affected_services) or set())
        active_suppress = getattr(self.store, "suppress_active_root_notifications", None)
        if active_suppress is not None:
            exempt_services = {current_root_service} if current_root_service else set()
            remaining = [incident for incident in incidents if incident.incident_id not in suppressed]
            suppressed.update(active_suppress(remaining, exempt_services) or set())
        active_suppressed = getattr(self.store, "suppressed_incident_ids", None)
        if active_suppressed is not None and active_suppress is None:
            suppressed.update(active_suppressed(incidents))
        return suppressed

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


def _log_final_root_cause_algorithm_scores(result: RcaResult, findings: list[AnomalyFinding]) -> None:
    if not result.root_causes:
        return
    root = result.root_causes[0]
    metrics = set(root.root_cause_metrics)
    scores = {
        finding.algorithm: finding.score
        for finding in findings
        if finding.service == root.service and finding.metric in metrics
    }
    logger.info(
        "AIOPS_RCA_FINAL_ALGORITHM_SCORES service=%s metrics=%s ewma_stl=%s isolation_forest=%s",
        root.service,
        root.root_cause_metrics,
        _score(scores.get("ewma_stl")),
        _score(scores.get("isolation_forest")),
    )


def _combined_rca_hyperparameters(config: dict) -> dict:
    anomaly = config["anomaly"]
    return {
        **config["combined"],
        "min_tail_anomaly_buckets": anomaly["min_tail_anomaly_buckets"],
        "min_relative_change_ratio": anomaly["min_relative_change_ratio"],
        "min_absolute_change": anomaly["min_absolute_change"],
        "correlation_lag_buckets": anomaly["correlation_lag_buckets"],
    }


def _score(value: float | None) -> str:
    return "NA" if value is None else f"{value:.3f}"


def _log_excerpts(summary: str, max_events: int = 100) -> list[str]:
    marker = "excerpts="
    if marker not in summary:
        return [summary]
    try:
        excerpts = ast.literal_eval(summary.split(marker, 1)[1])
    except (SyntaxError, ValueError):
        return [summary]
    if not isinstance(excerpts, list):
        return [summary]
    texts = [str(excerpt) for excerpt in excerpts if excerpt]
    count = _log_count(summary)
    if not texts or count <= len(texts):
        return texts
    return texts + [texts[0]] * (min(count, max_events) - len(texts))


def _log_count(summary: str) -> int:
    match = re.search(r"\bcount=(\d+)", summary)
    return int(match.group(1)) if match else 0


def _unique_incidents(incidents: list[Incident]) -> list[Incident]:
    return list({incident.incident_id: incident for incident in incidents}.values())


def _is_slo_candidate(candidate: CandidateEvent) -> bool:
    return candidate.reason == "threshold_breached" and any(
        marker in candidate.signal_id for marker in ("latency", "error_rate", "error_ratio")
    )


def _transient_slo_incident(candidate: CandidateEvent) -> Incident:
    token = uuid4().hex
    return Incident(
        incident_id=f"slo-{token[:12]}",
        fingerprint=f"slo-direct:{token}",
        state="open",
        severity=candidate.severity,
        flow=candidate.flow,
        service=candidate.service,
        likely_dependency=candidate.likely_dependency,
        events=[candidate],
    )
