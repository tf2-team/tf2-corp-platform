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
    cutoff = metric.points[-1].timestamp - detection_window_seconds
    first = next((index for index, point in enumerate(metric.points) if point.timestamp >= cutoff), len(metric.points))
    return range(max(start, first), len(metric.points))


def median3(values: list[float]) -> list[float]:
    if len(values) < 3:
        return values[:]
    return [values[0], *(median(values[index - 1 : index + 2]) for index in range(1, len(values) - 1)), values[-1]]


def series_step_seconds(metric: MetricSeries) -> int:
    if metric.detector_bucket_seconds or metric.step_seconds:
        return metric.detector_bucket_seconds or metric.step_seconds or 1
    differences = [right.timestamp - left.timestamp for left, right in zip(metric.points, metric.points[1:]) if right.timestamp > left.timestamp]
    return int(median(differences)) if differences else 1


def normal_traffic_growth_decision(
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    min_tail_anomaly_buckets: dict[str, int],
    min_relative_change_ratio: dict[str, float],
    min_absolute_change: dict[str, float],
    correlation_lag_buckets: dict[str, int],
) -> tuple[bool, str]:
    required_groups = ("request_rate", "cpu", "memory", "socket_io")
    by_group = {group: [metric for metric in series if metric_group(metric.metric) == group] for group in required_groups}
    missing = [group for group, metrics in by_group.items() if not metrics]
    if missing:
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
    base_tolerance = max(series_step_seconds(metric) for metrics in by_group.values() for metric in metrics)
    required = max(min_tail_anomaly_buckets[group] for group in required_groups)
    failures = []
    for direction, label in ((1, "growth"), (-1, "decline")):
        timestamps = {
            group: set().union(
                *(
                    tail_direction_timestamps(
                        metric,
                        detection_window_seconds,
                        start,
                        min_tail_anomaly_buckets[group],
                        min_relative_change_ratio[group],
                        min_absolute_change[group],
                        direction,
                    )
                    for metric in metrics
                )
            )
            for group, metrics in by_group.items()
        }
        below_threshold = [group for group, changed_at in timestamps.items() if not changed_at]
        if below_threshold:
            failures.append(f"{label}:{','.join(below_threshold)}")
            continue
        request_onset = min(timestamps["request_rate"])
        aligned = all(
            -base_tolerance <= min(timestamps[group]) - request_onset <= base_tolerance * correlation_lag_buckets[group]
            for group in required_groups[1:]
        )
        simultaneous = min(len(changed_at) for changed_at in timestamps.values()) if aligned else 0
        if simultaneous >= required:
            return True, f"reason=coordinated_{label} common={simultaneous}"
        failures.append(f"{label}:common={simultaneous}")
    return False, f"reason=not_coordinated details={'|'.join(failures)} required={required}"


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
