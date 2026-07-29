#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

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


def test_cart_tool_resolves_exact_product_name(monkeypatch):
    import react_agent
    from copilot_contracts import PendingCartAction

    def product(product_id, name):
        return SimpleNamespace(
            id=product_id,
            name=name,
            description="",
            price_usd=SimpleNamespace(units=10, nanos=0, currency_code="USD"),
            categories=["flashlights"],
        )

    deps = SimpleNamespace(
        catalog_stub=MagicMock(),
        valkey_client=MagicMock(),
    )
    deps.catalog_stub.SearchProducts.return_value = SimpleNamespace(results=[
        product("WHITE", "White Flashlight"),
        product("RED", "Red Flashlight"),
    ])
    monkeypatch.setattr(
        react_agent,
        "create_pending_token",
        lambda user_id, product_id, quantity, _client: PendingCartAction(
            token="token",
            user_id=user_id,
            product_id=product_id,
            quantity=quantity,
        ),
    )
    state = {
        "user_id": "eval-user",
        "conversation_id": "",
        "allowed_product_ids": [],
    }

    result = react_agent._run_tool(
        "prepare_cart_action",
        {"product_name": "Red Flashlight", "quantity": 1},
        state,
        deps,
    )

    assert result["product_id"] == "RED"
    assert state["pending_action"].product_id == "RED"


def test_tool_loop_failure_does_not_promote_partial_results():
    import react_agent
    from copilot_contracts import CopilotStatus

    state = {
        "status": CopilotStatus.GROUNDED,
        "catalog_results": [SimpleNamespace(product_id="RED")],
        "pending_action": None,
    }

    react_agent._tool_loop_failure(state)

    assert state["status"] == CopilotStatus.FALLBACK


def test_runtime_tool_failure_is_fallback_and_not_cache_eligible(monkeypatch):
    import react_agent
    from copilot_contracts import CopilotStatus

    monkeypatch.setattr(
        react_agent,
        "search_catalog",
        lambda *_: (_ for _ in ()).throw(RuntimeError("catalog unavailable")),
    )
    state = {
        "status": CopilotStatus.GROUNDED,
        "cache_eligible": True,
    }

    result = react_agent._run_tool(
        "search_catalog",
        {"query": "telescope", "max_price": 150},
        state,
        SimpleNamespace(catalog_stub=MagicMock()),
    )

    assert result == {
        "error": "The requested store operation is temporarily unavailable."
    }
    assert state["status"] == CopilotStatus.FALLBACK
    assert state["cache_eligible"] is False
