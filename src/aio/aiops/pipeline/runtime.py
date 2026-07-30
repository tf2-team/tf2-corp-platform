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

from aiops.collectors import Collector
from aiops.correlation import Correlator
from aiops.detectors import Detector, DetectorEngine
from aiops.enrichment import Enricher
from aiops.features import FeatureBuilder
from aiops.anomaly import build_v001_anomaly_engine
from aiops.rca import V001RcaEngine, is_root_cause_metric
from aiops.schemas import AnomalyFinding, EvidenceItem, MetricSeries, NotificationMessage, PipelineResult, PolicyDecision, RcaResult, RootCauseCandidate, RuntimeConfig, SignalQuality, TelemetryCorroboration
from aiops.normalization import Normalizer
from aiops.notifications import is_slo_notification
from aiops.qualification import QualificationGate
from aiops.remediation import (
    ActionCatalog,
    HistoryRetriever,
    IncidentHistoryStore,
    PolicyEngine,
    RemediationAuditLog,
    RemediationDecisionEngine,
    RemediationFeatureExtractor,
    SelfHealOrchestrator,
)
from aiops.schemas import ActionCatalogItem, ActionProposal, CandidateEvent, Incident, RemediationDecision, VerificationResult
from aiops.shared.metrics import is_memory_metric, is_oom_metric
from aiops.shared.series import prepare_detector_series
from aiops.shared.tail import evaluate_tail_change, metric_group, oom_counter_increased, point_changed, significant_tail_change
from aiops.topology import TopologyGraph
from aiops.verification import VerificationEngine
from aiops.pipeline.analysis import (
    apply_corroboration as _apply_corroboration,
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


class AiopsPipeline:
    def __init__(
        self,
        collector: Collector,
        detectors: list[Detector],
        store,
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
        notification_sender=None,
        rca_history_path: Path | None = None,
        self_heal: SelfHealOrchestrator | None = None,
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
        self.topology_graph = TopologyGraph(runtime_config) if runtime_config is not None else None
        correlator_options = {
            key: value
            for key, value in (correlation_hyperparameters or {}).items()
            if key in {"window_seconds", "confidence_threshold", "weights", "topology_max_hops"}
        }
        self.correlator = Correlator(runtime_config, topology_graph=self.topology_graph, **correlator_options)
        self.enricher = enricher or Enricher(runtime_config=runtime_config)
        self.store = store
        if getattr(self.store, "topology_graph", None) is None:
            setattr(self.store, "topology_graph", self.topology_graph)
        self.policy = policy
        self.verification = VerificationEngine()
        self.runtime_config = runtime_config
        self.rca_hyperparameters = rca_hyperparameters or {}
        self.correlation_hyperparameters = correlation_hyperparameters or {}
        self.remediation = remediation
        self.notification_sender = notification_sender
        self.rca_history_path = rca_history_path
        self.self_heal = self_heal

    def run_once(self, metric_series: list[MetricSeries] | None = None) -> PipelineResult:
        run_number = next(_RUN_COUNTER)
        logger.info("AIOPS_RUN_START run=%s", run_number)
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
        self_heal_verification = self.self_heal.reconcile(features) if self.self_heal is not None else []
        candidates = self.detector_engine.evaluate(features)
        (logger.info if candidates else logger.debug)("AIOPS_BLOCK detect candidates=%s ids=%s", len(candidates), [candidate.detector_id for candidate in candidates])
        correlated = self.correlator.correlate(candidates)
        logger.debug("AIOPS_BLOCK correlate candidates=%s ids=%s", len(correlated), [candidate.detector_id for candidate in correlated])
        enriched = self.enricher.enrich(correlated, features)
        logger.debug("AIOPS_BLOCK enrich candidates=%s evidence=%s", len(enriched), [len(candidate.evidence) for candidate in enriched])
        incidents = [self.store.upsert(candidate) for candidate in enriched]
        analysis_incidents = incidents
        regular_incidents = [incident for incident in incidents if not is_slo_notification(incident.events[-1])]
        deduped_incidents = _unique_incidents(incidents)
        logger.debug("AIOPS_BLOCK incident persisted=%s ids=%s", len(incidents), [incident.incident_id for incident in analysis_incidents])

        direct_notifications = self._flush_notifications(
            _unique_incidents([incident for incident in incidents if is_slo_notification(incident.events[-1])]),
            only_incidents=True,
        )

        input_metric_series = metric_series or []
        rca_result = self._run_v001_rca(input_metric_series, analysis_incidents)
        root_incidents = self._upsert_rca_root_incidents(rca_result, analysis_incidents, prepare_detector_series(input_metric_series))
        if root_incidents:
            incidents.extend(root_incidents)
            analysis_incidents = incidents
            regular_incidents = [incident for incident in incidents if not is_slo_notification(incident.events[-1])]
            deduped_incidents = _unique_incidents(incidents)
        if hasattr(self.store, "reconcile_lifecycle"):
            lifecycle_incidents = self.store.reconcile_lifecycle({incident.incident_id for incident in incidents})
            recovered_now = [
                incident
                for incident in lifecycle_incidents
                if incident.state == "recovered" and incident.recovery_count == getattr(self.store, "recovery_consecutive_buckets", 6)
            ]
            if recovered_now:
                direct_notifications.extend(self._flush_notifications(recovered_now, only_incidents=True))
            analysis_incidents = _unique_incidents([
                *analysis_incidents,
                *(incident for incident in lifecycle_incidents if incident.state != "recovered"),
            ])
        logger.info(
            "AIOPS_DEDUP_RESULT input_candidates=%s rca_incidents=%s incidents=%s ids=%s services=%s occurrences=%s",
            len(enriched),
            len(root_incidents),
            len(deduped_incidents),
            [incident.incident_id for incident in deduped_incidents],
            [incident.service for incident in deduped_incidents],
            [incident.occurrence_count for incident in deduped_incidents],
        )
        verification_results = self.verification.verify(analysis_incidents, features)
        if self_heal_verification:
            reconciled_ids = {result.incident_id for result in self_heal_verification}
            verification_results = [
                result for result in verification_results if result.incident_id not in reconciled_ids
            ] + self_heal_verification
        logger.debug("AIOPS_BLOCK verify results=%s statuses=%s", len(verification_results), [result.status for result in verification_results])
        logger.info(
            "AIOPS_BLOCK rca anomalies=%s root_causes=%s",
            len(rca_result.anomalies),
            [root.service for root in rca_result.root_causes],
        )
        self._log_failure_conclusion(rca_result, analysis_incidents)
        suppressed_incident_ids = self._suppress_related_notifications(
            _unique_incidents(regular_incidents),
            rca_result,
            _unique_incidents(root_incidents),
        )
        actionable_incidents = _unique_incidents(regular_incidents)
        self._record_rca_history(rca_result, incidents, enriched, metric_series or [])
        notifications = direct_notifications + self._flush_notifications(_unique_incidents(regular_incidents))
        logger.debug("AIOPS_BLOCK notify notifications=%s", len(notifications))
        decisions: list[PolicyDecision] = []
        for incident in actionable_incidents:
            proposal = self.policy.proposal_for(incident)
            if proposal is not None:
                decisions.append(self.policy.evaluate(proposal))
        logger.debug("AIOPS_BLOCK policy decisions=%s results=%s suppressed=%s", len(decisions), [decision.result for decision in decisions], len(suppressed_incident_ids))
        remediation_decisions = self._run_remediation_strategy(actionable_incidents, rca_result, features)
        if self.self_heal is not None and remediation_decisions:
            decisions = [
                PolicyDecision(
                    allowed=decision.policy_allowed,
                    result=decision.policy_result,
                    reasons=decision.policy_reasons,
                    executed=decision.would_execute,
                )
                for decision in remediation_decisions
            ]
        for decision in remediation_decisions:
            if decision.execution_status != "verifying":
                continue
            verification_results = [
                result for result in verification_results if result.incident_id != decision.incident_id
            ]
            verification_results.append(
                VerificationResult(
                    incident_id=decision.incident_id,
                    status="inconclusive",
                    reason="awaiting_fresh_post_action_telemetry",
                )
            )
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
            "AIOPS_RUN_END run=%s candidates=%s incidents=%s root_causes=%s",
            run_number,
            len(enriched),
            len(deduped_incidents),
            len(rca_result.root_causes),
        )
        return result

    def _flush_notifications(self, incidents: list[Incident], *, only_incidents: bool = False) -> list[NotificationMessage]:
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

        notifications = self.store.pending_notifications_for(incidents) if only_incidents else self.store.due_notifications()
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

    def _upsert_rca_root_incidents(self, rca_result: RcaResult, incidents: list[Incident], metric_series: list[MetricSeries] | None = None) -> list[Incident]:
        if not rca_result.root_causes:
            return []
        severity = min((incident.severity for incident in incidents), default="SEV2")
        threshold = float(self.correlation_hyperparameters["rca_notification_min_score"])
        min_metric_score = float(self.correlation_hyperparameters["rca_notification_min_metric_score"])
        strong_shape_correlation_score = float(self.correlation_hyperparameters["rca_notification_strong_shape_correlation_score"])
        has_slo_context = any(is_slo_notification(incident.events[-1]) for incident in incidents)
        has_anomaly_context = bool(rca_result.anomalies)
        valid_roots = []
        for root in rca_result.root_causes:
            if root.score < threshold:
                logger.info(
                    "AIOPS_RCA_NOTIFY_SKIPPED filter=rca_notification_score source=rca service=%s score=%.3f threshold=%.3f reason=root_score_below_threshold",
                    root.service,
                    root.score,
                    threshold,
                )
                continue
            metric_reasons = {
                metric: self._rca_root_metric_notify_reason(root.service, metric, metric_series or [])
                for metric in root.root_cause_metrics
            }
            filtered = root.model_copy(
                update={
                    "root_cause_metrics": [
                        metric
                        for metric in root.root_cause_metrics
                        if metric_reasons[metric][0]
                    ]
                }
            )
            if not filtered.root_cause_metrics:
                logger.info(
                    "AIOPS_RCA_NOTIFY_SKIPPED filter=rca_metric_tail_gate source=rca service=%s metrics=%s reason=no_root_metric_can_notify",
                    root.service,
                    {metric: reason for metric, (_, reason) in metric_reasons.items()},
                )
                continue
            if _passes_rca_notification_gate(
                root,
                min_metric_score,
                strong_shape_correlation_score,
                has_anomaly_context or has_slo_context,
            ):
                valid_roots.append(filtered)
            else:
                logger.info(
                    "AIOPS_RCA_NOTIFY_SKIPPED filter=rca_notification_gate source=rca service=%s metric_scores=%s shape_correlation=%.3f min_metric_score=%.3f strong_shape_correlation_score=%.3f reason=weak_metric_evidence",
                    root.service,
                    root.metric_scores,
                    root.evidence_scores.get("shape_correlation", 0.0),
                    min_metric_score,
                    strong_shape_correlation_score,
                )
        rows = []
        for root in self._dedup_rca_root_causes(valid_roots):
            metric = root.root_cause_metrics[0]
            signal_id = _canonical_signal_id(self.runtime_config, root.service, metric)
            flow = next((service.flow for service in self.runtime_config.topology.services if service.name == root.service), "unknown") if self.runtime_config else "unknown"
            rows.append(
                self.store.upsert(
                    CandidateEvent(
                        detector_id="rca_root_cause",
                        flow=flow,
                        service=root.service,
                        severity=severity,
                        signal_id=signal_id,
                        value=root.score,
                        unit="score",
                        window="rca",
                        threshold=threshold,
                        quality=SignalQuality.FALLBACK_ONLY,
                        reason="rca_root_cause",
                        runbook_id=_rca_runbook_id(root),
                        likely_dependency="unknown",
                        confidence=root.score,
                        contributing_signals=tuple(root.root_cause_metrics),
                        evidence=tuple(EvidenceItem(source="rca", reference=root.service, summary=item) for item in root.evidence),
                    )
                )
            )
        return rows

    def _rca_root_metric_can_notify(self, service: str, metric: str, metric_series: list[MetricSeries]) -> bool:
        return self._rca_root_metric_notify_reason(service, metric, metric_series)[0]

    def _rca_root_metric_notify_reason(self, service: str, metric: str, metric_series: list[MetricSeries]) -> tuple[bool, str]:
        if not is_root_cause_metric(metric):
            return False, "not_root_cause_metric"
        config = self.rca_hyperparameters.get("anomaly", {})
        combined = self.rca_hyperparameters.get("combined", {})
        detection_window_seconds = int(combined.get("detection_window_seconds", 0)) or None
        start = int(self.rca_hyperparameters.get("min_points", combined.get("drift_min_points", 1))) - 1
        if (is_memory_metric(metric) or is_oom_metric(metric)) and _service_oom_counter_increased(
            service,
            metric_series,
            detection_window_seconds,
            start,
            int(config.get("oom_recent_buckets", 3)),
        ):
            return True, "oom_counter_increased"
        match = next((item for item in metric_series if item.service == service and item.metric == metric), None)
        if match is None:
            allowed = bool(self.correlation_hyperparameters["rca_notification_allow_default_metric_without_series"]) and metric_group(metric) == "default"
            return allowed, "default_metric_without_series" if allowed else "missing_metric_series"
        if not all(key in config for key in ("min_tail_anomaly_buckets", "min_relative_change_ratio", "min_absolute_change")):
            return False, "missing_tail_config"
        change = _metric_tail_change(match, detection_window_seconds, start, config)
        significant = significant_tail_change(
            match,
            detection_window_seconds,
            start,
            config["min_tail_anomaly_buckets"],
            config["min_relative_change_ratio"],
            config["min_absolute_change"],
            config.get("slow_drift", {}),
            float(config.get("page_hinkley_min_bucket_factor", 2.0)),
            oom_recent_buckets=int(config.get("oom_recent_buckets", 3)),
        )
        if not bool(self.correlation_hyperparameters["rca_notification_require_current_tail_change"]):
            return significant, "tail_significant" if significant else "tail_not_significant"
        if not significant:
            return False, "tail_not_significant"
        if not _tail_is_still_changed(metric, change, config):
            return False, "tail_reversed"
        return True, "tail_significant_current"

    def _dedup_rca_root_causes(self, root_causes: list[RootCauseCandidate]) -> list[RootCauseCandidate]:
        kept: list[RootCauseCandidate] = []
        max_hops = int(self.correlation_hyperparameters["topology_max_hops"])
        for root in root_causes:
            same_service_only = bool(self.correlation_hyperparameters.get("rca_dedup_require_same_service", True))
            duplicate = next(
                (
                    item
                    for item in kept
                    if (root.service == item.service if same_service_only else self._same_rca_topology_scope(root.service, item.service, max_hops))
                    and bool(set(root.root_cause_metrics) & set(item.root_cause_metrics))
                ),
                None,
            )
            if duplicate is None:
                kept.append(root)
                continue
            logger.info(
                "AIOPS_RCA_DEDUP_SUPPRESSED filter=rca_topology_scope source=rca service=%s kept_service=%s reason=topology_scope",
                root.service,
                duplicate.service,
            )
        return kept

    def _same_rca_topology_scope(self, service: str, other: str, max_hops: int) -> bool:
        if service == other:
            return True
        if self.topology_graph is None or not self.topology_graph.contains(service) or not self.topology_graph.contains(other):
            return False
        return self.topology_graph.has_dependency_path(service, other, max_hops) or self.topology_graph.has_dependency_path(other, service, max_hops)

    def _run_v001_rca(self, metric_series: list[MetricSeries], incidents: list[Incident] | None = None) -> RcaResult:
        detector_series = prepare_detector_series(metric_series)
        impact_findings = _slo_impact_findings(incidents or [])
        if self.runtime_config is None or not self.rca_hyperparameters or not self.rca_hyperparameters["enabled"]:
            logger.info(
                "AIOPS_BLOCK rca skipped enabled=%s metric_series=%s log_messages=%s",
                self.rca_hyperparameters.get("enabled", None),
                len(metric_series),
                0,
            )
            return RcaResult()
        config = self.rca_hyperparameters
        log_messages = self._log_messages(incidents or [], int(config["anomaly"]["log_max_events_per_evidence"]))
        if not detector_series and not log_messages and not impact_findings:
            logger.info(
                "AIOPS_BLOCK rca skipped enabled=%s metric_series=%s log_messages=%s",
                config["enabled"],
                len(metric_series),
                len(log_messages),
            )
            return RcaResult()
        anomaly_engine = build_v001_anomaly_engine(config)
        anomaly_findings = anomaly_engine.evaluate(detector_series, logs=log_messages) if log_messages else anomaly_engine.evaluate(detector_series)
        anomaly_config = config["anomaly"]
        rca_engine = V001RcaEngine(
            self.runtime_config,
            config["graph"],
            _combined_rca_hyperparameters(config, int(self.correlation_hyperparameters["topology_max_hops"])),
            topology_graph=self.topology_graph,
        )
        breakout_metrics = getattr(anomaly_engine, "last_normal_growth_breakout_metrics", {})
        normal_growth_metrics = getattr(anomaly_engine, "last_normal_growth_metrics", {})
        top_k = int(config["top_k"])
        findings = impact_findings + anomaly_findings
        rank_args = {
            "top_k": top_k + len(normal_growth_metrics),
            **({"breakout_metrics": breakout_metrics} if breakout_metrics else {}),
        }
        result = rca_engine.rank(findings, detector_series, corroboration={}, **rank_args)
        corroboration = self._staged_rca_corroboration(
            result,
            findings,
            anomaly_findings,
            detector_series,
            int(anomaly_config["evidence_window_seconds"]),
        )
        if _should_boost_from_anomaly_enrichment(result, float(self.correlation_hyperparameters["suppress_min_root_score"])):
            anomaly_findings = _apply_corroboration(
                anomaly_findings,
                detector_series,
                corroboration,
                float(anomaly_config["no_evidence_multiplier"]),
                float(anomaly_config["single_evidence_bonus"]),
                float(anomaly_config["dual_evidence_bonus"]),
            )
            findings = impact_findings + anomaly_findings
        if corroboration:
            result = rca_engine.rank(findings, detector_series, corroboration=corroboration, **rank_args)
        if normal_growth_metrics:
            result = result.model_copy(update={"root_causes": _filter_normal_growth_root_metrics(result.root_causes, normal_growth_metrics, top_k)})
        result = _add_trace_log_enrichment_fallback(result, corroboration)
        algorithm_findings = list(getattr(anomaly_engine, "last_algorithm_findings", []) or [])
        _log_final_root_cause_algorithm_scores(result, algorithm_findings)
        return result.model_copy(update={"algorithm_findings": algorithm_findings})

    def _staged_rca_corroboration(
        self,
        result: RcaResult,
        findings: list[AnomalyFinding],
        anomaly_findings: list[AnomalyFinding],
        series: list[MetricSeries],
        window_seconds: int,
    ) -> dict[str, TelemetryCorroboration]:
        if not result.root_causes:
            return {}
        root = result.root_causes[0]
        root_finding = _service_context_finding(root.service, findings, series, root)
        corroboration = self.enricher.corroborate([root_finding], window_seconds)
        logger.info("AIOPS_RCA_ENRICH stage=root service=%s strong=%s", root.service, _has_strong_corroboration(corroboration.values()))
        if not _has_strong_corroboration(corroboration.values()):
            dependencies = _direct_dependencies(self.topology_graph, root.service)
            if dependencies:
                dependency_findings = [_service_context_finding(service, findings, series, root) for service in dependencies]
                corroboration.update(self.enricher.corroborate(dependency_findings, window_seconds))
                logger.info("AIOPS_RCA_ENRICH stage=dependency_path root_service=%s services=%s strong=%s", root.service, sorted(dependencies), _has_strong_corroboration(corroboration.values()))
        if _should_boost_from_anomaly_enrichment(result, float(self.correlation_hyperparameters["suppress_min_root_score"])):
            missing = {finding.service for finding in anomaly_findings} - set(corroboration)
            if missing:
                corroboration.update(self.enricher.corroborate([_service_context_finding(service, findings, series, root) for service in missing], window_seconds))
                logger.info("AIOPS_RCA_ENRICH stage=anomaly_boost services=%s reason=low_score_or_multiple_roots", sorted(missing))
        return corroboration

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

    def _log_messages(self, incidents: list[Incident], max_events: int) -> list[tuple[str, int, str]]:
        messages = []
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

    def _run_remediation_strategy(
        self,
        incidents: list[Incident],
        rca_result: RcaResult,
        verification_features: list[Feature],
    ) -> list[RemediationDecision]:
        if self.remediation is None:
            return []
        extractor, retriever, decider, catalog, history, audit = self.remediation
        records = history.load()
        actions = catalog.load()
        decisions = []
        for incident in incidents:
            features = extractor.extract(incident, rca_result)
            decision = decider.decide(incident.incident_id, features, retriever.top_matches(features, records), actions)
            decision = self._apply_remediation_policy(decision, actions)
            action = actions.get(decision.selected_action)
            if self.self_heal is not None and decision.policy_allowed and action is not None:
                root_cause = next(
                    (root for root in rca_result.root_causes if root.service == action.target),
                    rca_result.root_causes[0] if rca_result.root_causes else None,
                )
                execution = self.self_heal.start(
                    incident,
                    action,
                    root_cause,
                    verification_features=verification_features,
                )
                decision = decision.model_copy(
                    update={
                        "would_execute": bool(execution["executed"]),
                        "execution_id": execution.get("execution_id"),
                        "execution_status": execution["status"],
                        "execution_reasons": execution.get("reasons", []),
                        "decision": "executed" if execution["executed"] else decision.decision,
                    }
                )
            logger.info(
                "AIOPS_BLOCK remediation_decide incident=%s action=%s decision=%s policy=%s execution=%s reasons=%s policy_reasons=%s",
                incident.incident_id,
                decision.selected_action,
                decision.decision,
                decision.policy_result,
                decision.execution_status,
                decision.reasons,
                decision.policy_reasons,
            )
            audit.append(decision)
            decisions.append(decision)
        return decisions

    def _apply_remediation_policy(self, decision: RemediationDecision, actions: dict[str, ActionCatalogItem]) -> RemediationDecision:
        action = actions.get(decision.selected_action)
        if decision.fallback or action is None or action.action_type == "page":
            return decision.model_copy(
                update={"policy_result": "not_mutating", "policy_allowed": False, "would_execute": False}
            )
        if self.self_heal is not None:
            capability_reasons = _local_executor_capability_reasons(
                action,
                self.self_heal.config.policy_id,
            )
            if capability_reasons:
                return decision.model_copy(
                    update={
                        "policy_result": "executor_capability_blocked",
                        "policy_reasons": tuple(capability_reasons),
                        "policy_allowed": False,
                        "would_execute": False,
                    }
                )
        policy_decision = self.policy.evaluate(
            ActionProposal(
                action_type=action.action_type,
                target=action.target,
                target_kind=action.target_kind,
                replicas=action.replicas,
                mutating=True,
                verification_defined=action.verification_defined,
                rollback_defined=action.rollback_defined,
                approved=action.approved,
            )
        )
        return decision.model_copy(
            update={
                "policy_result": policy_decision.result,
                "policy_reasons": policy_decision.reasons,
                "policy_allowed": policy_decision.allowed,
                "would_execute": False,
            }
        )

    def _suppress_related_notifications(
        self,
        incidents: list[Incident],
        rca_result: RcaResult,
        root_incidents: list[Incident] | None = None,
    ) -> set[str]:
        suppressed = set()
        service_scores = _algorithm_service_scores(rca_result.algorithm_findings)
        max_hops = int(self.correlation_hyperparameters.get("topology_max_hops", 1))
        min_score = float(self.correlation_hyperparameters.get("suppress_min_root_score", 1.0))
        active_roots = [incident for incident in (root_incidents or []) if incident.events[-1].confidence >= min_score]
        root_services = {incident.service for incident in active_roots}
        direct_anomaly_services = set(service_scores) if self.correlation_hyperparameters.get("allow_direct_anomaly_breakout", True) else set()
        slo_services = {
            incident.service
            for incident in incidents
            if self.correlation_hyperparameters.get("allow_slo_breakout", True) and is_slo_notification(incident.events[-1])
        }
        affected_by_root = {
            incident.service: self.topology_graph.neighborhood(incident.service, max_hops) if self.topology_graph is not None else {incident.service}
            for incident in active_roots
        }
        for incident in active_roots:
            root_service = incident.service
            affected_services = affected_by_root[root_service]
            root_score = service_scores.get(root_service) or incident.events[-1].confidence
            logger.info(
                "AIOPS_RCA_SUPPRESS_FILTER filter=active_root_cause source=rca root_service=%s affected_services=%s max_hops=%s suppress_seconds=%s reason=notifiable_root_cause",
                root_service,
                sorted(affected_services),
                max_hops,
                int(self.correlation_hyperparameters.get("suppress_window_seconds", 900)),
            )
            self.store.register_active_root_cause(
                root_service,
                affected_services,
                int(self.correlation_hyperparameters.get("suppress_window_seconds", 900)),
                root_score,
            )
        breakout_services = (
            self.store.breakout_services(
                service_scores,
                float(self.correlation_hyperparameters.get("suppress_breakout_multiplier", 1.5)),
                max_hops,
            )
            if service_scores
            else set()
        )
        exempt_services = breakout_services | root_services | direct_anomaly_services | slo_services
        for root_service, affected_services in affected_by_root.items():
            suppressed.update(self.store.suppress_related_notifications(incidents, root_service, affected_services, exempt_services))
        if incidents:
            remaining = [incident for incident in incidents if incident.incident_id not in suppressed]
            suppressed.update(self.store.suppress_active_root_notifications(remaining, exempt_services))
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


def _algorithm_service_scores(findings: list[AnomalyFinding]) -> dict[str, float]:
    algorithms = {"robust_drift", "ewma_stl", "isolation_forest"}
    maxima: dict[str, dict[str, float]] = {}
    for finding in findings:
        if finding.algorithm in algorithms and is_root_cause_metric(finding.metric):
            service_scores = maxima.setdefault(finding.service, {})
            service_scores[finding.algorithm] = max(service_scores.get(finding.algorithm, 0.0), finding.score)
    return {service: sum(scores.values()) for service, scores in maxima.items()}


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


def _filter_normal_growth_root_metrics(root_causes: list[RootCauseCandidate], normal_growth_metrics: dict[str, set[str]], top_k: int) -> list[RootCauseCandidate]:
    kept: list[RootCauseCandidate] = []
    suppressed: dict[str, list[str]] = {}
    for root in root_causes:
        explained = normal_growth_metrics.get(root.service, set())
        metrics = [metric for metric in root.root_cause_metrics if metric not in explained]
        removed = [metric for metric in root.root_cause_metrics if metric in explained]
        if removed:
            suppressed[root.service] = removed
        if metrics:
            kept.append(root.model_copy(update={"root_cause_metrics": metrics}))
        if len(kept) >= top_k:
            break
    if suppressed:
        logger.info("AIOPS_RCA_BUSY_SUPPRESSED metrics=%s", {service: sorted(metrics) for service, metrics in suppressed.items()})
    return kept


def _has_strong_corroboration(items) -> bool:
    return any(item.log_failure or item.trace_failure for item in items)


def _add_trace_log_enrichment_fallback(result: RcaResult, corroboration: dict[str, TelemetryCorroboration]) -> RcaResult:
    if not result.root_causes or not corroboration or _has_strong_corroboration(corroboration.values()):
        return result
    line = "Trace/log enrichment: queried root/dependencies, no hard failure found"
    return result.model_copy(
        update={
            "root_causes": [
                root.model_copy(update={"evidence": [*root.evidence, line]})
                for root in result.root_causes
            ]
        }
    )


def _should_boost_from_anomaly_enrichment(result: RcaResult, low_score_threshold: float) -> bool:
    return bool(result.root_causes) and (result.root_causes[0].score < low_score_threshold or len(result.root_causes) > 1)


def _direct_dependencies(topology_graph: TopologyGraph | None, service: str) -> set[str]:
    if topology_graph is None or not topology_graph.contains(service):
        return set()
    return set(topology_graph.graph.successors(service))


def _service_context_finding(
    service: str,
    findings: list[AnomalyFinding],
    series: list[MetricSeries],
    root: RootCauseCandidate,
) -> AnomalyFinding:
    timestamp = max(
        [finding.timestamp for finding in findings if finding.service == service]
        + [metric.points[-1].timestamp for metric in series if metric.service == service and metric.points],
        default=0,
    )
    metric = root.root_cause_metrics[0] if root.root_cause_metrics else "rca_root"
    return AnomalyFinding(
        algorithm="rca_enrichment",
        service=service,
        metric=metric,
        signal_id=f"{service}_{metric}",
        score=root.score,
        timestamp=timestamp,
    )


def _service_oom_counter_increased(
    service: str,
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    recent_buckets: int,
) -> bool:
    return oom_counter_increased(series, detection_window_seconds, start, service, recent_buckets)


def _metric_tail_change(metric: MetricSeries, detection_window_seconds: int | None, start: int, config: dict):
    group = metric_group(metric.metric)
    return evaluate_tail_change(
        metric,
        detection_window_seconds,
        start,
        int(config["min_tail_anomaly_buckets"][group]),
        float(config["min_relative_change_ratio"][group]),
        float(config["min_absolute_change"][group]),
    )


def _tail_is_still_changed(metric: str, change, config: dict) -> bool:
    if not change.indexes:
        return False
    group = metric_group(metric)
    last = change.values[change.indexes[-1]]
    if point_changed(
        last,
        change.baseline,
        float(config["min_relative_change_ratio"][group]),
        float(config["min_absolute_change"][group]),
    ):
        return True
    direction = config.get("slow_drift", {}).get("metrics", {}).get(group, {}).get("direction")
    recent = change.indexes[-max(2, int(config["min_tail_anomaly_buckets"][group])) :]
    if direction == "up":
        return len(recent) > 1 and last > change.values[recent[0]]
    if direction == "down":
        return len(recent) > 1 and last < change.values[recent[0]]
    return False


def _passes_rca_notification_gate(
    root: RootCauseCandidate,
    min_metric_score: float,
    strong_shape_correlation_score: float,
    has_rca_context: bool = False,
) -> bool:
    if has_rca_context:
        return True
    if min_metric_score <= 0:
        return True
    metric_scores = list(root.metric_scores.values())
    return not metric_scores or max(metric_scores) >= min_metric_score or root.evidence_scores.get("shape_correlation", 0.0) >= strong_shape_correlation_score


def _combined_rca_hyperparameters(config: dict, topology_max_hops: int) -> dict:
    anomaly = config["anomaly"]
    return {
        **config["combined"],
        "min_tail_anomaly_buckets": anomaly["min_tail_anomaly_buckets"],
        "min_relative_change_ratio": anomaly["min_relative_change_ratio"],
        "min_absolute_change": anomaly["min_absolute_change"],
        "slow_drift": anomaly.get("slow_drift", {}),
        "page_hinkley_min_bucket_factor": anomaly["page_hinkley_min_bucket_factor"],
        "oom_recent_buckets": anomaly["oom_recent_buckets"],
        "traffic_shape_max_lag_buckets": anomaly["traffic_shape_max_lag_buckets"],
        "topology_max_hops": topology_max_hops,
    }


def _score(value: float | None) -> str:
    return "NA" if value is None else f"{value:.3f}"


def _rca_runbook_id(root: RootCauseCandidate) -> str:
    metrics = " ".join(root.root_cause_metrics).lower()
    if "error" in metrics:
        return "RB-CART-ERROR-RATE" if root.service == "cart" else "RB-SERVICE-ERROR-RATE"
    if "latency" in metrics or "duration" in metrics:
        return "RB-CHECKOUT-LATENCY" if root.service == "checkout" else "RB-SERVICE-LATENCY"
    if root.service == "product-catalog" and "cpu" in metrics:
        return "RB-PRODUCT-CATALOG-CPU"
    return "RB-SERVICE-RESOURCE"


def _log_excerpts(summary: str, max_events: int) -> list[str]:
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


def _local_executor_capability_reasons(
    action: ActionCatalogItem,
    policy_id: str,
) -> list[str]:
    checks = (
        (action.executor_supported, "executor_not_supported"),
        (action.dry_run_supported, "dry_run_not_supported"),
        (action.execute_supported, "execute_not_supported"),
        (action.live_execute_supported, "live_execute_not_supported"),
        (not action.recommendation_only, "recommendation_only"),
        (not action.audit_only, "audit_only"),
        (not action.protected, "protected_action"),
        (not action.blocked, "blocked_action"),
        (action.verification_defined, "verification_not_defined"),
        (bool(action.verification_query_id), "verification_query_missing"),
        (bool(action.verification_signal_id), "verification_signal_missing"),
        (
            action.verification_threshold is not None
            or action.verification_max_ratio is not None,
            "verification_recovery_rule_missing",
        ),
        (action.rollback_defined, "rollback_not_defined"),
        (action.rollback_supported, "rollback_not_supported"),
        (bool(action.rollback_action_id), "rollback_action_missing"),
        (action.approved, "action_not_approved"),
        (action.policy_approval_required, "policy_approval_not_required"),
        (action.policy_id == policy_id, "policy_id_mismatch"),
    )
    return [reason for allowed, reason in checks if not allowed]


def _canonical_signal_id(
    runtime_config: RuntimeConfig | None,
    service: str,
    metric: str,
) -> str:
    if runtime_config is not None:
        for spec in runtime_config.prometheus_query_specs.values():
            if spec.service == service and spec.metric == metric:
                return spec.signal_id
    return f"{service.replace('-', '_')}_{metric}"
