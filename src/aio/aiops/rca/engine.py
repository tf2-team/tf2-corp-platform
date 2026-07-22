#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import defaultdict
import math

from aiops.anomaly.stats import median, robust_score
from aiops.anomaly.v001 import _metric_group, _normal_traffic_growth_decision, _point_changed
from aiops.rca.graph import GraphTraversalRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig, TelemetryCorroboration


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig, graph_hyperparameters: dict[str, float], combined_hyperparameters: dict[str, float]):
        self.config = config
        self.ranker_weights = combined_hyperparameters["ranker_weights"]
        self.rrf_k = combined_hyperparameters["rrf_k"]
        self.drift_min_points = int(combined_hyperparameters["drift_min_points"])
        self.drift_score_threshold = float(combined_hyperparameters["drift_score_threshold"])
        self.detection_window_seconds = int(combined_hyperparameters["detection_window_seconds"]) or None
        self.min_tail_anomaly_buckets = {key: int(value) for key, value in combined_hyperparameters["min_tail_anomaly_buckets"].items()}
        self.min_relative_change_ratio = {key: float(value) for key, value in combined_hyperparameters["min_relative_change_ratio"].items()}
        self.min_absolute_change = {key: float(value) for key, value in combined_hyperparameters["min_absolute_change"].items()}
        self.canonical_service_suffixes = tuple(combined_hyperparameters["canonical_service_suffixes"])
        self.metric_aliases = combined_hyperparameters["metric_aliases"]
        self.graph = GraphTraversalRca(
            config,
            damping=graph_hyperparameters["damping"],
            pagerank_weight=graph_hyperparameters["pagerank_weight"],
            timestamp_weight=graph_hyperparameters["timestamp_weight"],
        )

    def rank(
        self,
        findings: list[AnomalyFinding],
        series: list[MetricSeries],
        top_k: int,
        corroboration: dict[str, TelemetryCorroboration] | None = None,
    ) -> RcaResult:
        root_findings = [
            finding.model_copy(update={"service": self._canonical_service(finding.service)})
            if finding.service != "global"
            else finding
            for finding in findings
            if (finding.service == "global" or not self._excluded_root_cause(finding.service))
            and not _is_context_metric(finding.metric)
            and not self._busy_infra_without_failure(finding.service, finding.metric, finding.timestamp, series, findings)
        ]
        trace_findings = self._trace_findings(findings, corroboration or {})
        root_findings.extend(trace_findings)
        rca_series = [metric for metric in series if not _is_context_metric(metric.metric)]
        drift_metrics = self._drift_metrics(rca_series, series, findings)
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
        graph_scores = self.graph.rank_services(root_findings)
        earliest_scores = self._earliest_drift_scores(rca_series)
        correlation_scores = self._correlation_scores(rca_series, findings, series)
        service_scores = self._weighted_rrf(
            {
                "graph": graph_scores,
                "earliest_drift": earliest_scores,
                "correlation": correlation_scores,
            }
        )
        anomaly_services = {finding.service for finding in root_findings if finding.service != "global"}
        evidence_strength = {
            service: min(1.0, max(finding.score for finding in root_findings if finding.service == service))
            for service in anomaly_services
        }

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in root_findings:
            if finding.service == "global":
                continue
            if _is_log_metric(finding.metric) or _is_context_metric(finding.metric):
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
        for service, metric, _, score, _ in drift_metrics:
            metrics_by_service[service].append((metric, score, "drift"))

        candidates: list[RootCauseCandidate] = []
        trace_services = {finding.service for finding in trace_findings}
        for service, rank_score in sorted(
            service_scores.items(),
            key=lambda item: (item[0] in trace_services, item[1] * evidence_strength.get(item[0], 0.0)),
            reverse=True,
        ):
            score = rank_score * evidence_strength.get(service, 0.0)
            if service not in anomaly_services:
                continue
            if self._excluded_root_cause(service):
                continue
            if not metrics_by_service[service]:
                continue
            metric_scores = sorted(metrics_by_service[service], key=lambda item: (_metric_priority(item[0]), item[1]), reverse=True)
            metrics = list(dict.fromkeys(alias for metric, _, _ in metric_scores for alias in self._metric_aliases(metric)))
            candidates.append(
                RootCauseCandidate(
                    service=service,
                    score=score,
                    root_cause_metrics=metrics,
                    evidence=[
                        f"graph_score={graph_scores.get(service, 0.0):.3f}",
                        f"earliest_drift_score={earliest_scores.get(service, 0.0):.3f}",
                        f"correlation_score={correlation_scores.get(service, 0.0):.3f}",
                        f"weighted_rrf_score={rank_score:.3f}",
                        f"evidence_strength={evidence_strength.get(service, 0.0):.3f}",
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                )
            )
            if len(candidates) >= top_k:
                break
        return RcaResult(anomalies=findings, root_causes=candidates)

    def _trace_findings(
        self,
        findings: list[AnomalyFinding],
        corroboration: dict[str, TelemetryCorroboration],
    ) -> list[AnomalyFinding]:
        rows = []
        for source, evidence in corroboration.items():
            root = evidence.trace_root_service
            if not evidence.trace_failure or root is None or not self._dependency_path_contains(source, root):
                continue
            score = max((finding.score for finding in findings if finding.service == source), default=0.0)
            if score:
                rows.append(
                    AnomalyFinding(
                        algorithm="trace",
                        service=root,
                        metric="trace_failure",
                        signal_id=f"{root}_trace_failure",
                        score=score,
                        timestamp=evidence.trace_failure_timestamp or 0,
                    )
                )
        return rows

    def _dependency_path_contains(self, source: str, target: str) -> bool:
        graph = {service.name: service.dependencies for service in self.config.topology.services}
        if source not in graph or target not in graph:
            return False
        pending = [source]
        seen = set()
        while pending:
            service = pending.pop()
            if service == target:
                return True
            if service in seen:
                continue
            seen.add(service)
            pending.extend(graph.get(service, []))
        return False

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
        for index in _tail_indexes(metric, self.detection_window_seconds, self.drift_min_points - 1):
            if robust_score(values[:index], [values[index]]) >= self.drift_score_threshold:
                return index
        return None

    def _drift_metrics(self, series: list[MetricSeries], all_series: list[MetricSeries], findings: list[AnomalyFinding]) -> list[tuple[str, str, str, float, int]]:
        rows = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.drift_min_points or self._excluded_root_cause(metric.service):
                continue
            score, index = max(
                ((robust_score(values[:index], [values[index]]), index) for index in _tail_indexes(metric, self.detection_window_seconds, self.drift_min_points - 1)),
                default=(0.0, 0),
            )
            if score >= self.drift_score_threshold:
                if not self._significant_tail_change(metric):
                    continue
                if self._busy_infra_without_failure(metric.service, metric.metric, metric.points[index].timestamp, all_series, findings):
                    continue
                rows.append((self._canonical_service(metric.service), metric.metric, metric.signal_id, score, metric.points[index].timestamp))
        return rows

    def _significant_tail_change(self, metric: MetricSeries) -> bool:
        indexes = list(_tail_indexes(metric, self.detection_window_seconds, self.drift_min_points - 1))
        if not indexes:
            return False
        baseline_values = [point.value for point in metric.points[: indexes[0]]]
        if len(baseline_values) < 4:
            return False
        group = _metric_group(metric.metric)
        baseline = median(baseline_values)
        changed = sum(
            _point_changed(
                metric.points[index].value,
                baseline,
                self.min_relative_change_ratio[group],
                self.min_absolute_change[group],
            )
            for index in indexes
        )
        return changed >= self.min_tail_anomaly_buckets[group]

    def _correlation_scores(
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
            score = max(abs(self._pearson([point.value for point in primary.points], [point.value for point in metric.points])) for primary in primaries)
            service = self._canonical_service(metric.service)
            scores[service] = max(scores.get(service, 0.0), score)
        return scores

    def _primary_series(self, series: list[MetricSeries], findings: list[AnomalyFinding]) -> MetricSeries | None:
        if not findings:
            return None
        top = max(findings, key=lambda finding: finding.score)
        return next((metric for metric in series if metric.signal_id == top.signal_id), None)

    def _pearson(self, left: list[float], right: list[float]) -> float:
        length = min(len(left), len(right))
        if length < 3:
            return 0.0
        left = left[-length:]
        right = right[-length:]
        left_mean = sum(left) / length
        right_mean = sum(right) / length
        numerator = sum((left[index] - left_mean) * (right[index] - right_mean) for index in range(length))
        left_denominator = math.sqrt(sum((value - left_mean) ** 2 for value in left))
        right_denominator = math.sqrt(sum((value - right_mean) ** 2 for value in right))
        denominator = left_denominator * right_denominator
        return numerator / denominator if denominator else 0.0

    def _weighted_rrf(self, rankers: dict[str, dict[str, float]]) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        max_possible = sum(self.ranker_weights.get(name, 0.0) / (self.rrf_k + 1) for name, values in rankers.items() if values)
        if not max_possible:
            return {}
        for name, values in rankers.items():
            weight = self.ranker_weights.get(name, 0.0)
            for rank, (service, _) in enumerate(sorted(values.items(), key=lambda item: item[1], reverse=True), start=1):
                scores[service] += weight / (self.rrf_k + rank)
        return {service: score / max_possible for service, score in scores.items()}

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

    def _canonical_service(self, service: str) -> str:
        for suffix in self.canonical_service_suffixes:
            if suffix and service.endswith(suffix):
                return service[: -len(suffix)]
        return service

    def _busy_infra_without_failure(self, service: str, metric: str, timestamp: int, series: list[MetricSeries], findings: list[AnomalyFinding]) -> bool:
        if not _is_busy_infra_metric(metric):
            return False
        service = self._canonical_service(service)
        service_series = [item for item in series if self._canonical_service(item.service) == service]
        normal, _ = _normal_traffic_growth_decision(
            service_series,
            self.detection_window_seconds,
            self.drift_min_points - 1,
            self.min_tail_anomaly_buckets,
            self.min_relative_change_ratio,
            self.min_absolute_change,
        )
        return normal and not self._failure_signal_increased(service, timestamp, series, findings)

    def _failure_signal_increased(self, service: str, timestamp: int, series: list[MetricSeries], findings: list[AnomalyFinding]) -> bool:
        if any(
            self._canonical_service(finding.service) == service
            and finding.timestamp == timestamp
            and (_is_error_metric(finding.metric) or _is_oom_metric(finding.metric))
            for finding in findings
        ):
            return True
        return any(
            self._canonical_service(metric.service) == service
            and (
                (_is_error_metric(metric.metric) or _is_oom_metric(metric.metric))
                and _robust_score_at(metric, timestamp) >= self.drift_score_threshold
                or "ready_pods" in metric.metric and _decreased_at(metric, timestamp, self.drift_score_threshold)
            )
            for metric in series
        )


def _is_log_metric(metric: str) -> bool:
    return metric.startswith("log_template_count_")


def _is_context_metric(metric: str) -> bool:
    return "request_rate" in metric or "latency" in metric or _is_error_metric(metric)


def _is_busy_infra_metric(metric: str) -> bool:
    return "cpu" in metric or "memory" in metric or "disk" in metric


def _is_error_metric(metric: str) -> bool:
    return "error_rate" in metric or "error_ratio" in metric or "bad_ratio" in metric


def _is_oom_metric(metric: str) -> bool:
    return "oom" in metric


def _metric_priority(metric: str) -> int:
    if _is_error_metric(metric):
        return 2
    if _is_busy_infra_metric(metric) or _is_oom_metric(metric):
        return 1
    return 0


def _robust_score_at(metric: MetricSeries, timestamp: int) -> float:
    values = [point.value for point in metric.points]
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= timestamp), len(metric.points) - 1)
    return robust_score(values[:index], [values[index]]) if index >= 4 else 0.0


def _decreased_at(metric: MetricSeries, timestamp: int, threshold: float) -> bool:
    values = [point.value for point in metric.points]
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= timestamp), len(metric.points) - 1)
    return index >= 4 and values[index] < median(values[:index]) and robust_score(values[:index], [values[index]]) >= threshold


def _tail_indexes(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> range:
    if not metric.points:
        return range(0)
    if not detection_window_seconds:
        return range(start, len(metric.points))
    cutoff = metric.points[-1].timestamp - detection_window_seconds
    first = next((index for index, point in enumerate(metric.points) if point.timestamp >= cutoff), len(metric.points))
    return range(max(start, first), len(metric.points))
