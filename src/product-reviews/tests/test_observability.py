#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from decimal import Decimal

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import techx_ai_common.observability as observability
from techx_ai_common.observability import (
    call_model,
    estimated_cost,
    pseudonymize,
    tool_names_from,
    usage_from,
)


def test_safe_model_metadata(monkeypatch):
    monkeypatch.setenv("AI_TELEMETRY_HMAC_SECRET", "test-secret")
    response = {
        "usage": {"inputTokens": 100, "outputTokens": 20},
        "output": {
            "message": {
                "content": [{"toolUse": {"name": "fetch_product_reviews", "input": {"secret": "PII-TOKEN-XYZ"}}}]
            }
        },
    }

    assert usage_from(response) == (100, 20)
    assert tool_names_from(response) == ["fetch_product_reviews"]
    assert "PII-TOKEN-XYZ" not in repr(tool_names_from(response))
    assert pseudonymize("customer@example.com", "user") != "customer@example.com"
    assert estimated_cost(
        "global.amazon.nova-2-lite-v1:0", 100, 20
    ) == (Decimal("0.000080"), "aws-2026-07-01-global-standard")
    assert estimated_cost("unknown", 100, 20) is None

    monkeypatch.setenv(
        "AI_MODEL_PRICING_JSON",
        '{"custom-model":{"input_per_million":"1","output_per_million":"2","version":"test-v1"}}',
    )
    assert estimated_cost(
        "custom-model", 100, 20
    ) == (Decimal("0.00014"), "test-v1")


def test_model_span_contains_safe_metadata_only(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        observability,
        "_TRACER",
        provider.get_tracer("test"),
    )
    monkeypatch.setenv("AI_TELEMETRY_HMAC_SECRET", "test-secret")

    call_model(
        lambda: {
            "model": "global.amazon.nova-2-lite-v1:0",
            "usage": {"inputTokens": 100, "outputTokens": 20},
            "output": {
                "message": {
                    "content": [{
                        "toolUse": {
                            "name": "fetch_product_reviews",
                            "input": {"secret": "PII-TOKEN-XYZ"},
                        }
                    }]
                }
            },
        },
        model="global.amazon.nova-2-lite-v1:0",
        provider="aws.bedrock",
        surface="summary",
        workflow_step="grounded_summary",
        user_id="customer@example.com",
    )

    span = exporter.get_finished_spans()[0]
    serialized = repr(dict(span.attributes))
    assert span.name == "chat global.amazon.nova-2-lite-v1:0"
    assert span.attributes["app.ai.outcome"] == "ok"
    assert span.attributes["gen_ai.usage.input_tokens"] == 100
    assert span.attributes["app.ai.tool_names"] == ("fetch_product_reviews",)
    assert "PII-TOKEN-XYZ" not in serialized
    assert "customer@example.com" not in serialized


def test_model_error_records_type_without_exception_message(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("test"))

    def fail():
        raise RuntimeError("PII-TOKEN-XYZ")

    try:
        call_model(
            fail,
            model="test-model-v1",
            provider="test",
            surface="summary",
            workflow_step="test",
        )
    except RuntimeError:
        pass

    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.attributes["app.ai.outcome"] == "error"
    assert not span.events
    assert "PII-TOKEN-XYZ" not in repr(span.attributes)
