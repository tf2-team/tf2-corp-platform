#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the Bedrock-only Shopping Copilot path."""

import sys
from types import SimpleNamespace

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
