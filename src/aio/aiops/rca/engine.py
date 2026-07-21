#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import defaultdict
import math

from aiops.anomaly.stats import robust_score
from aiops.rca.graph import GraphTraversalRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig, graph_hyperparameters: dict[str, float], combined_hyperparameters: dict[str, float]):
        self.config = config
        self.ranker_weights = combined_hyperparameters["ranker_weights"]
        self.rrf_k = combined_hyperparameters["rrf_k"]
        self.drift_min_points = int(combined_hyperparameters["drift_min_points"])
        self.drift_score_threshold = float(combined_hyperparameters["drift_score_threshold"])
        self.detection_window_seconds = int(combined_hyperparameters["detection_window_seconds"]) or None
        self.canonical_service_suffixes = tuple(combined_hyperparameters["canonical_service_suffixes"])
        self.metric_aliases = combined_hyperparameters["metric_aliases"]
        self.graph = GraphTraversalRca(
            config,
            damping=graph_hyperparameters["damping"],
            pagerank_weight=graph_hyperparameters["pagerank_weight"],
            timestamp_weight=graph_hyperparameters["timestamp_weight"],
        )

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int) -> RcaResult:
        root_findings = [
            finding.model_copy(update={"service": self._canonical_service(finding.service)})
            if finding.service != "global"
            else finding
            for finding in findings
            if (finding.service == "global" or not self._excluded_root_cause(finding.service))
            and not _is_context_metric(finding.metric)
            and not self._busy_infra_without_failure(finding.service, finding.metric, finding.timestamp, series, findings)
        ]
        if not root_findings:
            return RcaResult(anomalies=findings)
        rca_series = [metric for metric in series if not _is_context_metric(metric.metric)]
        graph_scores = self.graph.rank_services(root_findings)
        earliest_scores = self._earliest_drift_scores(rca_series)
        correlation_scores = self._correlation_scores(rca_series, root_findings)
        service_scores = self._weighted_rrf(
            {
                "graph": graph_scores,
                "earliest_drift": earliest_scores,
                "correlation": correlation_scores,
            }
        )
        anomaly_services = {finding.service for finding in root_findings if finding.service != "global"}

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in root_findings:
            if finding.service == "global":
                continue
            if _is_log_metric(finding.metric) or _is_context_metric(finding.metric):
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
        for service, metric, score in self._drift_metrics(rca_series, series, findings):
            metrics_by_service[service].append((metric, score, "drift"))

        candidates: list[RootCauseCandidate] = []
        for service, score in sorted(service_scores.items(), key=lambda item: item[1], reverse=True):
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
                        f"weighted_rrf_score={score:.3f}",
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                )
            )
            if len(candidates) >= top_k:
                break
        return RcaResult(anomalies=findings, root_causes=candidates)

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
        for index in _tail_indexes(metric, self.detection_window_seconds, self.drift_min_points - 1):
            if robust_score(values[:index], [values[index]]) >= self.drift_score_threshold:
                return index
        return None

    def _drift_metrics(self, series: list[MetricSeries], all_series: list[MetricSeries], findings: list[AnomalyFinding]) -> list[tuple[str, str, float]]:
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
                if self._busy_infra_without_failure(metric.service, metric.metric, metric.points[index].timestamp, all_series, findings):
                    continue
                rows.append((self._canonical_service(metric.service), metric.metric, score))
        return rows

    def _correlation_scores(self, series: list[MetricSeries], findings: list[AnomalyFinding]) -> dict[str, float]:
        primary = self._primary_series(series, findings)
        if primary is None:
            return {}
        scores: dict[str, float] = {}
        primary_values = [point.value for point in primary.points]
        for metric in series:
            if metric.service == "global" or self._excluded_root_cause(metric.service):
                continue
            score = abs(self._pearson(primary_values, [point.value for point in metric.points]))
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
        return self._request_rate_increased(service, timestamp, series) and not self._failure_signal_increased(service, timestamp, series, findings)

    def _request_rate_increased(self, service: str, timestamp: int, series: list[MetricSeries]) -> bool:
        return any(
            self._canonical_service(metric.service) == service and "request_rate" in metric.metric and _robust_score_at(metric, timestamp) >= self.drift_score_threshold
            for metric in series
        )

    def _failure_signal_increased(self, service: str, timestamp: int, series: list[MetricSeries], findings: list[AnomalyFinding]) -> bool:
        if any(
            self._canonical_service(finding.service) == service
            and finding.timestamp == timestamp
            and (_is_failure_metric(finding.metric) or _is_oom_metric(finding.metric))
            for finding in findings
        ):
            return True
        return any(
            self._canonical_service(metric.service) == service
            and (_is_failure_metric(metric.metric) or _is_oom_metric(metric.metric))
            and _robust_score_at(metric, timestamp) >= self.drift_score_threshold
            for metric in series
        )


def _is_log_metric(metric: str) -> bool:
    return metric.startswith("log_template_count_")


def _is_context_metric(metric: str) -> bool:
    return "request_rate" in metric or "latency" in metric


def _is_busy_infra_metric(metric: str) -> bool:
    return "cpu" in metric or "memory" in metric or "disk" in metric


def _is_error_metric(metric: str) -> bool:
    return "error_rate" in metric or "error_ratio" in metric


def _is_failure_metric(metric: str) -> bool:
    return _is_error_metric(metric) or "ready_pods" in metric


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


def _tail_indexes(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> range:
    if not metric.points:
        return range(0)
    if not detection_window_seconds:
        return range(start, len(metric.points))
    cutoff = metric.points[-1].timestamp - detection_window_seconds
    first = next((index for index, point in enumerate(metric.points) if point.timestamp >= cutoff), len(metric.points))
    return range(max(start, first), len(metric.points))
