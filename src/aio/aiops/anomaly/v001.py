#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import defaultdict
import hashlib
import os
from pathlib import Path
import re
import warnings

from aiops.anomaly.stats import mean, median, robust_score, stdev
from aiops.schemas import AnomalyFinding, MetricSeries

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
            scored = []
            for index in _tail_indexes(metric, self.detection_window_seconds, self.min_points - 1):
                baseline = residuals[:index]
                score = abs(residuals[index] - mean(baseline)) / (stdev(baseline) or 1.0)
                scored.append((score, index))
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
            scored = [
                (robust_score(values[:index], [values[index]]), index)
                for index in _tail_indexes(metric, self.detection_window_seconds, self.min_baseline_points)
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
    def __init__(self, score_threshold: float, min_points: int, detection_window_seconds: int | None = None):
        self.score_threshold = score_threshold
        self.min_points = min_points
        self.detection_window_seconds = detection_window_seconds

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
            rows = self._normalized_rows(self._rows(eligible))
            if len(rows) < self.min_points:
                continue
            tail_indexes = list(_tail_indexes(eligible[0], self.detection_window_seconds, self.min_points))
            if not tail_indexes:
                continue
            baseline_rows = rows[: tail_indexes[0]]
            tail_rows = [rows[index] for index in tail_indexes]
            scored = [(score * 10.0, index) for score, index in zip(self._scores(baseline_rows, tail_rows), tail_indexes)]
            service_score, service_index = max(scored, default=(0.0, 0))
            if service_score < self.score_threshold:
                continue
            latest_values = rows[service_index]
            baseline_values = rows[:service_index]
            baseline_center = [mean([row[index] for row in baseline_values]) for index in range(len(eligible))]
            top_metric = max(eligible, key=lambda metric: abs(latest_values[eligible.index(metric)] - baseline_center[eligible.index(metric)]))
            findings.append(
                AnomalyFinding(
                    algorithm="isolation_forest",
                    service=service,
                    metric=top_metric.metric,
                    signal_id=top_metric.signal_id,
                    score=service_score,
                    timestamp=top_metric.points[service_index].timestamp,
                )
            )
        return findings

    def _scores(self, baseline_rows: list[list[float]], scored_rows: list[list[float]]) -> list[float]:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(contamination="auto", random_state=0).fit(baseline_rows)
        return [-score for score in model.score_samples(scored_rows)]

    def _rows(self, metrics: list[MetricSeries]) -> list[list[float]]:
        values_by_metric = [{point.timestamp: point.value for point in metric.points} for metric in metrics]
        timestamps = sorted(set.intersection(*(set(values) for values in values_by_metric)))
        return [[values[timestamp] for values in values_by_metric] for timestamp in timestamps]

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
        suppress_cpu_robust_threshold: float,
        suppress_latency_absolute_threshold_seconds: float,
        suppress_latency_relative_increase_ratio: float,
        min_tail_anomaly_buckets: dict[str, int],
        min_relative_change_ratio: dict[str, float],
        min_absolute_change: dict[str, float],
        detection_window_seconds: int | None,
    ):
        self.algorithm_weights = algorithm_weights
        self.weighted_score_threshold = weighted_score_threshold
        self.single_algorithm_min_normalized_score = single_algorithm_min_normalized_score
        self.log_correlation_window_seconds = log_correlation_window_seconds
        self.suppress_cpu_robust_threshold = suppress_cpu_robust_threshold
        self.suppress_latency_absolute_threshold_seconds = suppress_latency_absolute_threshold_seconds
        self.suppress_latency_relative_increase_ratio = suppress_latency_relative_increase_ratio
        self.min_points = min_points
        self.min_tail_anomaly_buckets = min_tail_anomaly_buckets
        self.min_relative_change_ratio = min_relative_change_ratio
        self.min_absolute_change = min_absolute_change
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
        raw_metric_findings = [*self.robust_drift.evaluate(series), *self.ewma_stl.evaluate(series), *self.isolation_forest.evaluate(series)]
        metric_findings = self._significant_metric_findings(self._weighted_sum(raw_metric_findings), series)
        log_series = self.log_templates.build(logs or [])
        raw_log_findings = [*self.ewma_stl.evaluate(log_series), *self.isolation_forest.evaluate(log_series)]
        log_findings = self._correlated_log_findings(
            self._weighted_sum(raw_log_findings),
            metric_findings,
        )
        self.last_algorithm_findings = [*raw_metric_findings, *raw_log_findings]
        return self._suppress_busy_infra([*metric_findings, *log_findings], [*series, *log_series])

    def _significant_metric_findings(self, findings: list[AnomalyFinding], series: list[MetricSeries]) -> list[AnomalyFinding]:
        by_signal_id = {metric.signal_id: metric for metric in series}
        return [finding for finding in findings if self._has_significant_tail_change(by_signal_id.get(finding.signal_id))]

    def _has_significant_tail_change(self, metric: MetricSeries | None) -> bool:
        if metric is None:
            return True
        indexes = list(_tail_indexes(metric, self.detection_window_seconds, self.min_points - 1))
        if not indexes:
            return False
        baseline_values = [point.value for point in metric.points[: indexes[0]]]
        if len(baseline_values) < 4:
            return False
        baseline = median(baseline_values)
        group = _metric_group(metric.metric)
        min_buckets = self.min_tail_anomaly_buckets[group]
        min_relative = self.min_relative_change_ratio[group]
        min_absolute = self.min_absolute_change[group]
        count = sum(_point_changed(point.value, baseline, min_relative, min_absolute) for point in (metric.points[index] for index in indexes))
        return count >= min_buckets

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
        by_service_findings: dict[str, list[AnomalyFinding]] = defaultdict(list)
        for metric in series:
            by_service_series[metric.service].append(metric)
        for finding in findings:
            by_service_findings[finding.service].append(finding)

        filtered = []
        for finding in findings:
            if _is_latency_metric(finding.metric):
                service_series = by_service_series[finding.service]
                if _request_rate_increased(service_series, finding.timestamp, self.suppress_cpu_robust_threshold) and not _hard_failure_increased(
                    service_series, finding.timestamp, self.suppress_cpu_robust_threshold
                ):
                    value = _value_at(_series_for_metric(service_series, finding.metric), finding.timestamp)
                    if value <= self.suppress_latency_absolute_threshold_seconds or _relative_increase(
                        _series_for_metric(service_series, finding.metric), finding.timestamp
                    ) <= self.suppress_latency_relative_increase_ratio:
                        continue
                filtered.append(finding)
                continue
            if not _is_busy_infra_metric(finding.metric):
                filtered.append(finding)
                continue
            service_findings = by_service_findings[finding.service]
            service_series = by_service_series[finding.service]
            has_failure_or_oom = any(
                item.timestamp == finding.timestamp and (_is_hard_failure_metric(item.metric) or _is_oom_metric(item.metric))
                for item in service_findings
            )
            if (
                has_failure_or_oom
                or not _request_rate_increased(service_series, finding.timestamp, self.suppress_cpu_robust_threshold)
                or _hard_failure_increased(service_series, finding.timestamp, self.suppress_cpu_robust_threshold)
            ):
                filtered.append(finding)
        return filtered

    def _suppress_busy_cpu(self, findings: list[AnomalyFinding], series: list[MetricSeries]) -> list[AnomalyFinding]:
        return self._suppress_busy_infra(findings, series)


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


def _metric_group(metric: str) -> str:
    if "error_rate" in metric or "error_ratio" in metric:
        return "error"
    if "latency" in metric:
        return "latency"
    if "cpu" in metric:
        return "cpu"
    if "memory" in metric:
        return "memory"
    if "disk" in metric:
        return "disk"
    if "socket_io" in metric:
        return "socket_io"
    if "request_rate" in metric:
        return "request_rate"
    return "default"


def _point_changed(value: float, baseline: float, min_relative: float, min_absolute: float) -> bool:
    delta = abs(value - baseline)
    if delta < min_absolute:
        return False
    if baseline == 0:
        return delta > 0
    return delta / abs(baseline) >= min_relative


def _request_rate_increased(series: list[MetricSeries], timestamp: int, threshold: float) -> bool:
    return any("request_rate" in metric.metric and _robust_score_at(metric, timestamp) >= threshold for metric in series)


def _hard_failure_increased(series: list[MetricSeries], timestamp: int, threshold: float) -> bool:
    return any((_is_hard_failure_metric(metric.metric) or _is_oom_metric(metric.metric)) and _robust_score_at(metric, timestamp) >= threshold for metric in series)


def _series_for_metric(series: list[MetricSeries], metric: str) -> MetricSeries | None:
    return next((item for item in series if item.metric == metric), None)


def _value_at(metric: MetricSeries | None, timestamp: int) -> float:
    if metric is None or not metric.points:
        return 0.0
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= timestamp), len(metric.points) - 1)
    return metric.points[index].value


def _relative_increase(metric: MetricSeries | None, timestamp: int) -> float:
    if metric is None:
        return 0.0
    values = [point.value for point in metric.points]
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= timestamp), len(metric.points) - 1)
    if index < 4:
        return 0.0
    baseline = median(values[:index])
    return (values[index] - baseline) / baseline if baseline > 0 else 0.0


def _robust_score_at(metric: MetricSeries, timestamp: int) -> float:
    values = [point.value for point in metric.points]
    index = next((index for index, point in enumerate(metric.points) if point.timestamp >= timestamp), len(metric.points) - 1)
    return robust_score(values[:index], [values[index]]) if index >= 4 else 0.0


def _tail_indexes(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> range:
    if not metric.points:
        return range(0)
    if not detection_window_seconds:
        return range(start, len(metric.points))
    cutoff = metric.points[-1].timestamp - detection_window_seconds
    first = next((index for index, point in enumerate(metric.points) if point.timestamp >= cutoff), len(metric.points))
    return range(max(start, first), len(metric.points))


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
        suppress_cpu_robust_threshold=float(anomaly["suppress_cpu_robust_threshold"]),
        suppress_latency_absolute_threshold_seconds=float(anomaly["suppress_latency_absolute_threshold_seconds"]),
        suppress_latency_relative_increase_ratio=float(anomaly["suppress_latency_relative_increase_ratio"]),
        min_tail_anomaly_buckets={key: int(value) for key, value in anomaly["min_tail_anomaly_buckets"].items()},
        min_relative_change_ratio={key: float(value) for key, value in anomaly["min_relative_change_ratio"].items()},
        min_absolute_change={key: float(value) for key, value in anomaly["min_absolute_change"].items()},
        detection_window_seconds=int(anomaly["detection_window_seconds"]) or None,
    )
