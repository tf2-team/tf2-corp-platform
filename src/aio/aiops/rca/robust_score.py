from __future__ import annotations

import os

from aiops.schemas import MetricSeries

os.environ.setdefault("MPLCONFIGDIR", "/tmp")


class RobustScoreRca:
    def __init__(self, fallback_split_ratio: float):
        self.fallback_split_ratio = fallback_split_ratio

    def rank(self, series: list[MetricSeries], anomaly_timestamp: int | None) -> dict[str, float]:
        if not series:
            return {}

        from baro.root_cause_analysis import robust_scorer

        frame = self._to_frame(series)
        anomaly_index = self._anomaly_index(series[0], anomaly_timestamp)
        result = robust_scorer(frame, anomalies=[anomaly_index])
        ranks = result["ranks"]
        score_by_metric = dict(result.get("scores", []))
        scores: dict[str, float] = {}
        for index, metric_name in enumerate(ranks):
            if "_" not in metric_name:
                continue
            service, metric = metric_name.split("_", 1)
            scores[f"{service}:{metric}"] = float(score_by_metric.get(metric_name, len(ranks) - index))
        return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))

    def _to_frame(self, series: list[MetricSeries]):
        import pandas as pd

        length = min(len(metric.points) for metric in series)
        data: dict[str, list[float | int]] = {"time": [point.timestamp for point in series[0].points[-length:]]}
        for metric in series:
            data[f"{metric.service}_{metric.metric}"] = [point.value for point in metric.points[-length:]]
        return pd.DataFrame(data)

    def _anomaly_index(self, metric: MetricSeries, anomaly_timestamp: int | None) -> int:
        if anomaly_timestamp is None:
            return max(1, len(metric.points) // 2)
        for index, point in enumerate(metric.points):
            if point.timestamp >= anomaly_timestamp:
                if index >= int(len(metric.points) * self.fallback_split_ratio):
                    return max(1, len(metric.points) // 2)
                return max(1, index)
        return max(1, len(metric.points) - 1)
