from __future__ import annotations

from collections import defaultdict

from aiops.rca.graph import GraphTraversalRca
from aiops.rca.robust_score import RobustScoreRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig, graph_hyperparameters: dict[str, float], combined_hyperparameters: dict[str, float]):
        self.config = config
        self.graph_weight = combined_hyperparameters["graph_weight"]
        self.robust_weight = combined_hyperparameters["robust_weight"]
        self.graph = GraphTraversalRca(
            config,
            damping=graph_hyperparameters["damping"],
            pagerank_weight=graph_hyperparameters["pagerank_weight"],
            timestamp_weight=graph_hyperparameters["timestamp_weight"],
        )
        self.robust_score = RobustScoreRca()

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int, bocpd_findings: list[AnomalyFinding] | None = None) -> RcaResult:
        root_findings = [finding for finding in findings if finding.service == "global" or not self._excluded_root_cause(finding.service)]
        bocpd_root_findings = [finding for finding in (bocpd_findings or []) if finding.service == "global" or not self._excluded_root_cause(finding.service)]
        bocpd_timestamp = min((finding.timestamp for finding in bocpd_root_findings), default=None)
        graph_scores = self.graph.rank_services(root_findings or bocpd_root_findings)
        robust_scores = self._robust_service_scores(series, bocpd_timestamp)
        service_scores = self._combine_scores(graph_scores, robust_scores)

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in root_findings:
            if finding.service == "global":
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
        for finding in bocpd_root_findings:
            if finding.service == "global":
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "bocpd"))
        for full_name, score in self.robust_score.rank(series, bocpd_timestamp).items():
            service, metric = full_name.split(":", 1)
            if self._excluded_root_cause(service):
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
                        f"combined_score={score:.3f}",
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                )
            )
            if len(candidates) >= top_k:
                break
        return RcaResult(anomalies=[*findings, *(bocpd_findings or [])], root_causes=candidates)

    def _robust_service_scores(self, series: list[MetricSeries], anomaly_timestamp: int | None) -> dict[str, float]:
        scores: dict[str, float] = {}
        for full_name, score in self.robust_score.rank(series, anomaly_timestamp).items():
            service, _ = full_name.split(":", 1)
            if not self._excluded_root_cause(service):
                scores[service] = max(scores.get(service, 0.0), score)
        return scores

    def _combine_scores(self, graph_scores: dict[str, float], robust_scores: dict[str, float]) -> dict[str, float]:
        services = set(graph_scores) | set(robust_scores)
        max_graph = max(graph_scores.values(), default=0.0) or 1.0
        max_robust = max(robust_scores.values(), default=0.0) or 1.0
        return {
            service: self.graph_weight * (graph_scores.get(service, 0.0) / max_graph) + self.robust_weight * (robust_scores.get(service, 0.0) / max_robust)
            for service in services
        }

    def _excluded_root_cause(self, service: str) -> bool:
        services = {item.name: item for item in self.config.topology.services}
        item = services.get(service)
        if item is None:
            return False
        if item.flow in self.config.policy.non_actionable_flows:
            return True
        return service in self.config.policy.protected_targets and service != "postgresql"
