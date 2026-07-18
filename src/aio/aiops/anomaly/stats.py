from __future__ import annotations

from math import sqrt


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


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
