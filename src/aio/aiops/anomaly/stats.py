#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from statistics import mean as _mean, median as _median


def mean(values: list[float]) -> float:
    return _mean(values) if values else 0.0


def median(values: list[float]) -> float:
    return _median(values) if values else 0.0


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * q)))
    return ordered[index]


def robust_spread(values: list[float]) -> float:
    if len(values) < 4:
        return 1.0
    center = median(values)
    mad = median([abs(value - center) for value in values]) * 1.4826
    raw_iqr = quantile(values, 0.75) - quantile(values, 0.25)
    spread = max(mad, raw_iqr / 1.349)
    return spread if spread > 0 else 1.0


def robust_score(baseline: list[float], values: list[float]) -> float:
    if len(baseline) < 4 or not values:
        return 0.0
    center = median(baseline)
    spread = robust_spread(baseline)
    return max(abs(value - center) / spread for value in values)


def rolling_robust_scores(values: list[float], indexes, min_baseline_points: int, window_size: int | None = None) -> list[tuple[float, int]]:
    scored = []
    for index in indexes:
        start = max(0, index - (window_size or index))
        baseline = values[start:index]
        if len(baseline) >= min_baseline_points:
            scored.append((robust_score(baseline, [values[index]]), index))
    return scored
