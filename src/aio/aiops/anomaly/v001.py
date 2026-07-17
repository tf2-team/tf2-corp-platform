from __future__ import annotations

from collections import defaultdict
import os

from aiops.anomaly.stats import mean, stdev
from aiops.schemas import AnomalyFinding, MetricSeries

os.environ.setdefault("MPLCONFIGDIR", "/tmp")
SMOOTHING_EPSILON = 0.00001


class EwmaStlDetector:
    def __init__(self, alpha: float, z_threshold: float, min_points: int, seasonal_period: int):
        self.alpha = alpha
        self.z_threshold = z_threshold
        self.min_points = min_points
        self.seasonal_period = seasonal_period

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.min_points:
                continue
            residuals = self._residuals(values)
            baseline = residuals[: -1]
            score = abs(residuals[-1] - mean(baseline)) / (stdev(baseline) or 1.0)
            if score >= self.z_threshold:
                findings.append(self._finding(metric, "ewma_stl", score, metric.points[-1].timestamp))
        return findings

    def _residuals(self, values: list[float]) -> list[float]:
        from statsmodels.tsa.seasonal import STL

        smoothed = self._ewma(values)
        if self.seasonal_period <= 1 or len(values) < self.seasonal_period * 2:
            return [value - smooth for value, smooth in zip(values, smoothed)]
        seasonal = STL(values, period=self.seasonal_period, robust=True).fit().seasonal
        return [value - smooth - season for value, smooth, season in zip(values, smoothed, seasonal)]

    def _ewma(self, values: list[float]) -> list[float]:
        smoothed = [values[0]]
        for value in values[1:]:
            smoothed.append(self.alpha * value + (1 - self.alpha) * smoothed[-1] + SMOOTHING_EPSILON)
        return smoothed

    def _finding(self, metric: MetricSeries, algorithm: str, score: float, timestamp: int) -> AnomalyFinding:
        return AnomalyFinding(
            algorithm=algorithm,
            service=metric.service,
            metric=metric.metric,
            signal_id=metric.signal_id,
            score=score,
            timestamp=timestamp,
        )


class ServiceIsolationForestDetector:
    def __init__(self, score_threshold: float, min_points: int):
        self.score_threshold = score_threshold
        self.min_points = min_points

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        by_service: dict[str, list[MetricSeries]] = defaultdict(list)
        for metric in series:
            by_service[metric.service].append(metric)

        findings: list[AnomalyFinding] = []
        for service, metrics in by_service.items():
            if len(metrics) < 2:
                continue
            eligible = [metric for metric in metrics if len(metric.points) >= self.min_points]
            if len(eligible) < 2:
                continue
            # ponytail: preserve existing threshold scale; recalibrate config if sklearn score is used directly.
            scores = [score * 10.0 for score in self._scores(eligible)]
            service_score = max(scores)
            if service_score < self.score_threshold:
                continue
            latest_values = [metric.points[-1].value for metric in eligible]
            baseline_values = [[metric.points[index].value for metric in eligible] for index in range(-self.min_points, -1)]
            baseline_center = [mean([row[index] for row in baseline_values]) for index in range(len(eligible))]
            top_metric = max(eligible, key=lambda metric: abs(latest_values[eligible.index(metric)] - baseline_center[eligible.index(metric)]))
            findings.append(
                AnomalyFinding(
                    algorithm="isolation_forest",
                    service=service,
                    metric=top_metric.metric,
                    signal_id=top_metric.signal_id,
                    score=service_score,
                    timestamp=top_metric.points[-1].timestamp,
                )
            )
        return findings

    def _scores(self, metrics: list[MetricSeries]) -> list[float]:
        from sklearn.ensemble import IsolationForest

        length = min(len(metric.points) for metric in metrics)
        rows = [[metric.points[index].value for metric in metrics] for index in range(-length, 0)]
        model = IsolationForest(contamination="auto", random_state=0).fit(rows[:-1])
        return [-score for score in model.score_samples([rows[-1]])]


class V001AnomalyEngine:
    def __init__(
        self,
        ewma_alpha: float,
        ewma_z_threshold: float,
        isolation_score_threshold: float,
        min_points: int,
        seasonal_period: int,
    ):
        self.ewma_stl = EwmaStlDetector(ewma_alpha, ewma_z_threshold, min_points, seasonal_period)
        self.isolation_forest = ServiceIsolationForestDetector(isolation_score_threshold, min_points)

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        return [
            *self.ewma_stl.evaluate(series),
            *self.isolation_forest.evaluate(series),
        ]
