#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

def init_metrics(meter):

    # Product reviews counter
    app_product_review_counter = meter.create_counter(
        'app_product_review_counter', unit='reviews', description="Counts the total number of returned product reviews"
    )

    # AI Assistant counter
    app_ai_assistant_counter = meter.create_counter(
        'app_ai_assistant_counter', unit='summaries', description="Counts the total number of AI Assistant requests"
    )

    # Guardrail checks counter
    app_guardrail_counter = meter.create_counter(
        'app_guardrail_counter', unit='checks', description="Counts the total number of guardrail checks"
    )

    # Hybrid cache metrics (A1.3) — low-cardinality labels only.
    # outcome: hit | miss | error | bypass
    # match: exact | semantic | none
    ai_cache_requests_total = meter.create_counter(
        'ai_cache_requests_total',
        unit='1',
        description="Cache lookup outcomes for Summary Bot",
    )
    ai_cache_lookup_duration_ms = meter.create_histogram(
        'ai_cache_lookup_duration_ms',
        unit='ms',
        description="Cache lookup latency in milliseconds",
    )
    ai_cache_model_calls_total = meter.create_counter(
        'ai_cache_model_calls_total',
        unit='1',
        description="Model calls on the Summary Bot miss path",
    )
    ai_cache_model_input_tokens_total = meter.create_counter(
        'ai_cache_model_input_tokens_total',
        unit='1',
        description="Model input tokens from real usage on miss path",
    )
    ai_cache_model_output_tokens_total = meter.create_counter(
        'ai_cache_model_output_tokens_total',
        unit='1',
        description="Model output tokens from real usage on miss path",
    )

    product_review_svc_metrics = {
        "app_product_review_counter": app_product_review_counter,
        "app_ai_assistant_counter": app_ai_assistant_counter,
        "app_guardrail_counter": app_guardrail_counter,
        "ai_cache_requests_total": ai_cache_requests_total,
        "ai_cache_lookup_duration_ms": ai_cache_lookup_duration_ms,
        "ai_cache_model_calls_total": ai_cache_model_calls_total,
        "ai_cache_model_input_tokens_total": ai_cache_model_input_tokens_total,
        "ai_cache_model_output_tokens_total": ai_cache_model_output_tokens_total,
        # Backward-compatible aliases used by earlier integration drafts
        "app_cache_requests_total": ai_cache_requests_total,
        "app_cache_lookup_duration_ms": ai_cache_lookup_duration_ms,
        "app_cache_model_calls_total": ai_cache_model_calls_total,
    }

    return product_review_svc_metrics
