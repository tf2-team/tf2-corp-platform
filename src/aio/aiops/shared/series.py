#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import MetricPoint, MetricSeries, SignalQuality


def prepare_detector_series(series: list[MetricSeries]) -> list[MetricSeries]:
    """Keep only valid series and bucket one-second collection data for model stability."""
    return [_bucket(item) for item in series if item.quality == SignalQuality.VERIFIED and item.points]


def _bucket(series: MetricSeries) -> MetricSeries:
    bucket_seconds = series.detector_bucket_seconds or series.step_seconds or 1
    step_seconds = series.step_seconds or bucket_seconds
    if bucket_seconds <= step_seconds:
        return series
    latest_by_bucket: dict[int, MetricPoint] = {}
    for point in series.points:
        timestamp = (point.timestamp // bucket_seconds) * bucket_seconds
        latest_by_bucket[timestamp] = MetricPoint(timestamp=timestamp, value=point.value)
    return series.model_copy(
        update={
            "points": [latest_by_bucket[timestamp] for timestamp in sorted(latest_by_bucket)],
            "step_seconds": bucket_seconds,
            "detector_bucket_seconds": bucket_seconds,
        }
    )
