from __future__ import annotations

from collections import defaultdict
import hashlib
import os
from pathlib import Path
import re
import warnings

from aiops.anomaly.stats import mean, robust_score, stdev
from aiops.schemas import AnomalyFinding, MetricSeries

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
except Exception:  # pragma: no cover - drain3 is optional until the env is refreshed.
    TemplateMiner = None
    TemplateMinerConfig = None


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


class RobustDriftDetector:
    def __init__(self, score_threshold: float, min_points: int, min_baseline_points: int):
        self.score_threshold = score_threshold
        self.min_points = min_points
        self.min_baseline_points = min_baseline_points

    def evaluate(self, series: list[MetricSeries]) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for metric in series:
            values = [point.value for point in metric.points]
            if len(values) < self.min_points:
                continue
            scored = [
                (robust_score(values[:index], [values[index]]), index)
                for index in range(self.min_baseline_points, len(values))
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
        drain3_config_path: str | Path = "config/drain3.ini",
        log_bucket_seconds: int = 60,
        log_history_buckets: int | None = None,
        log_max_templates_per_service: int = 20,
        log_min_nonzero_buckets: int = 2,
        log_correlation_window_seconds: int = 300,
        single_algorithm_min_normalized_score: float = 2.0,
        robust_drift_threshold: float = 3.0,
        robust_drift_min_baseline_points: int = 4,
        suppress_cpu_robust_threshold: float = 3.0,
    ):
        self.algorithm_weights = algorithm_weights
        self.weighted_score_threshold = weighted_score_threshold
        self.single_algorithm_min_normalized_score = single_algorithm_min_normalized_score
        self.log_correlation_window_seconds = log_correlation_window_seconds
        self.suppress_cpu_robust_threshold = suppress_cpu_robust_threshold
        self.thresholds = {
            "robust_drift": robust_drift_threshold,
            "ewma_stl": ewma_z_threshold,
            "isolation_forest": isolation_score_threshold,
        }
        self.robust_drift = RobustDriftDetector(robust_drift_threshold, min_points, robust_drift_min_baseline_points)
        self.ewma_stl = EwmaStlDetector(ewma_alpha, ewma_z_threshold, min_points, seasonal_period)
        self.isolation_forest = ServiceIsolationForestDetector(isolation_score_threshold, min_points)
        self.log_templates = LogTemplateMetricBuilder(
            drain3_config_path,
            log_bucket_seconds,
            log_history_buckets or min_points,
            log_max_templates_per_service,
            log_min_nonzero_buckets,
        )
        self.last_algorithm_findings: list[AnomalyFinding] = []

    def evaluate(self, series: list[MetricSeries], logs: list[tuple[str, int, str]] | None = None) -> list[AnomalyFinding]:
        raw_metric_findings = [*self.robust_drift.evaluate(series), *self.ewma_stl.evaluate(series), *self.isolation_forest.evaluate(series)]
        metric_findings = self._weighted_sum(raw_metric_findings)
        log_series = self.log_templates.build(logs or [])
        raw_log_findings = [*self.ewma_stl.evaluate(log_series), *self.isolation_forest.evaluate(log_series)]
        log_findings = self._correlated_log_findings(
            self._weighted_sum(raw_log_findings),
            metric_findings,
        )
        self.last_algorithm_findings = [*raw_metric_findings, *raw_log_findings]
        return self._suppress_busy_cpu([*metric_findings, *log_findings], [*series, *log_series])

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

    def _suppress_busy_cpu(self, findings: list[AnomalyFinding], series: list[MetricSeries]) -> list[AnomalyFinding]:
        by_service_series: dict[str, list[MetricSeries]] = defaultdict(list)
        by_service_findings: dict[str, list[AnomalyFinding]] = defaultdict(list)
        for metric in series:
            by_service_series[metric.service].append(metric)
        for finding in findings:
            by_service_findings[finding.service].append(finding)

        filtered = []
        for finding in findings:
            if not _is_cpu_metric(finding.metric):
                filtered.append(finding)
                continue
            service_findings = by_service_findings[finding.service]
            service_series = by_service_series[finding.service]
            has_failure_or_memory = any(_is_failure_metric(item.metric) or _is_memory_metric(item.metric) for item in service_findings)
            if (
                has_failure_or_memory
                or not _request_rate_increased(service_series, self.suppress_cpu_robust_threshold)
                or _failure_metric_increased(service_series, self.suppress_cpu_robust_threshold)
            ):
                filtered.append(finding)
        return filtered


def _is_cpu_metric(metric: str) -> bool:
    return "cpu" in metric


def _is_memory_metric(metric: str) -> bool:
    return "memory" in metric or "oom" in metric


def _is_failure_metric(metric: str) -> bool:
    return "latency" in metric or "error_rate" in metric or "ready_pods" in metric


def _request_rate_increased(series: list[MetricSeries], threshold: float) -> bool:
    return any("request_rate" in metric.metric and _latest_robust_score(metric) >= threshold for metric in series)


def _failure_metric_increased(series: list[MetricSeries], threshold: float) -> bool:
    return any(_is_failure_metric(metric.metric) and _latest_robust_score(metric) >= threshold for metric in series)


def _latest_robust_score(metric: MetricSeries) -> float:
    values = [point.value for point in metric.points]
    return robust_score(values[:-1], [values[-1]]) if len(values) >= 5 else 0.0


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
        drain3_config_path=anomaly.get("drain3_config_path", "config/drain3.ini"),
        log_bucket_seconds=int(anomaly.get("log_bucket_seconds", 60)),
        log_history_buckets=int(anomaly.get("log_history_buckets", config["min_points"])),
        log_max_templates_per_service=int(anomaly.get("log_max_templates_per_service", 20)),
        log_min_nonzero_buckets=int(anomaly.get("log_min_nonzero_buckets", 2)),
        log_correlation_window_seconds=int(anomaly.get("log_correlation_window_seconds", 300)),
        single_algorithm_min_normalized_score=float(anomaly["single_algorithm_min_normalized_score"]),
        robust_drift_threshold=float(anomaly["robust_drift_threshold"]),
        robust_drift_min_baseline_points=int(anomaly["robust_drift_min_baseline_points"]),
        suppress_cpu_robust_threshold=float(anomaly["suppress_cpu_robust_threshold"]),
    )
