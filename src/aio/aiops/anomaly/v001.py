from __future__ import annotations

from collections import defaultdict
from math import sqrt

from aiops.anomaly.stats import mean, robust_score, stdev
from aiops.schemas import AnomalyFinding, MetricSeries


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
        smoothed: list[float] = []
        current = values[0]
        for value in values:
            current = self.alpha * value + (1 - self.alpha) * current
            smoothed.append(current)

        if self.seasonal_period <= 1 or len(values) < self.seasonal_period * 2:
            return [value - smooth for value, smooth in zip(values, smoothed)]

        seasonal = []
        for index, value in enumerate(values):
            same_slot = values[index % self.seasonal_period : index : self.seasonal_period]
            seasonal.append(mean(same_slot) if same_slot else 0.0)
        return [value - smooth - season for value, smooth, season in zip(values, smoothed, seasonal)]

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
            metric_scores = [self._metric_score(metric) for metric in metrics]
            service_score = sqrt(sum(score * score for score in metric_scores))
            if service_score < self.score_threshold:
                continue
            top_metric = max(metrics, key=self._metric_score)
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

    def _metric_score(self, metric: MetricSeries) -> float:
        values = [point.value for point in metric.points]
        if len(values) < self.min_points:
            return 0.0
        return robust_score(values[:-1], values[-1:])


class NormBocpdDetector:
    def __init__(self, score_threshold: float, min_points: int):
        self.score_threshold = score_threshold
        self.min_points = min_points

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        aligned = [metric for metric in series if len(metric.points) >= self.min_points]
        if not aligned:
            return []

        length = min(len(metric.points) for metric in aligned)
        normalized = [self._normalize([point.value for point in metric.points[-length:]]) for metric in aligned]
        norms = [sqrt(sum(values[index] ** 2 for values in normalized)) for index in range(length)]
        midpoint = max(4, length // 2)
        score = robust_score(norms[:midpoint], norms[midpoint:])
        if score < self.score_threshold:
            return []

        timestamp = aligned[0].points[-1].timestamp
        return [
            AnomalyFinding(
                algorithm="norm_bocpd",
                service="global",
                metric="multivariate_norm",
                signal_id="global_multivariate_norm",
                score=score,
                timestamp=timestamp,
            )
        ]

    def _normalize(self, values: list[float]) -> list[float]:
        low = min(values)
        high = max(values)
        if high == low:
            return [0.0 for _ in values]
        return [(value - low) / (high - low) for value in values]


class V001AnomalyEngine:
    def __init__(
        self,
        ewma_alpha: float,
        ewma_z_threshold: float,
        isolation_score_threshold: float,
        bocpd_score_threshold: float,
        min_points: int,
        seasonal_period: int,
    ):
        self.ewma_stl = EwmaStlDetector(ewma_alpha, ewma_z_threshold, min_points, seasonal_period)
        self.isolation_forest = ServiceIsolationForestDetector(isolation_score_threshold, min_points)
        self.norm_bocpd = NormBocpdDetector(bocpd_score_threshold, min_points)

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        return [
            *self.ewma_stl.evaluate(series),
            *self.isolation_forest.evaluate(series),
            *self.norm_bocpd.evaluate(series),
        ]
