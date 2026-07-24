#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from aiops.schemas import MetricSeries


@dataclass(frozen=True)
class TailChange:
    indexes: tuple[int, ...]
    values: tuple[float, ...]
    baseline: float
    changed_buckets: int
    first_changed_at: int | None
    significant: bool


def metric_group(metric: str) -> str:
    for marker, group in (
        ("error_rate", "error"),
        ("error_ratio", "error"),
        ("latency", "latency"),
        ("cpu", "cpu"),
        ("memory", "memory"),
        ("disk", "disk"),
        ("socket_io", "socket_io"),
        ("request_rate", "request_rate"),
    ):
        if marker in metric:
            return group
    return "default"


def point_changed(value: float, baseline: float, min_relative: float, min_absolute: float) -> bool:
    delta = abs(value - baseline)
    return delta >= min_absolute and (delta > 0 if baseline == 0 else delta / abs(baseline) >= min_relative)


def evaluate_tail_change(
    metric: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
    min_buckets: int,
    min_relative: float,
    min_absolute: float,
    *,
    smooth: bool = False,
) -> TailChange:
    indexes = tuple(tail_indexes(metric, detection_window_seconds, start))
    values = tuple(median3([point.value for point in metric.points]) if smooth else [point.value for point in metric.points])
    baseline_values = values[: indexes[0]] if indexes else ()
    if len(baseline_values) < 4:
        return TailChange((), values, 0.0, 0, None, False)
    baseline = median(baseline_values)
    changed = [index for index in indexes if point_changed(values[index], baseline, min_relative, min_absolute)]
    return TailChange(
        indexes=indexes,
        values=values,
        baseline=baseline,
        changed_buckets=len(changed),
        first_changed_at=metric.points[changed[0]].timestamp if changed else None,
        significant=len(changed) >= min_buckets,
    )


def tail_indexes(metric: MetricSeries, detection_window_seconds: int | None, start: int) -> range:
    if not metric.points:
        return range(0)
    if not detection_window_seconds:
        return range(start, len(metric.points))
    cutoff = metric.points[-1].timestamp - detection_window_seconds + series_step_seconds(metric)
    first = next((index for index, point in enumerate(metric.points) if point.timestamp >= cutoff), len(metric.points))
    return range(max(start, first), len(metric.points))


def fixed_baseline_and_tail(metric: MetricSeries, detection_window_seconds: int | None, start: int, values: list[float]) -> tuple[list[float], range]:
    indexes = tail_indexes(metric, detection_window_seconds, start)
    return (values[: indexes.start], indexes)


def median3(values: list[float]) -> list[float]:
    if len(values) < 3:
        return values[:]
    return [values[0], *(median(values[index - 1 : index + 2]) for index in range(1, len(values) - 1)), values[-1]]


import math


def series_step_seconds(metric: MetricSeries) -> int:
    if metric.detector_bucket_seconds or metric.step_seconds:
        return metric.detector_bucket_seconds or metric.step_seconds or 1
    differences = [right.timestamp - left.timestamp for left, right in zip(metric.points, metric.points[1:]) if right.timestamp > left.timestamp]
    return int(median(differences)) if differences else 1


from scipy.stats import pearsonr


def tail_pearson_correlation(
    left: MetricSeries,
    right: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
) -> float:
    left_tail = tail_indexes(left, detection_window_seconds, start)
    start_idx = max(0, left_tail.start - 15) if left_tail else max(0, start - 15)
    left_indexes = range(start_idx, len(left.points))
    if not left_indexes or not right.points:
        return 0.0

    tolerance = max(series_step_seconds(left), series_step_seconds(right)) * 2
    left_vals, right_vals = [], []
    right_idx = 0
    for i in left_indexes:
        pt = left.points[i]
        while right_idx + 1 < len(right.points) and abs(right.points[right_idx + 1].timestamp - pt.timestamp) <= abs(right.points[right_idx].timestamp - pt.timestamp):
            right_idx += 1
        if abs(right.points[right_idx].timestamp - pt.timestamp) <= tolerance:
            left_vals.append(pt.value)
            right_vals.append(right.points[right_idx].value)

    if len(left_vals) < 3 or len(set(left_vals)) <= 1 or len(set(right_vals)) <= 1:
        return 0.0
    try:
        r_result = pearsonr(left_vals, right_vals)
        r = float(r_result.statistic) if hasattr(r_result, "statistic") else float(r_result[0])
        return 0.0 if math.isnan(r) else r
    except Exception:
        return 0.0


def normal_traffic_growth_decision(
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    min_tail_anomaly_buckets: dict[str, int],
    min_relative_change_ratio: dict[str, float],
    min_absolute_change: dict[str, float],
    correlation_lag_buckets: dict[str, int],
    min_pearson_correlation: float = 0.5,
) -> tuple[bool, str]:
    infra_groups = ("cpu", "memory", "socket_io")
    groups = ("request_rate", *infra_groups)
    by_group = {group: [metric for metric in series if metric_group(metric.metric) == group] for group in groups}
    missing = [group for group, metrics in by_group.items() if not metrics]
    if "request_rate" in missing or sum(bool(by_group[group]) for group in infra_groups) < 2:
        return False, f"reason=missing_metrics metrics={','.join(missing)}"
    for metric in series:
        change = _smoothed_tail_change(metric, detection_window_seconds, start, min_tail_anomaly_buckets, min_relative_change_ratio, min_absolute_change)
        if ("error_rate" in metric.metric or "error_ratio" in metric.metric) and any(
            change.values[index] > change.baseline
            and point_changed(change.values[index], change.baseline, 0.0, min_absolute_change["error"])
            for index in change.indexes
        ):
            return False, "reason=error_increased"
        if "ready_pods" in metric.metric:
            decreased = sum(change.values[index] < change.baseline and index_changed(change, index, metric.metric, min_relative_change_ratio, min_absolute_change) for index in change.indexes)
            group = metric_group(metric.metric)
            if decreased >= min_tail_anomaly_buckets[group] and change.indexes and median(change.values[index] for index in change.indexes) < change.baseline:
                return False, "reason=ready_pods_decreased"

    req_metrics = by_group["request_rate"]
    for direction, label in ((1, "growth"), (-1, "decline")):
        req_has_direction = False
        for req_metric in req_metrics:
            change = _smoothed_tail_change(req_metric, detection_window_seconds, start, min_tail_anomaly_buckets, min_relative_change_ratio, min_absolute_change)
            if change.indexes:
                delta = median(change.values[i] for i in change.indexes) - change.baseline
                if delta * direction > 0 and abs(delta) >= min_absolute_change.get("request_rate", 5.0):
                    req_has_direction = True
                    break

        if not req_has_direction:
            continue

        correlated_infra = []
        opposite_infra = []
        for group in infra_groups:
            metrics = by_group[group]
            if not metrics:
                continue
            r_scores = []
            for req_metric in req_metrics:
                for infra_metric in metrics:
                    r = tail_pearson_correlation(req_metric, infra_metric, detection_window_seconds, start)
                    change = _smoothed_tail_change(infra_metric, detection_window_seconds, start, min_tail_anomaly_buckets, min_relative_change_ratio, min_absolute_change)
                    tail_delta = median(change.values[i] for i in change.indexes) - change.baseline if change.indexes else 0.0
                    
                    # Đồng biến: r cao và biến động cùng hướng với request_rate
                    if r >= min_pearson_correlation and tail_delta * direction > 0:
                        r_scores.append(r)
                    # Bất thường/Nghịch biến: r âm hoặc biến động ngược hướng có ý nghĩa
                    elif (r <= -min_pearson_correlation) or (tail_delta * direction < 0 and abs(tail_delta) >= min_absolute_change.get(group, 1.0)):
                        opposite_infra.append(group)
            if r_scores:
                correlated_infra.append(group)

        if len(correlated_infra) >= 2 and not opposite_infra:
            return True, f"reason=coordinated_{label} common={len(correlated_infra)} infra={','.join(correlated_infra)}"

    return False, "reason=not_coordinated"


def tail_increase_timestamps(metric: MetricSeries, detection_window_seconds: int | None, start: int, min_buckets: int, min_relative: float, min_absolute: float) -> set[int]:
    return tail_direction_timestamps(metric, detection_window_seconds, start, min_buckets, min_relative, min_absolute, 1)


def tail_direction_timestamps(
    metric: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
    min_buckets: int,
    min_relative: float,
    min_absolute: float,
    direction: int,
) -> set[int]:
    change = evaluate_tail_change(metric, detection_window_seconds, start, min_buckets, min_relative, min_absolute, smooth=True)
    changed = {
        metric.points[index].timestamp
        for index in change.indexes
        if (change.values[index] - change.baseline) * direction > 0
        and point_changed(change.values[index], change.baseline, min_relative, min_absolute)
    }
    tail_delta = median(change.values[index] for index in change.indexes) - change.baseline if change.indexes else 0.0
    return changed if len(changed) >= min_buckets and tail_delta * direction > 0 else set()


def _smoothed_tail_change(metric, detection_window_seconds, start, min_buckets_by_group, min_relative_by_group, min_absolute_by_group) -> TailChange:
    group = metric_group(metric.metric)
    return evaluate_tail_change(
        metric,
        detection_window_seconds,
        start,
        min_buckets_by_group[group],
        min_relative_by_group[group],
        min_absolute_by_group[group],
        smooth=True,
    )


def index_changed(change: TailChange, index: int, metric: str, min_relative_by_group: dict[str, float], min_absolute_by_group: dict[str, float]) -> bool:
    group = metric_group(metric)
    return point_changed(change.values[index], change.baseline, min_relative_by_group[group], min_absolute_by_group[group])
