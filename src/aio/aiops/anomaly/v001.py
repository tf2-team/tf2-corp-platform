from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import os
import warnings

from aiops.anomaly.stats import mean, robust_score, stdev
from aiops.schemas import AnomalyFinding, MetricSeries

os.environ.setdefault("MPLCONFIGDIR", "/tmp")


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
        from statsmodels.tsa.api import SimpleExpSmoothing
        from statsmodels.tsa.seasonal import STL

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="divide by zero encountered in log", category=RuntimeWarning)
            smoothed = SimpleExpSmoothing(values, initialization_method="estimated").fit(smoothing_level=self.alpha, optimized=False).fittedvalues
        if self.seasonal_period <= 1 or len(values) < self.seasonal_period * 2:
            return [value - smooth for value, smooth in zip(values, smoothed)]
        seasonal = STL(values, period=self.seasonal_period, robust=True).fit().seasonal
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
            eligible = [metric for metric in metrics if len(metric.points) >= self.min_points]
            if len(eligible) < 2:
                continue
            # ponytail: preserve existing threshold scale; recalibrate config if sklearn score is used directly.
            scores = [score * 10.0 for score in self._scores(eligible)]
            service_score = max(scores)
            if service_score < self.score_threshold:
                continue
            rows = self._normalized_rows(self._rows(eligible))
            latest_values = rows[-1]
            baseline_values = rows[-self.min_points : -1]
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

        rows = self._normalized_rows(self._rows(metrics))
        model = IsolationForest(contamination="auto", random_state=0).fit(rows[:-1])
        return [-score for score in model.score_samples([rows[-1]])]

    def _rows(self, metrics: list[MetricSeries]) -> list[list[float]]:
        length = min(len(metric.points) for metric in metrics)
        return [[metric.points[index].value for metric in metrics] for index in range(-length, 0)]

    def _normalized_rows(self, rows: list[list[float]]) -> list[list[float]]:
        if not rows:
            return []
        columns = list(zip(*rows))
        normalized_columns = []
        for column in columns:
            low = min(column)
            high = max(column)
            spread = high - low
            normalized_columns.append([0.0 if spread == 0 else (value - low) / spread for value in column])
        return [list(row) for row in zip(*normalized_columns)]


class BaroBocpdDetector:
    def __init__(
        self,
        score_threshold: float,
        min_points: int,
        min_changed_metrics: int = 2,
        hazard_lambda: int = 50,
        max_metrics: int = 8,
        max_points: int = 120,
    ):
        self.score_threshold = score_threshold
        self.min_points = min_points
        self.min_changed_metrics = min_changed_metrics
        self.hazard_lambda = hazard_lambda
        self.max_metrics = max_metrics
        self.max_points = max_points

    def evaluate(self, series: list[MetricSeries], bocpd: Callable[[list[list[float]]], list[int]] | None = None) -> list[AnomalyFinding]:
        scored: list[tuple[MetricSeries, float]] = []
        for metric in series:
            if not self._is_bocpd_metric(metric.metric):
                continue
            values = [point.value for point in metric.points]
            if len(values) < self.min_points:
                continue
            score = robust_score(values[:-1], [values[-1]])
            if score >= self.score_threshold:
                scored.append((metric, score))

        if len(scored) < self.min_changed_metrics:
            return []
        selected = sorted(scored, key=lambda item: item[1], reverse=True)[: self.max_metrics]
        rows = self._normalized_rows([metric for metric, _ in selected])
        changepoints = (bocpd or self._baro_bocpd)(rows)
        if not changepoints:
            return []
        return [
            AnomalyFinding(
                algorithm="baro_bocpd",
                service=metric.service,
                metric=metric.metric,
                signal_id=metric.signal_id,
                score=score,
                timestamp=metric.points[-1].timestamp,
            )
            for metric, score in selected
        ]

    def _normalized_rows(self, metrics: list[MetricSeries]) -> list[list[float]]:
        length = min(self.max_points, *(len(metric.points) for metric in metrics))
        rows = [[metric.points[index].value for metric in metrics] for index in range(-length, 0)]
        return ServiceIsolationForestDetector(self.score_threshold, self.min_points)._normalized_rows(rows)

    def _is_bocpd_metric(self, metric: str) -> bool:
        return "latency" in metric or "error_rate" in metric

    def _baro_bocpd(self, rows: list[list[float]]) -> list[int]:
        from functools import partial

        from baro._bocpd import MultivariateT, constant_hazard, online_changepoint_detection
        from baro.utility import find_cps

        _, maxes = online_changepoint_detection(rows, partial(constant_hazard, self.hazard_lambda), MultivariateT(dims=len(rows[0])))
        return [point for point, _ in find_cps(maxes)]


class V001AnomalyEngine:
    def __init__(
        self,
        ewma_alpha: float,
        ewma_z_threshold: float,
        isolation_score_threshold: float,
        min_points: int,
        seasonal_period: int,
        algorithm_weights: dict[str, float],
        weighted_score_threshold: float,
        bocpd_min_changed_metrics: int,
        bocpd_hazard_lambda: int = 50,
        bocpd_max_metrics: int = 8,
        bocpd_max_points: int = 120,
        single_algorithm_min_normalized_score: float = 2.0,
    ):
        self.algorithm_weights = algorithm_weights
        self.weighted_score_threshold = weighted_score_threshold
        self.single_algorithm_min_normalized_score = single_algorithm_min_normalized_score
        self.thresholds = {
            "ewma_stl": ewma_z_threshold,
            "isolation_forest": isolation_score_threshold,
        }
        self.ewma_stl = EwmaStlDetector(ewma_alpha, ewma_z_threshold, min_points, seasonal_period)
        self.isolation_forest = ServiceIsolationForestDetector(isolation_score_threshold, min_points)
        self.baro_bocpd = BaroBocpdDetector(isolation_score_threshold, min_points, bocpd_min_changed_metrics, bocpd_hazard_lambda, bocpd_max_metrics, bocpd_max_points)

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        return self._weighted_sum([*self.ewma_stl.evaluate(series), *self.isolation_forest.evaluate(series)])

    def evaluate_bocpd(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        return self.baro_bocpd.evaluate(series)

    def _weighted_sum(self, findings: list[AnomalyFinding]) -> list[AnomalyFinding]:
        grouped: dict[tuple[str, str, str], list[AnomalyFinding]] = defaultdict(list)
        for finding in findings:
            grouped[(finding.service, finding.metric, finding.signal_id)].append(finding)

        combined: list[AnomalyFinding] = []
        for (_, _, _), items in grouped.items():
            normalized_scores = [item.score / self.thresholds[item.algorithm] for item in items]
            score = sum(self.algorithm_weights[item.algorithm] * min(normalized_score, 1.0) for item, normalized_score in zip(items, normalized_scores))
            if len(items) == 1 and normalized_scores[0] >= self.single_algorithm_min_normalized_score:
                score = max(score, self.weighted_score_threshold)
            if score < self.weighted_score_threshold:
                continue
            top = max(items, key=lambda item: item.score)
            combined.append(
                AnomalyFinding(
                    algorithm="weighted_sum",
                    service=top.service,
                    metric=top.metric,
                    signal_id=top.signal_id,
                    score=score,
                    timestamp=top.timestamp,
                )
            )
        return sorted(combined, key=lambda item: item.score, reverse=True)
