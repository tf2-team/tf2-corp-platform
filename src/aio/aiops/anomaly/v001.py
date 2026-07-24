#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import defaultdict
import hashlib
import logging
import os
from pathlib import Path
import re
import warnings

from aiops.anomaly.stats import mean, median, robust_score, stdev
from aiops.schemas import AnomalyFinding, MetricSeries
from aiops.shared.tail import evaluate_tail_change, fixed_baseline_and_tail, median3, metric_group, normal_traffic_growth_decision, point_changed, series_step_seconds, tail_increase_timestamps, tail_indexes

logger = logging.getLogger(__name__)

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
except Exception:  # pragma: no cover - drain3 is optional until the env is refreshed.
    TemplateMiner = None
    TemplateMinerConfig = None


class EwmaStlDetector:
    def __init__(self, alpha: float, z_threshold: float, min_points: int, seasonal_period: int, detection_window_seconds: int | None = None):
        self.alpha = alpha
        self.z_threshold = z_threshold
        self.min_points = min_points
        self.seasonal_period = seasonal_period
        self.detection_window_seconds = detection_window_seconds

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.min_points:
                continue
            residuals = self._residuals(values)
            baseline, indexes = fixed_baseline_and_tail(metric, self.detection_window_seconds, self.min_points - 1, residuals)
            center, spread = mean(baseline), stdev(baseline) or 1.0
            scored = [(abs(residuals[index] - center) / spread, index) for index in indexes]
            score, index = max(scored, default=(0.0, 0))
            if score >= self.z_threshold:
                findings.append(self._finding(metric, "ewma_stl", score, metric.points[index].timestamp))
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


class RobustDriftDetector:
    def __init__(self, score_threshold: float, min_points: int, min_baseline_points: int, detection_window_seconds: int | None = None):
        self.score_threshold = score_threshold
        self.min_points = min_points
        self.min_baseline_points = min_baseline_points
        self.detection_window_seconds = detection_window_seconds

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.min_points:
                continue
            baseline, indexes = fixed_baseline_and_tail(metric, self.detection_window_seconds, self.min_baseline_points, values)
            scored = [
                (robust_score(baseline, [values[index]]), index)
                for index in indexes
            ]
            score, index = max(scored, default=(0.0, 0))
            if score >= self.score_threshold:
                findings.append(
                    AnomalyFinding(
                        algorithm="robust_drift",
                        service=metric.service,
                        metric=metric.metric,
                        signal_id=metric.signal_id,
                        score=score,
                        timestamp=metric.points[index].timestamp,
                    )
                )
        return findings


class ServiceIsolationForestDetector:
    def __init__(
        self,
        score_threshold: float,
        min_points: int,
        detection_window_seconds: int | None = None,
        min_tail_anomaly_buckets: dict[str, int] | None = None,
        min_relative_change_ratio: dict[str, float] | None = None,
        min_absolute_change: dict[str, float] | None = None,
    ):
        self.score_threshold = score_threshold
        self.min_points = min_points
        self.detection_window_seconds = detection_window_seconds
        self.min_tail_anomaly_buckets = min_tail_anomaly_buckets or {}
        self.min_relative_change_ratio = min_relative_change_ratio or {}
        self.min_absolute_change = min_absolute_change or {}

    def _min_tail_buckets(self, metric: str) -> int:
        group = metric_group(metric)
        return self.min_tail_anomaly_buckets.get(group, self.min_tail_anomaly_buckets.get("default", 2))

    def _min_relative_ratio(self, metric: str) -> float:
        group = metric_group(metric)
        return self.min_relative_change_ratio.get(group, self.min_relative_change_ratio.get("default", 0.3))

    def _min_absolute_delta(self, metric: str) -> float:
        group = metric_group(metric)
        return self.min_absolute_change.get(group, self.min_absolute_change.get("default", 1.0))

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
            timestamps = self._timestamps(eligible)
            rows = self._rows(eligible, timestamps)
            if len(rows) < self.min_points:
                continue
            cutoff = timestamps[-1] - self.detection_window_seconds if self.detection_window_seconds else None
            first_tail = next((index for index, timestamp in enumerate(timestamps) if cutoff is not None and timestamp >= cutoff), self.min_points)
            tail_indexes = list(range(max(self.min_points, first_tail), len(rows)))
            if not tail_indexes:
                continue
            rows = self._normalized_rows(rows, eligible, tail_indexes[0])
            baseline_rows = rows[: tail_indexes[0]]
            tail_rows = [rows[index] for index in tail_indexes]
            scored = [(score * 10.0, index) for score, index in zip(self._scores(baseline_rows, tail_rows), tail_indexes)]
            service_score, service_index = max(scored, default=(0.0, 0))
            if service_score < self.score_threshold:
                continue
            latest_values = rows[service_index]
            baseline_values = rows[:service_index]
            baseline_center = [mean([row[index] for row in baseline_values]) for index in range(len(eligible))]
            significant_eligible = [
                metric for metric in eligible
                if _is_error_metric(metric.metric) or _is_oom_metric(metric.metric) or evaluate_tail_change(
                    metric,
                    self.detection_window_seconds,
                    self.min_points - 1,
                    self._min_tail_buckets(metric.metric),
                    self._min_relative_ratio(metric.metric),
                    self._min_absolute_delta(metric.metric),
                ).significant
            ]
            candidates = significant_eligible if significant_eligible else eligible
            top_metric = max(candidates, key=lambda metric: abs(latest_values[eligible.index(metric)] - baseline_center[eligible.index(metric)]))
            findings.append(
                AnomalyFinding(
                    algorithm="isolation_forest",
                    service=service,
                    metric=top_metric.metric,
                    signal_id=top_metric.signal_id,
                    score=service_score,
                    timestamp=timestamps[service_index],
                )
            )
        return findings

    def _scores(self, baseline_rows: list[list[float]], scored_rows: list[list[float]]) -> list[float]:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(contamination="auto", random_state=0).fit(baseline_rows)
        return [-score for score in model.score_samples(scored_rows)]

    def _timestamps(self, metrics: list[MetricSeries]) -> list[int]:
        values_by_metric = [{point.timestamp: point.value for point in metric.points} for metric in metrics]
        return sorted(set.intersection(*(set(values) for values in values_by_metric)))

    def _rows(self, metrics: list[MetricSeries], timestamps: list[int] | None = None) -> list[list[float]]:
        values_by_metric = [{point.timestamp: point.value for point in metric.points} for metric in metrics]
        timestamps = timestamps if timestamps is not None else sorted(set.intersection(*(set(values) for values in values_by_metric)))
        return [[values[timestamp] for values in values_by_metric] for timestamp in timestamps]

    def _normalized_rows(self, rows: list[list[float]], metrics: list[MetricSeries] | None = None, baseline_count: int | None = None) -> list[list[float]]:
        if not rows:
            return []
        columns = list(zip(*rows))
        normalized_columns = []
        for index, column in enumerate(columns):
            baseline = column[:baseline_count] if baseline_count is not None else column
            low = min(baseline)
            high = max(baseline)
            min_spread = self._min_absolute_delta(metrics[index].metric) if metrics and index < len(metrics) else 1.0
            spread = max(high - low, min_spread)
            normalized_columns.append([(value - low) / spread for value in column])
        return [list(row) for row in zip(*normalized_columns)]


def _drain3_config(config_path: str | Path):
    config = TemplateMinerConfig()
    path = Path(config_path)
    if path.exists():
        config.load(str(path))
    return config


class LogTemplateMetricBuilder:
    def __init__(
        self,
        config_path: str | Path = "config/drain3.ini",
        bucket_seconds: int = 60,
        history_buckets: int = 8,
        max_templates_per_service: int = 20,
        min_nonzero_buckets: int = 2,
    ):
        self.bucket_seconds = bucket_seconds
        self.history_buckets = history_buckets
        self.max_templates_per_service = max_templates_per_service
        self.min_nonzero_buckets = min_nonzero_buckets
        self.template_miner = TemplateMiner(config=_drain3_config(config_path)) if TemplateMiner is not None and TemplateMinerConfig is not None else None

    def build(self, logs: list[tuple[str, int, str]]) -> list[MetricSeries]:
        grouped: dict[tuple[str, str], dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for service, timestamp, message in logs:
            template = self._template(message)
            grouped[(service, template)][self._bucket(timestamp)] += 1.0

        series = []
        for service, template, buckets in self._top_templates(grouped):
            if sum(1 for value in buckets.values() if value > 0) < self.min_nonzero_buckets:
                continue
            latest = max(buckets) if buckets else 0
            start = latest - (self.history_buckets - 1) * self.bucket_seconds
            digest = hashlib.sha1(service.encode() + b":" + template.encode()).hexdigest()[:10]
            metric = f"log_template_count_{digest}"
            series.append(
                MetricSeries(
                    service=service,
                    metric=metric,
                    signal_id=f"{service.replace('-', '_')}_{metric}",
                    points=[self._point(start + index * self.bucket_seconds, buckets) for index in range(self.history_buckets)],
                )
            )
        return series

    def _template(self, message: str) -> str:
        if self.template_miner is not None:
            result = self.template_miner.add_log_message(message)
            template = result.get("template_mined")
            if template:
                return template
        message = re.sub(r"\b[0-9a-f]{8,}\b", "<*>", message, flags=re.IGNORECASE)
        message = re.sub(r"\b\d+(?:\.\d+)?\b", "<*>", message)
        return " ".join(message.split())

    def _bucket(self, timestamp: int) -> int:
        return (timestamp // self.bucket_seconds) * self.bucket_seconds if timestamp else 0

    def _point(self, timestamp: int, buckets: dict[int, float]):
        from aiops.schemas import MetricPoint

        return MetricPoint(timestamp=timestamp, value=buckets.get(timestamp, 0.0))

    def _top_templates(self, grouped: dict[tuple[str, str], dict[int, float]]):
        by_service: dict[str, list[tuple[str, dict[int, float], float]]] = defaultdict(list)
        for (service, template), buckets in grouped.items():
            by_service[service].append((template, buckets, sum(buckets.values())))
        for service, items in by_service.items():
            for template, buckets, _ in sorted(items, key=lambda item: item[2], reverse=True)[: self.max_templates_per_service]:
                yield service, template, buckets


def _drain3_config(config_path: str | Path):
    config = TemplateMinerConfig()
    path = Path(config_path)
    if path.exists():
        config.load(str(path))
    return config


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
        drain3_config_path: str | Path,
        log_bucket_seconds: int,
        log_history_buckets: int,
        log_max_templates_per_service: int,
        log_min_nonzero_buckets: int,
        log_correlation_window_seconds: int,
        single_algorithm_min_normalized_score: float,
        robust_drift_threshold: float,
        robust_drift_min_baseline_points: int,
        min_tail_anomaly_buckets: dict[str, int],
        min_relative_change_ratio: dict[str, float],
        min_absolute_change: dict[str, float],
        correlation_lag_buckets: dict[str, int],
        detection_window_seconds: int | None,
    ):
        self.algorithm_weights = algorithm_weights
        self.weighted_score_threshold = weighted_score_threshold
        self.single_algorithm_min_normalized_score = single_algorithm_min_normalized_score
        self.log_correlation_window_seconds = log_correlation_window_seconds
        self.min_points = min_points
        self.min_tail_anomaly_buckets = min_tail_anomaly_buckets
        self.min_relative_change_ratio = min_relative_change_ratio
        self.min_absolute_change = min_absolute_change
        self.correlation_lag_buckets = correlation_lag_buckets
        self.detection_window_seconds = detection_window_seconds
        self.thresholds = {
            "robust_drift": robust_drift_threshold,
            "ewma_stl": ewma_z_threshold,
            "isolation_forest": isolation_score_threshold,
        }
        self.robust_drift = RobustDriftDetector(robust_drift_threshold, min_points, robust_drift_min_baseline_points, detection_window_seconds)
        self.ewma_stl = EwmaStlDetector(ewma_alpha, ewma_z_threshold, min_points, seasonal_period, detection_window_seconds)
        self.isolation_forest = ServiceIsolationForestDetector(isolation_score_threshold, min_points, detection_window_seconds)
        self.log_templates = LogTemplateMetricBuilder(
            drain3_config_path,
            log_bucket_seconds,
            log_history_buckets,
            log_max_templates_per_service,
            log_min_nonzero_buckets,
        )
        self.last_algorithm_findings: list[AnomalyFinding] = []

    def evaluate(self, series: list[MetricSeries], logs: list[tuple[str, int, str]] | None = None) -> list[AnomalyFinding]:
        detector_series = self._filter_normal_traffic_growth(series)
        detector_series = [metric for metric in detector_series if self._has_significant_tail_change(metric)]
        raw_metric_findings = (
            [
                *self.robust_drift.evaluate(detector_series),
                *self.ewma_stl.evaluate(detector_series),
                *self.isolation_forest.evaluate(detector_series),
            ]
            if detector_series
            else []
        )
        metric_findings = self._weighted_sum(raw_metric_findings)
        log_series = self.log_templates.build(logs or [])
        raw_log_findings = [*self.ewma_stl.evaluate(log_series), *self.isolation_forest.evaluate(log_series)] if log_series else []
        log_findings = self._correlated_log_findings(
            self._weighted_sum(raw_log_findings),
            metric_findings,
        )
        self.last_algorithm_findings = [*raw_metric_findings, *raw_log_findings]
        return self._suppress_busy_infra([*metric_findings, *log_findings], [*series, *log_series])

    def _has_significant_tail_change(self, metric: MetricSeries) -> bool:
        group = _metric_group(metric.metric)
        return evaluate_tail_change(
            metric,
            self.detection_window_seconds,
            self.min_points - 1,
            self.min_tail_anomaly_buckets[group],
            self.min_relative_change_ratio[group],
            self.min_absolute_change[group],
        ).significant

    def _correlated_log_findings(self, log_findings: list[AnomalyFinding], metric_findings: list[AnomalyFinding]) -> list[AnomalyFinding]:
        return [
            log
            for log in log_findings
            if any(
                metric.service == log.service and abs(metric.timestamp - log.timestamp) <= self.log_correlation_window_seconds
                for metric in metric_findings
            )
        ]

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

    def _suppress_busy_infra(self, findings: list[AnomalyFinding], series: list[MetricSeries]) -> list[AnomalyFinding]:
        by_service_series: dict[str, list[MetricSeries]] = defaultdict(list)
        for metric in series:
            by_service_series[metric.service].append(metric)
        normal_services = {
            service
            for service, service_series in by_service_series.items()
            if self._normal_traffic_growth_decision(service_series)[0]
        }
        return [
            finding
            for finding in findings
            if finding.service not in normal_services or not (_is_busy_infra_metric(finding.metric) or _is_latency_metric(finding.metric))
        ]

    def _filter_normal_traffic_growth(self, series: list[MetricSeries]) -> list[MetricSeries]:
        by_service: dict[str, list[MetricSeries]] = defaultdict(list)
        for metric in series:
            by_service[metric.service].append(metric)
        decisions = {service: self._normal_traffic_growth_decision(service_series) for service, service_series in by_service.items()}
        normal_services = {service for service, (normal, _) in decisions.items() if normal}
        logger.info(
            "AIOPS_NORMAL_GROWTH_GATE %s",
            " | ".join(f"service={service} result={'skip' if normal else 'detect'} {detail}" for service, (normal, detail) in decisions.items()),
        )
        return [
            metric
            for metric in series
            if metric.service not in normal_services or _is_error_metric(metric.metric) or _is_oom_metric(metric.metric)
        ]

    def _normal_traffic_growth_decision(self, series: list[MetricSeries]) -> tuple[bool, str]:
        return _normal_traffic_growth_decision(
            series,
            self.detection_window_seconds,
            self.min_points - 1,
            self.min_tail_anomaly_buckets,
            self.min_relative_change_ratio,
            self.min_absolute_change,
            self.correlation_lag_buckets,
        )

    def _increase_timestamps(self, metric: MetricSeries, group: str) -> set[int]:
        return _tail_increase_timestamps(
            metric,
            self.detection_window_seconds,
            self.min_points - 1,
            self.min_tail_anomaly_buckets[group],
            self.min_relative_change_ratio[group],
            self.min_absolute_change[group],
        )

def _is_cpu_metric(metric: str) -> bool:
    return "cpu" in metric


def _is_disk_metric(metric: str) -> bool:
    return "disk" in metric


def _is_busy_infra_metric(metric: str) -> bool:
    return _is_cpu_metric(metric) or _is_disk_metric(metric) or _is_memory_metric(metric)


def _is_memory_metric(metric: str) -> bool:
    return "memory" in metric


def _is_oom_metric(metric: str) -> bool:
    return "oom" in metric


def _is_latency_metric(metric: str) -> bool:
    return "latency" in metric


def _is_hard_failure_metric(metric: str) -> bool:
    return "error_rate" in metric or "error_ratio" in metric or "ready_pods" in metric


def _is_error_metric(metric: str) -> bool:
    return "error_rate" in metric or "error_ratio" in metric


def _metric_group(metric: str) -> str:
    return metric_group(metric)


def _point_changed(value: float, baseline: float, min_relative: float, min_absolute: float) -> bool:
    return point_changed(value, baseline, min_relative, min_absolute)


def _normal_traffic_growth_decision(
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    min_tail_anomaly_buckets: dict[str, int],
    min_relative_change_ratio: dict[str, float],
    min_absolute_change: dict[str, float],
    correlation_lag_buckets: dict[str, int],
) -> tuple[bool, str]:
    return normal_traffic_growth_decision(
        series,
        detection_window_seconds,
        start,
        min_tail_anomaly_buckets,
        min_relative_change_ratio,
        min_absolute_change,
        correlation_lag_buckets,
    )


def _tail_increase_timestamps(
    metric: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
    min_buckets: int,
    min_relative: float,
    min_absolute: float,
) -> set[int]:
    return tail_increase_timestamps(metric, detection_window_seconds, start, min_buckets, min_relative, min_absolute)


def _tail_context(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> tuple[list[int], list[float], float]:
    indexes = list(_tail_indexes(metric, detection_window_seconds, start))
    values = median3([point.value for point in metric.points])
    baseline_values = values[: indexes[0]] if indexes else []
    return (indexes, values, median(baseline_values)) if len(baseline_values) >= 4 else ([], values, 0.0)


def _median3(values: list[float]) -> list[float]:
    return median3(values)


def _series_step_seconds(metric: MetricSeries) -> int:
    return series_step_seconds(metric)


def _tail_indexes(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> range:
    return tail_indexes(metric, detection_window_seconds, start)


def build_v001_anomaly_engine(config: dict, **overrides) -> V001AnomalyEngine:
    anomaly = config["anomaly"]
    config = {**config, **overrides}
    return V001AnomalyEngine(
        ewma_alpha=float(config["ewma_alpha"]),
        ewma_z_threshold=float(config["ewma_z_threshold"]),
        isolation_score_threshold=float(config["isolation_score_threshold"]),
        min_points=int(config["min_points"]),
        seasonal_period=int(config["seasonal_period"]),
        algorithm_weights=anomaly["algorithm_weights"],
        weighted_score_threshold=float(anomaly["weighted_score_threshold"]),
        drain3_config_path=anomaly["drain3_config_path"],
        log_bucket_seconds=int(anomaly["log_bucket_seconds"]),
        log_history_buckets=int(anomaly["log_history_buckets"]),
        log_max_templates_per_service=int(anomaly["log_max_templates_per_service"]),
        log_min_nonzero_buckets=int(anomaly["log_min_nonzero_buckets"]),
        log_correlation_window_seconds=int(anomaly["log_correlation_window_seconds"]),
        single_algorithm_min_normalized_score=float(anomaly["single_algorithm_min_normalized_score"]),
        robust_drift_threshold=float(anomaly["robust_drift_threshold"]),
        robust_drift_min_baseline_points=int(anomaly["robust_drift_min_baseline_points"]),
        min_tail_anomaly_buckets={key: int(value) for key, value in anomaly["min_tail_anomaly_buckets"].items()},
        min_relative_change_ratio={key: float(value) for key, value in anomaly["min_relative_change_ratio"].items()},
        min_absolute_change={key: float(value) for key, value in anomaly["min_absolute_change"].items()},
        correlation_lag_buckets={key: int(value) for key, value in anomaly["correlation_lag_buckets"].items()},
        detection_window_seconds=int(anomaly["detection_window_seconds"]) or None,
    )
