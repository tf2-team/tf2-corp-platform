#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Run Shopping Copilot against deterministic service doubles for eval."""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


_ROOT = Path(__file__).resolve().parents[2]
for _path in (_ROOT / "src" / "ai-common", _ROOT / "src" / "shopping-copilot"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


class EvalValkey:
    """Small in-memory subset needed by conversation_store and cart safety."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        if not key.startswith("rate_limit:"):
            self.values[key] = value

    def getdel(self, key):
        return self.values.pop(key, None)

    def pipeline(self):
        return self

    def zremrangebyscore(self, *_args): return self
    def zadd(self, *_args): return self
    def zcard(self, *_args): return self
    def expire(self, *_args): return self
    def execute(self): return [None, None, 1, None]


class EvalMem0:
    """Conversation-scoped in-memory Mem0 double with observable reads/writes."""

    def __init__(self, initial_memories=()):
        self.entries = list(initial_memories)
        self.reads = []
        self.writes = []

    def add(self, content, conversation_id, **_kwargs):
        self.entries.append({"memory": content, "conversation_id": conversation_id})
        self.writes.append(content)
        return True

    def search(self, query, conversation_id):
        self.reads.append({"query": query, "conversation_id": conversation_id})
        return [
            {"memory": item["memory"]}
            for item in self.entries
            if item["conversation_id"] == conversation_id
        ]


def _product(value: dict):
    return SimpleNamespace(
        id=value["product_id"], name=value["name"],
        description=value.get("description", ""),
        price_usd=SimpleNamespace(
            units=value.get("price_units", 0), nanos=value.get("price_nanos", 0),
            currency_code=value.get("currency_code", "USD"),
        ),
        categories=value.get("categories", []),
    )


def make_copilot_deps(case: dict):
    """Create Catalog/Review/Cart doubles; the graph and configured LLM are real."""
    from copilot_graph import CopilotDeps

    case_input = case["input"]
    products = [_product(item) for item in case_input.get("mock_catalog_products", [])]
    catalog = MagicMock()
    catalog.SearchProducts.return_value = SimpleNamespace(results=products)
    catalog.GetProduct.side_effect = lambda request: next(
        (item for item in products if item.id == request.id), SimpleNamespace(id="")
    )
    reviews = MagicMock()
    reviews.GetProductReviews.return_value = SimpleNamespace(product_reviews=[
        SimpleNamespace(id=str(index), username="eval", description=item if isinstance(item, str) else item["text"], score="4")
        for index, item in enumerate(case_input.get("mock_reviews", []), 1)
    ])
    return CopilotDeps(catalog, reviews, MagicMock(), EvalValkey())


def iter_copilot_turns(case: dict) -> list[dict]:
    """Return one ordered turn list for either supported Copilot case shape.

    The runner owns invoking each turn with the same dependencies and
    ``conversation_id``. Keeping that state stable is what makes this a
    multi-turn test rather than several unrelated single-turn requests.
    """
    case_input = case["input"]
    if "turns" in case_input:
        return case_input["turns"]
    return [{"user_message": case_input["user_message"]}]


def run_copilot_case(case: dict) -> dict:
    """Run all case turns in order, preserving one in-memory conversation."""
    import copilot_graph
    import react_agent

    deps = make_copilot_deps(case)
    conversation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, case["input"].get("conversation_id", case["case_id"])))
    mem0 = EvalMem0([
        {"memory": memory, "conversation_id": conversation_id}
        for memory in case["input"].get("mock_memories", [])
    ])
    traces = []
    original_run_tool = react_agent._run_tool

    def traced_tool(name, arguments, state, tool_deps):
        traces[-1]["tool_calls"].append({"name": name, "args": arguments or {}})
        return original_run_tool(name, arguments, state, tool_deps)

    with patch.object(copilot_graph.mem0_client, "read_enabled", return_value=True), patch.object(
        copilot_graph.mem0_client, "write_enabled", return_value=True
    ), patch.object(copilot_graph.mem0_client, "search", side_effect=mem0.search), patch.object(
        copilot_graph.mem0_client, "add", side_effect=mem0.add
    ), patch.object(react_agent, "_run_tool", side_effect=traced_tool):
        for index, turn in enumerate(iter_copilot_turns(case)):
            traces.append({"turn_index": index, "tool_calls": []})
            started = time.perf_counter()
            state = copilot_graph.run_copilot(
                turn["user_message"], deps, user_id="eval-user", conversation_id=conversation_id,
                turn_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{conversation_id}:{index}")),
            )
            traced_calls = list(traces[-1]["tool_calls"])
            traces[-1].update(normalize_copilot_output(state, deps.cart_stub))
            traces[-1]["tool_calls"] = traced_calls
            traces[-1]["answer"] = state.get("reason", "")
            traces[-1]["products"] = [item.model_dump() for item in state.get("catalog_results", [])]
            traces[-1]["memory_context"] = state.get("memory_context", "")
            traces[-1]["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            traces[-1]["usage"] = state.get("usage", {})

    final = traces[-1]
    return {
        **final, "turns": traces, "conversation_id": conversation_id,
        "mem0": {"reads": mem0.reads, "writes": mem0.writes},
    }


def normalize_copilot_output(state: dict, cart_stub) -> dict:
    """Extract the stable fields used by deterministic Copilot graders."""
    pending = state.get("pending_action")
    return {
        "status": getattr(state.get("status"), "value", state.get("status")),
        "pending_action": (
            {
                "token": pending.token,
                "product_id": pending.product_id,
                "quantity": pending.quantity,
            }
            if pending
            else None
        ),
        "tool_calls": state.get("tool_calls", []),
        "cart_add_item_called": bool(getattr(cart_stub.AddItem, "called", False)),
    }
