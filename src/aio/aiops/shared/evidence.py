#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

STRONG_TRACE_MARKER = "trace_id="
STRONG_LOG_MARKER = "log_classification=hard_failure"


def trace_summary(
    trace_id: str | None,
    operation: str | None = None,
    status: str | None = None,
    duration_ms: float | None = None,
    reference: str | None = None,
    *,
    upstream: str | None = None,
    downstream: str | None = None,
    observed: bool = False,
) -> str:
    duration = f"{duration_ms or 0.0:.3f}"
    if observed:
        return f"trace_observed id={trace_id or 'unknown'} operation={operation or 'unknown'} status={status or 'unknown'} duration_ms={duration} reference={reference or 'unknown'}"
    return (
        f"trace_id={trace_id or 'unknown'} operation={operation or 'unknown'} status={status or 'unknown'} "
        f"upstream={upstream or 'unknown'} downstream={downstream or 'unknown'} duration_ms={duration} reference={reference or 'unknown'}"
    )


def log_summary(
    classification: str | None,
    count: int,
    timestamp: int | None = None,
    reference: str | None = None,
    excerpt: str | None = None,
) -> str:
    return f"log_classification={classification or 'unknown'} count={count} timestamp={timestamp or 0} reference={reference or 'unknown'} excerpt={excerpt or 'unknown'}"


def log_search_summary(count: int, excerpts: list[str]) -> str:
    return f"count={count} excerpts={excerpts}"
