#!/usr/bin/python

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_bedrock_tools_are_omitted_when_turn_policy_denies_access(monkeypatch):
    import react_agent

    calls = []

    class FakeClient:
        def converse(self, **kwargs):
            calls.append(kwargs)
            return {"output": {"message": {"content": [{"text": "Noted."}]}}}

    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *_args, **_kwargs: FakeClient()))

    response = react_agent._run_bedrock({"tool_access": "none", "safe_message": "My budget is 200 USD."}, SimpleNamespace())

    assert response == "Noted."
    assert "toolConfig" not in calls[0]


def test_context_does_not_expose_tool_availability():
    import react_agent

    context = react_agent._context({"safe_message": "My budget is 200 USD.", "tool_access": "none"})
    assert "Shopping tools are available" not in context
