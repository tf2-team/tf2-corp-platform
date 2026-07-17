from __future__ import annotations

from aiops.anomaly.stats import robust_score
from aiops.schemas import MetricSeries


class RobustScoreRca:
    def rank(self, series: list[MetricSeries], anomaly_timestamp: int | None) -> dict[str, float]:
        scores: dict[str, float] = {}
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < 5:
                continue
            index = self._anomaly_index(metric, anomaly_timestamp)
            score = robust_score(values[:index], values[index:])
            if score:
                scores[f"{metric.service}:{metric.metric}"] = score
        return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))

    def _anomaly_index(self, metric: MetricSeries, anomaly_timestamp: int | None) -> int:
        if anomaly_timestamp is not None:
            for index, point in enumerate(metric.points):
                if point.timestamp >= anomaly_timestamp:
                    return max(1, index)
        return max(1, len(metric.points) - 1)
