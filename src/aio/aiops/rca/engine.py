from __future__ import annotations

from collections import defaultdict
import math

from aiops.anomaly.stats import robust_score
from aiops.rca.graph import GraphTraversalRca
from aiops.rca.robust_score import RobustScoreRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig, graph_hyperparameters: dict[str, float], combined_hyperparameters: dict[str, float]):
        self.config = config
        self.ranker_weights = combined_hyperparameters["ranker_weights"]
        self.rrf_k = combined_hyperparameters["rrf_k"]
        self.graph = GraphTraversalRca(
            config,
            damping=graph_hyperparameters["damping"],
            pagerank_weight=graph_hyperparameters["pagerank_weight"],
            timestamp_weight=graph_hyperparameters["timestamp_weight"],
        )
        self.robust_score = RobustScoreRca()

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int) -> RcaResult:
        root_findings = [finding for finding in findings if finding.service == "global" or not self._excluded_root_cause(finding.service)]
        anomaly_timestamp = min((finding.timestamp for finding in root_findings), default=None)
        graph_scores = self.graph.rank_services(root_findings)
        robust_scores = self._robust_service_scores(series, anomaly_timestamp)
        earliest_scores = self._earliest_drift_scores(series)
        correlation_scores = self._correlation_scores(series, root_findings)
        service_scores = self._weighted_rrf(
            {
                "graph": graph_scores,
                "robust": robust_scores,
                "earliest_drift": earliest_scores,
                "correlation": correlation_scores,
            }
        )

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in root_findings:
            if finding.service == "global":
                continue
            if _is_log_metric(finding.metric):
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
        for full_name, score in self.robust_score.rank(series, anomaly_timestamp).items():
            service, metric = full_name.split(":", 1)
            if self._excluded_root_cause(service) or _is_log_metric(metric):
                continue
            metrics_by_service[service].append((metric, score, "robust"))

        candidates: list[RootCauseCandidate] = []
        for service, score in sorted(service_scores.items(), key=lambda item: item[1], reverse=True):
            if self._excluded_root_cause(service):
                continue
            if not metrics_by_service[service]:
                continue
            metric_scores = sorted(metrics_by_service[service], key=lambda item: item[1], reverse=True)[:top_k]
            metrics = list(dict.fromkeys(metric for metric, _, _ in metric_scores))
            candidates.append(
                RootCauseCandidate(
                    service=service,
                    score=score,
                    root_cause_metrics=metrics,
                    evidence=[
                        f"graph_score={graph_scores.get(service, 0.0):.3f}",
                        f"robust_score={robust_scores.get(service, 0.0):.3f}",
                        f"earliest_drift_score={earliest_scores.get(service, 0.0):.3f}",
                        f"correlation_score={correlation_scores.get(service, 0.0):.3f}",
                        f"weighted_rrf_score={score:.3f}",
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                )
            )
            break
        return RcaResult(anomalies=findings, root_causes=candidates)

    def _robust_service_scores(self, series: list[MetricSeries], anomaly_timestamp: int | None) -> dict[str, float]:
        scores: dict[str, float] = {}
        for full_name, score in self.robust_score.rank(series, anomaly_timestamp).items():
            service, _ = full_name.split(":", 1)
            if not self._excluded_root_cause(service):
                scores[service] = max(scores.get(service, 0.0), score)
        return scores

    def _earliest_drift_scores(self, series: list[MetricSeries]) -> dict[str, float]:
        drift_indexes: dict[str, int] = {}
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < 5:
                continue
            index = self._first_drift_index(values)
            if index is not None and not self._excluded_root_cause(metric.service):
                drift_indexes[metric.service] = min(drift_indexes.get(metric.service, index), index)
        if not drift_indexes:
            return {}
        latest = max(drift_indexes.values()) or 1
        return {service: 1.0 - (index / latest) for service, index in drift_indexes.items()}

    def _first_drift_index(self, values: list[float]) -> int | None:
        for index in range(4, len(values)):
            if robust_score(values[:index], [values[index]]) >= 3.0:
                return index
        return None

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
            scores[metric.service] = max(scores.get(metric.service, 0.0), score)
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


def _is_log_metric(metric: str) -> bool:
    return metric.startswith("log_template_count_")
