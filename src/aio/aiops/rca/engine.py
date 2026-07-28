#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
from collections import defaultdict

from aiops.anomaly.stats import robust_score
from aiops.rca.graph import GraphTraversalRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig, TelemetryCorroboration
from aiops.shared.evidence import log_summary, trace_summary
from aiops.shared.metrics import is_root_cause_metric, metric_priority
from aiops.shared.tail import fixed_baseline_and_tail, metric_group, significant_tail_change, tail_aligned_spearman
from aiops.topology import TopologyGraph


logger = logging.getLogger(__name__)


class V001RcaEngine:
    def __init__(
        self,
        config: RuntimeConfig,
        graph_hyperparameters: dict[str, float],
        combined_hyperparameters: dict[str, float],
        topology_graph: TopologyGraph | None = None,
    ):
        self.config = config
        self.topology_graph = topology_graph or TopologyGraph(config)
        self.ranker_weights = combined_hyperparameters["ranker_weights"]
        self.rrf_k = combined_hyperparameters["rrf_k"]
        self.drift_min_points = int(combined_hyperparameters["drift_min_points"])
        self.drift_score_threshold = float(combined_hyperparameters["drift_score_threshold"])
        self.detection_window_seconds = int(combined_hyperparameters["detection_window_seconds"]) or None
        self.min_tail_anomaly_buckets = {key: int(value) for key, value in combined_hyperparameters["min_tail_anomaly_buckets"].items()}
        self.min_relative_change_ratio = {key: float(value) for key, value in combined_hyperparameters["min_relative_change_ratio"].items()}
        self.min_absolute_change = {key: float(value) for key, value in combined_hyperparameters["min_absolute_change"].items()}
        self.slow_drift = combined_hyperparameters.get("slow_drift", {})
        self.page_hinkley_min_bucket_factor = float(combined_hyperparameters["page_hinkley_min_bucket_factor"])
        self.oom_recent_buckets = int(combined_hyperparameters["oom_recent_buckets"])
        self.traffic_shape_max_lag_buckets = int(combined_hyperparameters["traffic_shape_max_lag_buckets"])
        self.topology_max_hops = int(combined_hyperparameters["topology_max_hops"])
        self.canonical_service_suffixes = tuple(combined_hyperparameters["canonical_service_suffixes"])
        self.metric_aliases = combined_hyperparameters["metric_aliases"]
        self.graph = GraphTraversalRca(
            config,
            damping=graph_hyperparameters["damping"],
            pagerank_weight=graph_hyperparameters["pagerank_weight"],
            timestamp_weight=graph_hyperparameters["timestamp_weight"],
            pagerank_max_iter=int(graph_hyperparameters["pagerank_max_iter"]),
            pagerank_tolerance=float(graph_hyperparameters["pagerank_tolerance"]),
            topology_graph=self.topology_graph,
        )

    def rank(
        self,
        findings: list[AnomalyFinding],
        series: list[MetricSeries],
        top_k: int,
        corroboration: dict[str, TelemetryCorroboration] | None = None,
        breakout_metrics: dict[str, set[str]] | None = None,
    ) -> RcaResult:
        breakout_metrics = {
            self._canonical_service(service): set(metrics)
            for service, metrics in (breakout_metrics or {}).items()
            if metrics
        }
        required_breakout_metrics = {
            service: {metric for metric in metrics if is_root_cause_metric(metric)}
            for service, metrics in breakout_metrics.items()
        }
        root_findings = [
            finding.model_copy(update={"service": self._canonical_service(finding.service)})
            if finding.service != "global"
            else finding
            for finding in findings
            if (finding.service == "global" or not self._excluded_root_cause(finding.service))
            and (is_root_cause_metric(finding.metric) or self._is_breakout_metric(self._canonical_service(finding.service), finding.metric, breakout_metrics))
        ]
        root_findings.extend(self._trace_log_root_findings(root_findings, corroboration or {}))
        rca_series = [metric for metric in series if is_root_cause_metric(metric.metric)]
        drift_metrics = self._drift_metrics(rca_series)
        if not root_findings and any(finding.algorithm == "slo_threshold" for finding in findings):
            root_findings.extend(
                AnomalyFinding(
                    algorithm="drift",
                    service=service,
                    metric=metric,
                    signal_id=signal_id,
                    score=score,
                    timestamp=timestamp,
                )
                for service, metric, signal_id, score, timestamp in drift_metrics
            )
        if not root_findings:
            return RcaResult(anomalies=findings)
        graph_scores = _normalize_scores(self.graph.rank_services(root_findings))
        graph_evidence_scores = graph_scores
        earliest_scores = self._earliest_drift_scores(rca_series)
        shape_correlation_scores = self._shape_correlation_scores(rca_series, findings, series)
        downstream_coverage_scores = self._downstream_coverage_scores(root_findings)
        rankers = {
            "graph": graph_scores,
            "earliest_drift": earliest_scores,
            "shape_correlation": shape_correlation_scores,
            "downstream_coverage": downstream_coverage_scores,
        }
        service_scores, support_scores = self._weighted_rank_scores(rankers)
        evidence_strength = {
            service: min(1.0, max(finding.score for finding in root_findings if finding.service == service))
            for service in {finding.service for finding in root_findings if finding.service != "global"}
        }

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in root_findings:
            if finding.service == "global":
                continue
            if not is_root_cause_metric(finding.metric):
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
        for service, metric, _, score, _ in drift_metrics:
            if service not in metrics_by_service:
                metrics_by_service[service].append((metric, score, "drift"))

        candidates: list[RootCauseCandidate] = []
        trace_details, log_details = self._corroboration_details(corroboration or {})
        for service, rank_score in sorted(
            service_scores.items(),
            key=lambda item: item[1] * evidence_strength.get(item[0], 0.0),
            reverse=True,
        ):
            score = rank_score * evidence_strength.get(service, 0.0) * support_scores.get(service, 0.0)
            if service not in evidence_strength:
                continue
            if self._excluded_root_cause(service):
                continue
            if not metrics_by_service[service]:
                continue
            metric_scores = sorted(metrics_by_service[service], key=lambda item: (self._is_breakout_metric(service, item[0], required_breakout_metrics), metric_priority(item[0]), item[1]), reverse=True)
            if required_breakout_metrics.get(service) and not self._is_breakout_metric(service, metric_scores[0][0], required_breakout_metrics):
                continue
            metrics = list(dict.fromkeys(alias for metric, _, _ in metric_scores for alias in self._metric_aliases(metric)))
            evidence_scores = {
                "graph": graph_evidence_scores.get(service, 0.0),
                "earliest_drift": earliest_scores.get(service, 0.0),
                "shape_correlation": shape_correlation_scores.get(service, 0.0),
                "downstream_coverage": downstream_coverage_scores.get(service, 0.0),
                "weighted_rrf": rank_score,
                "evidence_strength": evidence_strength.get(service, 0.0),
                "support": support_scores.get(service, 0.0),
            }
            candidates.append(
                RootCauseCandidate(
                    service=service,
                    score=score,
                    root_cause_metrics=metrics,
                    evidence=[
                        f"graph_score={evidence_scores['graph']:.3f}",
                        f"earliest_drift_score={evidence_scores['earliest_drift']:.3f}",
                        f"shape_correlation_score={evidence_scores['shape_correlation']:.3f}",
                        f"downstream_coverage_score={evidence_scores['downstream_coverage']:.3f}",
                        f"weighted_rrf_score={evidence_scores['weighted_rrf']:.3f}",
                        f"evidence_strength={evidence_scores['evidence_strength']:.3f}",
                        f"support_score={evidence_scores['support']:.3f}",
                    ]
                    + [
                        *log_details.get(service, []),
                        *trace_details.get(service, []),
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                    evidence_scores=evidence_scores,
                    metric_scores={metric: metric_score for metric, metric_score, _ in metric_scores},
                )
            )
            if len(candidates) >= top_k:
                break
        return RcaResult(anomalies=findings, root_causes=self._suppress_downstream_symptoms(candidates, root_findings))

    def _downstream_coverage_scores(self, findings: list[AnomalyFinding]) -> dict[str, float]:
        first_seen: dict[str, int] = {}
        strength: dict[str, float] = {}
        for finding in findings:
            if finding.service == "global":
                continue
            first_seen[finding.service] = min(first_seen.get(finding.service, finding.timestamp), finding.timestamp)
            strength[finding.service] = max(strength.get(finding.service, 0.0), finding.score)
        scores = {
            root: sum(
                strength.get(service, 0.0)
                for service in first_seen
                if service != root
                and self.topology_graph.has_dependency_path(service, root, self.topology_max_hops)
                and first_seen[root] < first_seen[service]
            )
            for root in first_seen
        }
        maximum = max(scores.values(), default=0.0)
        return {service: score / maximum for service, score in scores.items() if maximum and score > 0}

    def _trace_log_root_findings(self, root_findings: list[AnomalyFinding], corroboration: dict[str, TelemetryCorroboration]) -> list[AnomalyFinding]:
        existing = {(finding.service, finding.metric) for finding in root_findings}
        rows = []
        for source, evidence in corroboration.items():
            root = self._canonical_service(evidence.trace_root_service or "")
            if not (root and evidence.trace_failure and evidence.log_failure and evidence.log_classification == "hard_failure"):
                continue
            if not self._trace_root_allowed(source, root):
                continue
            key = (root, "trace_log_failure")
            if key not in existing:
                rows.append(
                    AnomalyFinding(
                        algorithm="trace_log_root",
                        service=root,
                        metric="trace_log_failure",
                        signal_id=evidence.trace_id or f"{root}_trace_log_failure",
                        score=1.0,
                        timestamp=evidence.trace_failure_timestamp or evidence.log_failure_timestamp or 0,
                    )
                )
        return rows

    def _trace_root_allowed(self, source: str, root: str) -> bool:
        source = self._canonical_service(source)
        return source == root or self.topology_graph.has_dependency_path(source, root)

    def _corroboration_details(self, corroboration: dict[str, TelemetryCorroboration]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        trace_details: dict[str, list[str]] = defaultdict(list)
        log_details: dict[str, list[str]] = defaultdict(list)
        for source, evidence in corroboration.items():
            trace_root = self._canonical_service(evidence.trace_root_service or "")
            if evidence.trace_failure and trace_root:
                trace_details[trace_root].append(
                    trace_summary(
                        evidence.trace_id,
                        evidence.trace_operation,
                        evidence.trace_status,
                        evidence.trace_duration_ms,
                        evidence.trace_reference,
                        upstream=source,
                        downstream=trace_root,
                    )
                )
            elif evidence.trace_id:
                trace_details[self._canonical_service(source)].append(
                    trace_summary(
                        evidence.trace_id,
                        evidence.trace_operation,
                        evidence.trace_status,
                        evidence.trace_duration_ms,
                        evidence.trace_reference,
                        observed=True,
                    )
                )
            if evidence.log_failure or evidence.log_failure_count:
                detail = log_summary(evidence.log_classification, evidence.log_failure_count, evidence.log_failure_timestamp, evidence.log_reference, evidence.log_excerpt)
                log_details[self._canonical_service(source)].append(detail)
                if trace_root:
                    log_details[trace_root].append(detail)
        return trace_details, log_details

    def _suppress_downstream_symptoms(self, candidates: list[RootCauseCandidate], findings: list[AnomalyFinding]) -> list[RootCauseCandidate]:
        first_seen: dict[str, int] = {}
        for finding in findings:
            if finding.service != "global":
                first_seen[finding.service] = min(first_seen.get(finding.service, finding.timestamp), finding.timestamp)
        suppressed: set[str] = set()
        for candidate in candidates:
            parent = next(
                (
                    root
                    for root in candidates
                    if root.service != candidate.service
                    and self.topology_graph.has_dependency_path(candidate.service, root.service, self.topology_max_hops)
                    and first_seen.get(root.service, 0) < first_seen.get(candidate.service, 0)
                    and root.score >= candidate.score
                ),
                None,
            )
            if parent is not None:
                suppressed.add(candidate.service)
                logger.info(
                    "AIOPS_RCA_SUPPRESSED filter=downstream_symptom source=rca service=%s parent_root_cause=%s reason=parent_earlier_and_stronger score=%.3f parent_score=%.3f",
                    candidate.service,
                    parent.service,
                    candidate.score,
                    parent.score,
                )
        return [candidate for candidate in candidates if candidate.service not in suppressed]

    def _earliest_drift_scores(self, series: list[MetricSeries]) -> dict[str, float]:
        drift_indexes: dict[str, int] = {}
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.drift_min_points:
                continue
            index = self._first_drift_index(metric, values)
            if index is not None and not self._excluded_root_cause(metric.service):
                service = self._canonical_service(metric.service)
                drift_indexes[service] = min(drift_indexes.get(service, index), index)
        if not drift_indexes:
            return {}
        latest = max(drift_indexes.values()) or 1
        return {service: 1.0 - (index / latest) for service, index in drift_indexes.items()}

    def _first_drift_index(self, metric: MetricSeries, values: list[float]) -> int | None:
        if not self._significant_tail_change(metric):
            return None
        baseline, indexes = fixed_baseline_and_tail(metric, self.detection_window_seconds, self.drift_min_points - 1, values)
        for index in indexes:
            if robust_score(baseline, [values[index]]) >= self.drift_score_threshold:
                return index
        return None

    def _drift_metrics(self, series: list[MetricSeries]) -> list[tuple[str, str, str, float, int]]:
        rows = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.drift_min_points or self._excluded_root_cause(metric.service):
                continue
            baseline, indexes = fixed_baseline_and_tail(metric, self.detection_window_seconds, self.drift_min_points - 1, values)
            score, index = max(
                ((robust_score(baseline, [values[index]]), index) for index in indexes),
                default=(0.0, 0),
            )
            if score >= self.drift_score_threshold:
                if not self._significant_tail_change(metric):
                    continue
                rows.append((self._canonical_service(metric.service), metric.metric, metric.signal_id, score, metric.points[index].timestamp))
        return rows

    def _significant_tail_change(self, metric: MetricSeries) -> bool:
        return significant_tail_change(
            metric,
            self.detection_window_seconds,
            self.drift_min_points - 1,
            self.min_tail_anomaly_buckets,
            self.min_relative_change_ratio,
            self.min_absolute_change,
            self.slow_drift,
            self.page_hinkley_min_bucket_factor,
            oom_recent_buckets=self.oom_recent_buckets,
        )

    def _shape_correlation_scores(
        self,
        series: list[MetricSeries],
        findings: list[AnomalyFinding],
        impact_series: list[MetricSeries] | None = None,
    ) -> dict[str, float]:
        impact_series = impact_series or series
        primaries = [
            metric
            for finding in findings
            if finding.algorithm == "slo_threshold"
            for metric in impact_series
            if metric.signal_id == finding.signal_id
        ]
        if not primaries:
            primary = self._primary_series(impact_series, findings)
            if primary is None:
                return {}
            primaries = [primary]
        scores: dict[str, float] = {}
        for metric in series:
            if metric.service == "global" or self._excluded_root_cause(metric.service):
                continue
            score = max(
                abs(tail_aligned_spearman(primary, metric, self.detection_window_seconds, self.drift_min_points - 1, right_lag_buckets=lag))
                for lag in range(max(0, self.traffic_shape_max_lag_buckets) + 1)
                for primary in primaries
            )
            service = self._canonical_service(metric.service)
            scores[service] = max(scores.get(service, 0.0), score)
        return scores

    def _primary_series(self, series: list[MetricSeries], findings: list[AnomalyFinding]) -> MetricSeries | None:
        if not findings:
            return None
        top = max(findings, key=lambda finding: finding.score)
        return next((metric for metric in series if metric.signal_id == top.signal_id), None)

    def _weighted_rank_scores(self, rankers: dict[str, dict[str, float]]) -> tuple[dict[str, float], dict[str, float]]:
        scores: dict[str, float] = defaultdict(float)
        max_possible = sum(self.ranker_weights[name] / (self.rrf_k + 1) for name, values in rankers.items() if values)
        if not max_possible:
            return {}, {}
        for name, values in rankers.items():
            weight = self.ranker_weights[name]
            for rank, (service, _) in enumerate(sorted(values.items(), key=lambda item: item[1], reverse=True), start=1):
                scores[service] += weight / (self.rrf_k + rank)
        rrf_scores = {service: score / max_possible for service, score in scores.items()}
        services = {service for values in rankers.values() for service in values}
        total = sum(self.ranker_weights[name] for name in rankers)
        if not total:
            return rrf_scores, {}
        support_scores = {
            service: sum(self.ranker_weights[name] * max(0.0, min(1.0, values.get(service, 0.0))) for name, values in rankers.items()) / total
            for service in services
        }
        return rrf_scores, support_scores

    def _excluded_root_cause(self, service: str) -> bool:
        services = {item.name: item for item in self.config.topology.services}
        item = services.get(service)
        if item is None:
            return False
        if item.flow in self.config.policy.non_actionable_flows:
            return True
        return service in self.config.policy.protected_targets and service != "postgresql"

    def _metric_aliases(self, metric: str) -> tuple[str, ...]:
        aliases = [metric]
        for marker, values in self.metric_aliases.items():
            if marker in metric:
                aliases.extend(values)
        return tuple(aliases)

    def _is_breakout_metric(self, service: str, metric: str, breakout_metrics: dict[str, set[str]]) -> bool:
        return metric in breakout_metrics.get(service, set())

    def _canonical_service(self, service: str) -> str:
        for suffix in self.canonical_service_suffixes:
            if suffix and service.endswith(suffix):
                return service[: -len(suffix)]
        return service


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    maximum = max(scores.values(), default=0.0)
    if maximum <= 0:
        return {}
    return {service: max(0.0, min(1.0, score / maximum)) for service, score in scores.items()}
