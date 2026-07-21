#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import defaultdict
from aiops.schemas import MetricPoint, MetricSeries, SignalQuality


def prepare_detector_series(series: list[MetricSeries]) -> list[MetricSeries]:
    """Keep only valid series and bucket one-second collection data for model stability."""
    return [_bucket(item) for item in series if item.quality == SignalQuality.VERIFIED and item.points]


def _bucket(series: MetricSeries) -> MetricSeries:
    bucket_seconds = series.detector_bucket_seconds or series.step_seconds or 1
    step_seconds = series.step_seconds or bucket_seconds
    if bucket_seconds <= step_seconds:
        return series
    values_by_bucket: dict[int, list[float]] = defaultdict(list)
    for point in series.points:
        timestamp = (point.timestamp // bucket_seconds) * bucket_seconds
        values_by_bucket[timestamp].append(point.value)
    return series.model_copy(
        update={
            "points": [
                MetricPoint(timestamp=timestamp, value=_bucket_value(series.metric, values))
                for timestamp, values in sorted(values_by_bucket.items())
            ],
            "step_seconds": bucket_seconds,
            "detector_bucket_seconds": bucket_seconds,
        }
    )


def _bucket_value(metric: str, values: list[float]) -> float:
    if "error_rate" in metric or "error_ratio" in metric or "latency" in metric:
        return max(values)
    if "cpu" in metric or "memory" in metric or "request_rate" in metric:
        return sum(values) / len(values)
    return values[-1]
