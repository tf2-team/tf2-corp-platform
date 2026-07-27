#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import warnings
from dataclasses import dataclass
from statistics import median

from aiops.schemas import MetricSeries
from aiops.shared.metrics import is_root_cause_metric


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


def cusum_tail_change(metric: MetricSeries, detection_window_seconds: int | None, start: int, min_buckets: int, min_relative: float, min_absolute: float) -> TailChange:
    change = evaluate_tail_change(metric, detection_window_seconds, start, min_buckets, min_relative, min_absolute)
    if change.significant or not change.indexes:
        return change
    limit = max(min_absolute, abs(change.baseline) * min_relative) * max(2, min_buckets)
    cumulative = 0.0
    first_changed = None
    positive_buckets = 0
    for index in change.indexes:
        delta = change.values[index] - change.baseline
        positive_buckets += int(delta > 0)
        cumulative = max(0.0, cumulative + delta)
        if positive_buckets >= min_buckets and cumulative >= limit:
            first_changed = metric.points[index].timestamp
            break
    return TailChange(
        indexes=change.indexes,
        values=change.values,
        baseline=change.baseline,
        changed_buckets=change.changed_buckets,
        first_changed_at=first_changed or change.first_changed_at,
        significant=first_changed is not None,
    )


def page_hinkley_tail_change(
    metric: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
    min_buckets: int,
    min_relative: float,
    min_absolute: float,
    min_bucket_factor: float = 2.0,
) -> TailChange:
    change = evaluate_tail_change(metric, detection_window_seconds, start, min_buckets, min_relative, min_absolute)
    if change.significant or not change.indexes:
        return change
    threshold = max(min_absolute, abs(change.baseline) * min_relative)
    tolerance = threshold / max(min_bucket_factor, min_buckets)
    cumulative = 0.0
    minimum = 0.0
    first_changed = None
    positive_buckets = 0
    for index in change.indexes:
        delta = change.values[index] - change.baseline - tolerance
        positive_buckets += int(delta > 0)
        cumulative += delta
        minimum = min(minimum, cumulative)
        if positive_buckets >= min_buckets and cumulative - minimum >= threshold:
            first_changed = metric.points[index].timestamp
            break
    return TailChange(
        indexes=change.indexes,
        values=change.values,
        baseline=change.baseline,
        changed_buckets=change.changed_buckets,
        first_changed_at=first_changed or change.first_changed_at,
        significant=first_changed is not None,
    )


def slow_drift_tail_change(metric: MetricSeries, detection_window_seconds: int | None, start: int, config: dict | None) -> TailChange:
    params = _slow_drift_params(metric, config)
    values = tuple(point.value for point in metric.points)
    indexes = tuple(tail_indexes(metric, int(params.get("window_seconds", detection_window_seconds or 0)) or detection_window_seconds, 0))
    if not params or len(indexes) < int(params.get("min_points", 6)):
        return TailChange(indexes, values, 0.0, 0, None, False)
    xs = [metric.points[index].timestamp for index in indexes]
    ys = [values[index] for index in indexes]
    span = max(xs) - min(xs)
    if span <= 0:
        return TailChange(indexes, values, ys[0], 0, None, False)
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom if denom else 0.0
    direction = -1.0 if params.get("direction") == "down" else 1.0
    deltas = [direction * (right - left) for left, right in zip(ys, ys[1:])]
    positive_ratio = sum(delta > 0 for delta in deltas) / len(deltas) if deltas else 0.0
    projected_change = direction * slope * span
    significant = (
        projected_change >= float(params.get("min_total_change", 0.0))
        and positive_ratio >= float(params.get("positive_bucket_ratio", config.get("positive_bucket_ratio", 0.65)))
    )
    return TailChange(
        indexes=indexes,
        values=values,
        baseline=ys[0],
        changed_buckets=sum(delta > 0 for delta in deltas),
        first_changed_at=metric.points[indexes[0]].timestamp if significant else None,
        significant=significant,
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


def series_step_seconds(metric: MetricSeries) -> int:
    if metric.detector_bucket_seconds or metric.step_seconds:
        return metric.detector_bucket_seconds or metric.step_seconds or 1
    differences = [right.timestamp - left.timestamp for left, right in zip(metric.points, metric.points[1:]) if right.timestamp > left.timestamp]
    return int(median(differences)) if differences else 1


def _slow_drift_params(metric: MetricSeries, config: dict | None) -> dict:
    if not config or not config.get("enabled", False):
        return {}
    metrics = config.get("metrics", {})
    group = metric_group(metric.metric)
    for key in (group, *(key for key in metrics if key in metric.metric)):
        if key in metrics:
            return {**config, **metrics[key]}
    return {}


def normal_traffic_growth_decision(
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    min_tail_anomaly_buckets: dict[str, int],
    min_relative_change_ratio: dict[str, float],
    min_absolute_change: dict[str, float],
    traffic_shape_min_spearman: float = 0.7,
    traffic_shape_max_lag_buckets: int = 0,
    traffic_explanation: dict | None = None,
) -> tuple[bool, str]:
    required_infra_groups = ("cpu", "socket_io")
    groups = ("request_rate", *required_infra_groups, "memory")
    by_group = {group: [metric for metric in series if metric_group(metric.metric) == group] for group in groups}
    missing = [group for group in ("request_rate", *required_infra_groups) if not by_group[group]]
    if missing:
        return False, f"reason=missing_metrics metrics={','.join(missing)}"
    request_changes = [
        _smoothed_tail_change(metric, detection_window_seconds, start, min_tail_anomaly_buckets, min_relative_change_ratio, min_absolute_change)
        for metric in by_group["request_rate"]
    ]
    request_increased = any(change.significant and any(change.values[index] > change.baseline for index in change.indexes) for change in request_changes)
    request_decreased = any(change.significant and any(change.values[index] < change.baseline for index in change.indexes) for change in request_changes)
    request_direction = 1 if request_increased else -1 if request_decreased else 0
    for metric in series:
        if "oom_events_total" in metric.metric:
            values = [point.value for point in metric.points]
            baseline, indexes = fixed_baseline_and_tail(metric, detection_window_seconds, start, values)
            if not request_increased and baseline and indexes and max(values[index] for index in indexes) > max(baseline):
                return False, "reason=oom_increased"
    memory_shape_metrics = []
    primary_direction_mismatch = False
    for metric in series:
        change = _smoothed_tail_change(metric, detection_window_seconds, start, min_tail_anomaly_buckets, min_relative_change_ratio, min_absolute_change)
        group = metric_group(metric.metric)
        if request_direction and group in required_infra_groups and change.significant and change.indexes:
            tail_median = median(change.values[index] for index in change.indexes)
            primary_direction_mismatch = primary_direction_mismatch or (tail_median - change.baseline) * request_direction < 0
        if group == "memory" and change.significant and not request_increased and any(change.values[index] > change.baseline for index in change.indexes):
            return False, "reason=memory_increased_without_traffic"
        if group == "memory" and change.significant and change.indexes:
            tail_median = median(change.values[index] for index in change.indexes)
            if request_increased and tail_median < change.baseline:
                return False, "reason=memory_shape_mismatch"
            if all(change.values[index] >= change.baseline for index in change.indexes) or all(change.values[index] <= change.baseline for index in change.indexes):
                memory_shape_metrics.append(metric)
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
    request = by_group["request_rate"]
    config = traffic_explanation or {}
    dtw_onset_threshold = float(config.get("dtw_onset_threshold", 0.1))
    dtw_cost_scale = float(config.get("dtw_cost_scale", 2.0))
    scores = {
        group: max(
            (
                tail_aligned_dtw_similarity(
                    rate,
                    metric,
                    detection_window_seconds,
                    start,
                    max_warp_buckets=traffic_shape_max_lag_buckets,
                    enforce_onset=group in required_infra_groups,
                    onset_threshold=dtw_onset_threshold,
                    cost_scale=dtw_cost_scale,
                )
                for rate in request
                for metric in (memory_shape_metrics if group == "memory" else by_group[group])
            ),
            default=0.0,
        )
        for group in (*required_infra_groups, "memory")
        if group != "memory" or memory_shape_metrics
    }
    memory_detail = f" memory={scores['memory']:.3f}" if "memory" in scores else ""
    if primary_direction_mismatch:
        return False, f"reason=shape_mismatch direction=primary cpu={scores['cpu']:.3f} socket_io={scores['socket_io']:.3f}{memory_detail}"
    weights = config.get("weights", {"cpu": 0.5, "socket_io": 0.5, "memory": 0.0})
    threshold = float(config.get("threshold", traffic_shape_min_spearman))
    min_primary = float(config.get("min_primary_shape", traffic_shape_min_spearman))
    positive = {group: score for group, score in scores.items() if score > 0}
    weight_sum = sum(float(weights.get(group, 0.0)) for group in positive)
    traffic_score = sum(score * float(weights.get(group, 0.0)) for group, score in positive.items()) / weight_sum if weight_sum else 0.0
    primary_score = max(scores["cpu"], scores["socket_io"])
    if traffic_score >= threshold and primary_score >= min_primary:
        return True, f"reason=traffic_explained score={traffic_score:.3f} primary={primary_score:.3f} cpu={scores['cpu']:.3f} socket_io={scores['socket_io']:.3f}{memory_detail}"
    zero_metrics = [metric.metric for metrics in by_group.values() for metric in metrics if metric.points and all(point.value == 0 for point in metric.points)]
    zero_detail = f" zero_metrics={','.join(zero_metrics)}" if zero_metrics else ""
    return False, f"reason=shape_mismatch score={traffic_score:.3f} primary={primary_score:.3f} cpu={scores['cpu']:.3f} socket_io={scores['socket_io']:.3f}{memory_detail} threshold={threshold:.3f}{zero_detail}"


def traffic_explained_metrics(
    series: list[MetricSeries],
    detection_window_seconds: int | None,
    start: int,
    traffic_shape_max_lag_buckets: int = 0,
    traffic_explanation: dict | None = None,
) -> set[str]:
    request = [metric for metric in series if metric_group(metric.metric) == "request_rate"]
    if not request:
        return set()
    config = traffic_explanation or {}
    threshold = float(config.get("threshold", 0.7))
    dtw_onset_threshold = float(config.get("dtw_onset_threshold", 0.1))
    dtw_cost_scale = float(config.get("dtw_cost_scale", 2.0))
    return {
        metric.metric
        for metric in series
        if is_root_cause_metric(metric.metric)
        and max(
            (
                tail_aligned_dtw_similarity(
                    rate,
                    metric,
                    detection_window_seconds,
                    start,
                    max_warp_buckets=traffic_shape_max_lag_buckets,
                    enforce_onset=metric_group(metric.metric) in {"cpu", "socket_io"},
                    onset_threshold=dtw_onset_threshold,
                    cost_scale=dtw_cost_scale,
                )
                for rate in request
            ),
            default=0.0,
        )
        >= threshold
    }


def tail_aligned_dtw_similarity(
    left: MetricSeries,
    right: MetricSeries,
    detection_window_seconds: int | None,
    start: int,
    max_warp_buckets: int = 0,
    *,
    enforce_onset: bool = False,
    onset_threshold: float = 0.1,
    cost_scale: float = 2.0,
) -> float:
    tail = tail_indexes(left, detection_window_seconds, start)
    if not tail:
        return aligned_dtw_similarity(left, right, max_warp_buckets, enforce_onset=enforce_onset, onset_threshold=onset_threshold, cost_scale=cost_scale)
    first = max(0, tail.start - max(1, max_warp_buckets + 1))
    indexes = set(range(first, tail.stop))
    return aligned_dtw_similarity(
        left.model_copy(update={"points": [point for index, point in enumerate(left.points) if index in indexes]}),
        right,
        max_warp_buckets,
        enforce_onset=enforce_onset,
        onset_threshold=onset_threshold,
        cost_scale=cost_scale,
    )


def aligned_dtw_similarity(
    left: MetricSeries,
    right: MetricSeries,
    max_warp_buckets: int = 0,
    *,
    enforce_onset: bool = False,
    onset_threshold: float = 0.1,
    cost_scale: float = 2.0,
) -> float:
    from scipy.spatial import distance

    pairs = _aligned_pairs(left, right)
    if not pairs:
        return 0.0
    left_values = _normalize([left for left, _ in pairs])
    right_values = _normalize([right for _, right in pairs])
    if not any(left_values) or not any(right_values):
        return 0.0
    if enforce_onset:
        left_first = next((index for index, value in enumerate(left_values) if value > onset_threshold), None)
        right_first = next((index for index, value in enumerate(right_values) if value > onset_threshold), None)
        if left_first is None or right_first is None:
            return 0.0
        if abs(left_first - right_first) > max(0, max_warp_buckets):
            return 0.0
    window = max(0, max_warp_buckets)
    previous = [float("inf")] * (len(right_values) + 1)
    previous[0] = 0.0
    for left_index, left_value in enumerate(left_values, start=1):
        current = [float("inf")] * (len(right_values) + 1)
        low = max(1, left_index - window)
        high = min(len(right_values), left_index + window)
        for right_index in range(low, high + 1):
            cost = distance.euclidean((left_value,), (right_values[right_index - 1],))
            current[right_index] = cost + min(previous[right_index], current[right_index - 1], previous[right_index - 1])
        previous = current
    cost = previous[-1] / max(len(left_values), len(right_values))
    return 1.0 / (1.0 + cost_scale * cost)


def tail_aligned_spearman(left: MetricSeries, right: MetricSeries, detection_window_seconds: int | None, start: int, right_lag_buckets: int = 0) -> float:
    tail = tail_indexes(left, detection_window_seconds, start)
    if not tail:
        return aligned_spearman(left, right, right_lag_buckets)
    first = max(0, tail.start - max(1, right_lag_buckets + 1))
    indexes = set(range(first, tail.stop))
    return aligned_spearman(
        left.model_copy(update={"points": [point for index, point in enumerate(left.points) if index in indexes]}),
        right,
        right_lag_buckets,
    )


def aligned_spearman(left: MetricSeries, right: MetricSeries, right_lag_buckets: int = 0) -> float:
    from scipy.stats import ConstantInputWarning, spearmanr

    pairs = _aligned_pairs(left, right, right_lag_buckets)
    if not pairs:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConstantInputWarning)
        coefficient = spearmanr(*zip(*pairs)).statistic
    return float(coefficient) if coefficient == coefficient else 0.0


def _aligned_pairs(left: MetricSeries, right: MetricSeries, right_lag_buckets: int = 0) -> list[tuple[float, float]]:
    tolerance = max(series_step_seconds(left), series_step_seconds(right))
    lag_seconds = max(0, right_lag_buckets) * series_step_seconds(right)
    pairs = []
    right_index = 0
    for point in left.points:
        target_timestamp = point.timestamp + lag_seconds
        while right_index + 1 < len(right.points) and abs(right.points[right_index + 1].timestamp - target_timestamp) <= abs(right.points[right_index].timestamp - target_timestamp):
            right_index += 1
        if right.points and abs(right.points[right_index].timestamp - target_timestamp) <= tolerance:
            pairs.append((point.value, right.points[right_index].value))
    return pairs


def _normalize(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    spread = high - low
    return [(value - low) / spread for value in values] if spread else [0.0 for _ in values]

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
