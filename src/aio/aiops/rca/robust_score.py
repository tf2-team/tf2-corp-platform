from __future__ import annotations

from aiops.anomaly.stats import robust_score
from aiops.schemas import MetricSeries


class RobustScoreRca:
    def rank(self, series: list[MetricSeries], anomaly_timestamp: int | None) -> dict[str, float]:
        scores: dict[str, float] = {}
        for metric in series:
            baseline = [point.value for point in metric.points if anomaly_timestamp is None or point.timestamp < anomaly_timestamp]
            post = [point.value for point in metric.points if anomaly_timestamp is None or point.timestamp >= anomaly_timestamp]
            score = robust_score(baseline, post)
            if score > 0:
                scores[f"{metric.service}:{metric.metric}"] = score
        return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))
