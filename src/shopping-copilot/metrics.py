#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Low-cardinality metrics for Shopping Copilot cache and model usage."""

from __future__ import annotations

from typing import Any


_instruments: dict[str, Any] = {}


def init_metrics(meter: Any) -> dict[str, Any]:
    instruments = {
        "cache_requests": meter.create_counter(
            "shopping_copilot_cache_requests_total",
            unit="1",
            description="Shopping Copilot cache lookup outcomes",
        ),
        "cache_lookup_duration": meter.create_histogram(
            "shopping_copilot_cache_lookup_duration_ms",
            unit="ms",
            description="Shopping Copilot cache lookup latency",
        ),
        "model_calls": meter.create_counter(
            "shopping_copilot_model_calls_total",
            unit="1",
            description="Actual Shopping Copilot provider model calls",
        ),
        "model_input_tokens": meter.create_counter(
            "shopping_copilot_model_input_tokens_total",
            unit="1",
            description="Provider-reported Shopping Copilot input tokens",
        ),
        "model_output_tokens": meter.create_counter(
            "shopping_copilot_model_output_tokens_total",
            unit="1",
            description="Provider-reported Shopping Copilot output tokens",
        ),
    }
    _instruments.clear()
    _instruments.update(instruments)
    return instruments


def record_cache_lookup(
    outcome: str,
    match: str = "none",
    duration_ms: float | None = None,
) -> None:
    attributes = {"outcome": outcome, "match": match}
    counter = _instruments.get("cache_requests")
    if counter is not None:
        counter.add(1, attributes)
    histogram = _instruments.get("cache_lookup_duration")
    if histogram is not None and duration_ms is not None:
        histogram.record(duration_ms, attributes)


def record_model_call(
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    attributes = {"provider": provider}
    counter = _instruments.get("model_calls")
    if counter is not None:
        counter.add(1, attributes)
    input_counter = _instruments.get("model_input_tokens")
    if input_counter is not None and input_tokens > 0:
        input_counter.add(input_tokens, attributes)
    output_counter = _instruments.get("model_output_tokens")
    if output_counter is not None and output_tokens > 0:
        output_counter.add(output_tokens, attributes)
