#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import sys
from types import SimpleNamespace

from copilot_contracts import RetrievalHint


def test_converse_json_uses_profile_and_validates_response(monkeypatch):
    import bedrock_runtime

    calls = []

    class FakeClient:
        def converse(self, **kwargs):
            calls.append(kwargs)
            return {"output": {"message": {"content": [{"text": '{"is_follow_up":false,"semantic_query":"telescope"}'}]}}}

    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FakeClient()))
    result = bedrock_runtime.converse_json(RetrievalHint, "system", "user")
    assert result.semantic_query == "telescope"
    assert calls[0]["modelId"] == "global.amazon.nova-2-lite-v1:0"


def test_converse_json_accepts_explanatory_text_around_json(monkeypatch):
    import bedrock_runtime

    class FakeClient:
        def converse(self, **_kwargs):
            return {
                "output": {
                    "message": {
                        "content": [{
                            "text": 'Here is the JSON: {"is_follow_up":false,"semantic_query":"telescope"} done.'
                        }]
                    }
                }
            }

    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda *_args, **_kwargs: FakeClient()),
    )

    result = bedrock_runtime.converse_json(RetrievalHint, "system", "user")

    assert result.semantic_query == "telescope"


def test_converse_json_forwards_workflow_step(monkeypatch):
    import bedrock_runtime

    seen = {}

    def fake_converse_json(*args, **kwargs):
        seen["workflow_step"] = kwargs["workflow_step"]
        return RetrievalHint(semantic_query="telescope")

    monkeypatch.setattr(
        bedrock_runtime._shared_bedrock, "converse_json", fake_converse_json
    )

    bedrock_runtime.converse_json(
        RetrievalHint, "system", "user", workflow_step="retrieval_hint"
    )

    assert seen["workflow_step"] == "retrieval_hint"
