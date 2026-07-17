from __future__ import annotations

from collections import defaultdict

from aiops.rca.graph import GraphTraversalRca
from aiops.rca.robust_score import RobustScoreRca
from aiops.schemas import AnomalyFinding, MetricSeries, RcaResult, RootCauseCandidate, RuntimeConfig


class V001RcaEngine:
    def __init__(self, config: RuntimeConfig):
        self.graph = GraphTraversalRca(config)
        self.robust_score = RobustScoreRca()

    def rank(self, findings: list[AnomalyFinding], series: list[MetricSeries], top_k: int) -> RcaResult:
        anomaly_timestamp = min((finding.timestamp for finding in findings), default=None)
        service_scores = self.graph.rank_services(findings)

        metrics_by_service: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for finding in findings:
            if finding.service == "global":
                continue
            metrics_by_service[finding.service].append((finding.metric, finding.score, "anomaly"))
            service_scores[finding.service] = max(service_scores.get(finding.service, 0.0), finding.score)
        for full_name, score in self.robust_score.rank(series, anomaly_timestamp).items():
            service, metric = full_name.split(":", 1)
            metrics_by_service[service].append((metric, score, "robust"))
            service_scores[service] = max(service_scores.get(service, 0.0), score)

        candidates: list[RootCauseCandidate] = []
        for service, score in sorted(service_scores.items(), key=lambda item: item[1], reverse=True)[:top_k]:
            metric_scores = sorted(metrics_by_service[service], key=lambda item: item[1], reverse=True)[:top_k]
            metrics = list(dict.fromkeys(metric for metric, _, _ in metric_scores))
            candidates.append(
                RootCauseCandidate(
                    service=service,
                    score=score,
                    root_cause_metrics=metrics,
                    evidence=[
                        f"graph_score={service_scores.get(service, 0.0):.3f}",
                        *[f"{metric} {source}_score={metric_score:.3f}" for metric, metric_score, source in metric_scores],
                    ],
                )
            )
        return RcaResult(anomalies=findings, root_causes=candidates)
