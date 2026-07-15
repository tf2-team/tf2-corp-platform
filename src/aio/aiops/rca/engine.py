from __future__ import annotations

from collections import defaultdict

from aiops.rca.graph import GraphTraversalRca
from aiops.rca.robust_score import RobustScoreRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig, fallback_split_ratio: float):
        self.graph = GraphTraversalRca(config)
        self.robust_score = RobustScoreRca(fallback_split_ratio)

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int) -> RcaResult:
        anomaly_timestamp = min((finding.timestamp for finding in findings), default=None)
        service_scores = self.graph.rank_services(findings)
        metric_scores = self.robust_score.rank(series, anomaly_timestamp)

        metrics_by_service: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for full_name, score in metric_scores.items():
            service, metric = full_name.split(":", 1)
            metrics_by_service[service].append((metric, score))
            service_scores[service] = max(service_scores.get(service, 0.0), score)

        candidates: list[RootCauseCandidate] = []
        for service, score in sorted(service_scores.items(), key=lambda item: item[1], reverse=True)[:top_k]:
            metrics = [metric for metric, _ in sorted(metrics_by_service[service], key=lambda item: item[1], reverse=True)[:top_k]]
            candidates.append(
                RootCauseCandidate(
                    service=service,
                    score=score,
                    root_cause_metrics=metrics,
                    evidence=[
                        f"graph_score={service_scores.get(service, 0.0):.3f}",
                        *[f"{metric} robust_score={metric_score:.3f}" for metric, metric_score in metrics_by_service[service][:top_k]],
                    ],
                )
            )
        return RcaResult(anomalies=findings, root_causes=candidates)
