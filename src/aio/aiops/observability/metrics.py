#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import time

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from aiops.schemas import PipelineResult


PIPELINE_RUNS = Counter(
    "aiops_pipeline_runs_total",
    "AIOps pipeline runs by outcome.",
    labelnames=("outcome",),
)
PIPELINE_DURATION = Histogram(
    "aiops_pipeline_run_duration_seconds",
    "Time spent collecting signals and executing one AIOps pipeline cycle.",
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
LAST_SUCCESS = Gauge(
    "aiops_pipeline_last_success_unixtime",
    "Unix timestamp of the most recent successful AIOps pipeline cycle.",
)
LAST_INCIDENTS = Gauge(
    "aiops_pipeline_last_incidents",
    "Number of incidents returned by the most recent successful cycle.",
)
LAST_ANOMALIES = Gauge(
    "aiops_pipeline_last_anomalies",
    "Number of anomaly findings returned by the most recent successful cycle.",
)


def record_pipeline_success(result: PipelineResult, duration_seconds: float) -> None:
    PIPELINE_RUNS.labels(outcome="success").inc()
    PIPELINE_DURATION.observe(duration_seconds)
    LAST_SUCCESS.set(time.time())
    LAST_INCIDENTS.set(len(result.incidents))
    LAST_ANOMALIES.set(len(result.rca_result.anomalies))


def record_pipeline_failure(duration_seconds: float) -> None:
    PIPELINE_RUNS.labels(outcome="failure").inc()
    PIPELINE_DURATION.observe(duration_seconds)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
