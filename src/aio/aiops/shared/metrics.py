#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations


def is_error_metric(metric: str) -> bool:
    return metric == "error" or "error_rate" in metric or "error_ratio" in metric or "bad_ratio" in metric


def is_oom_metric(metric: str) -> bool:
    return "oom" in metric


def is_memory_metric(metric: str) -> bool:
    return "memory" in metric


def is_log_metric(metric: str) -> bool:
    return metric.startswith("log_template_count_")


def is_context_metric(metric: str) -> bool:
    return "request_rate" in metric or "latency" in metric or "burn_rate" in metric or is_error_metric(metric)


def is_root_cause_metric(metric: str) -> bool:
    return not (is_log_metric(metric) or is_context_metric(metric))


def is_busy_infra_metric(metric: str) -> bool:
    return "cpu" in metric or "memory" in metric or "disk" in metric


def metric_priority(metric: str) -> int:
    if is_error_metric(metric):
        return 2
    if is_busy_infra_metric(metric) or is_oom_metric(metric):
        return 1
    return 0
