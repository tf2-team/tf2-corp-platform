#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the Bedrock-only Shopping Copilot path."""

import sys
import time
from types import SimpleNamespace

import pytest

from copilot_contracts import ShoppingIntent


def test_converse_json_uses_profile_and_validates_response(monkeypatch):
    import bedrock_runtime

    calls = []

    class FakeClient:
        def converse(self, **kwargs):
            calls.append(kwargs)
            return {
                "output": {
                    "message": {
                        "content": [{"text": '{"query":"headphones","is_shopping_related":true}'}]
                    }
                }
            }

    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FakeClient()))

    result = bedrock_runtime.converse_json(ShoppingIntent, "system", "user")

    assert result.query == "headphones"
    assert calls[0]["modelId"] == "global.amazon.nova-2-lite-v1:0"
    assert calls[0]["inferenceConfig"]["temperature"] == 0.0


def test_parse_intent_uses_bedrock_without_openai_key(monkeypatch):
    import intent_parser

    expected = ShoppingIntent(query="headphones", is_shopping_related=True)
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(intent_parser, "converse_json", lambda *_: expected)
    monkeypatch.setattr(intent_parser, "_get_instructor_client", lambda: (_ for _ in ()).throw(AssertionError()))

    assert intent_parser.parse_intent("Find headphones") == expected


def test_external_schema_mismatch_fault_is_rejected(monkeypatch):
    import bedrock_runtime
    from techx_ai_common import bedrock

    old_config = bedrock._get_config()
    try:
        monkeypatch.setenv("BEDROCK_FAULT_MODE", "schema_mismatch")
        monkeypatch.setenv("BEDROCK_MAX_ATTEMPTS", "1")
        monkeypatch.setenv("BEDROCK_SCHEMA_MAX_ATTEMPTS", "2")
        monkeypatch.setenv("BEDROCK_TOTAL_DEADLINE_SECONDS", "1")
        bedrock.reload_config()
        bedrock.reset_breaker_state()

        with pytest.raises(bedrock_runtime.InvalidModelOutputError):
            bedrock_runtime.converse_json(
                ShoppingIntent,
                "system",
                "find headphones",
            )
    finally:
        bedrock._config = old_config
        bedrock.reset_breaker_state()


def test_external_sustained_fault_opens_breaker_and_recovers(monkeypatch):
    import bedrock_runtime
    from techx_ai_common import bedrock

    old_config = bedrock._get_config()
    try:
        monkeypatch.setenv("BEDROCK_FAULT_MODE", "server_error")
        monkeypatch.setenv("BEDROCK_MAX_ATTEMPTS", "1")
        monkeypatch.setenv("BEDROCK_SCHEMA_MAX_ATTEMPTS", "1")
        monkeypatch.setenv("BEDROCK_BREAKER_FAILURE_THRESHOLD", "3")
        monkeypatch.setenv("BEDROCK_BREAKER_RECOVERY_SECONDS", "0.01")
        monkeypatch.setenv("BEDROCK_TOTAL_DEADLINE_SECONDS", "1")
        monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
        bedrock.reload_config()
        bedrock.reset_breaker_state()

        for _ in range(3):
            with pytest.raises(bedrock_runtime.BedrockUnavailableError):
                bedrock_runtime.converse_json(
                    ShoppingIntent,
                    "system",
                    "find headphones",
                )

        assert bedrock_runtime.get_breaker_state() == "OPEN"
        with pytest.raises(bedrock_runtime.CircuitBreakerOpenError):
            bedrock_runtime.converse_json(
                ShoppingIntent,
                "system",
                "find headphones",
            )

        monkeypatch.setenv("BEDROCK_FAULT_MODE", "none")

        class HealthyClient:
            def converse(self, **_kwargs):
                return {
                    "output": {
                        "message": {
                            "content": [{"text": '{"query":"headphones"}'}]
                        }
                    }
                }

        monkeypatch.setattr(bedrock, "_client_factory", lambda: HealthyClient())
        time.sleep(0.02)

        result = bedrock_runtime.converse_json(
            ShoppingIntent,
            "system",
            "find headphones",
        )

        assert result.query == "headphones"
        assert bedrock_runtime.get_breaker_state() == "CLOSED"
    finally:
        bedrock._config = old_config
        bedrock.reset_breaker_state()
