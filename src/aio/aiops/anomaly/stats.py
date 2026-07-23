#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from statistics import mean as _mean, median as _median, stdev as _stdev


def mean(values: list[float]) -> float:
    return _mean(values) if values else 0.0


def median(values: list[float]) -> float:
    return _median(values) if values else 0.0


def stdev(values: list[float]) -> float:
    return _stdev(values) if len(values) >= 2 else 0.0


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * q)))
    return ordered[index]


def iqr(values: list[float]) -> float:
    spread = quantile(values, 0.75) - quantile(values, 0.25)
    return spread if spread != 0 else 1.0


def robust_score(baseline: list[float], values: list[float]) -> float:
    if len(baseline) < 4 or not values:
        return 0.0
    center = median(baseline)
    spread = iqr(baseline)
    return max(abs(value - center) / spread for value in values)
