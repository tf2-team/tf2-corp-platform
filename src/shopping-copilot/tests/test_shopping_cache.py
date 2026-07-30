#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from copilot_contracts import CopilotStatus, RetrievalHint
from copilot_graph import CopilotDeps, run_copilot
from techx_ai_common.proto import demo_pb2
import shopping_cache
import metrics as copilot_metrics


CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"
TURN_ID = "22222222-2222-4222-8222-222222222222"


class FakeCache:
    hmac_secret = "test-secret"

    def __init__(self, lookup_result=None, lookup_error=None):
        self.lookup_result = lookup_result
        self.lookup_error = lookup_error
        self.lookup_calls = []
        self.store_calls = []

    def lookup(self, **kwargs):
        self.lookup_calls.append(kwargs)
        if self.lookup_error:
            raise self.lookup_error
        return self.lookup_result

    def store(self, **kwargs):
        self.store_calls.append(kwargs)
        return True


def _deps(cache):
    return CopilotDeps(
        catalog_stub=MagicMock(),
        reviews_stub=MagicMock(),
        cart_stub=MagicMock(),
        valkey_client=MagicMock(),
        semantic_cache=cache,
    )


def _cached_result(match="exact", distance=0.0):
    return {
        "answer_data": {
            "status": "GROUNDED",
            "state": {
                "reason": "Cached answer",
                "interpreted_criteria": "",
                "catalog_results": [],
                "qa_result": None,
                "safe_reviews": None,
            },
        },
        "cache_match": match,
        "cache_distance": distance,
    }


def test_create_cache_initializes_runtime_dependency(monkeypatch):
    monkeypatch.setenv("AI_CACHE_ENABLED", "true")
    monkeypatch.setenv("AI_CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("AI_CACHE_MAX_DISTANCE", "0.25")
    monkeypatch.setenv("AI_CACHE_USER_HMAC_SECRET", "test-secret")

    cache = shopping_cache.create_cache()

    assert cache is not None
    assert cache.kind == "shopping-copilot"
    assert cache.index_name == "ai_copilot_cache_idx"
    assert cache.ttl_seconds == 120
    assert cache.max_distance == 0.25


def test_create_cache_invalid_configuration_fails_open(monkeypatch):
    monkeypatch.setenv("AI_CACHE_ENABLED", "true")
    monkeypatch.setenv("AI_CACHE_TTL_SECONDS", "not-an-integer")

    assert shopping_cache.create_cache() is None


def _stub_miss_path(monkeypatch):
    import copilot_graph

    monkeypatch.setattr(
        copilot_graph.memory_retrieval,
        "parse_retrieval_hint",
        lambda *_: RetrievalHint(
            semantic_query="telescope",
            tool_access="none",
            policy_action="allow",
        ),
    )
    monkeypatch.setattr(copilot_graph, "run_react_agent", lambda *_: "Fresh answer")


def test_exact_hit_skips_all_model_nodes(monkeypatch):
    import copilot_graph

    cache = FakeCache(_cached_result())
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")
    monkeypatch.setattr(
        copilot_graph.memory_retrieval,
        "parse_retrieval_hint",
        lambda *_: (_ for _ in ()).throw(AssertionError("retrieval model called")),
    )
    monkeypatch.setattr(
        copilot_graph,
        "run_react_agent",
        lambda *_: (_ for _ in ()).throw(AssertionError("agent model called")),
    )

    state = run_copilot(
        "Find a telescope",
        deps,
        "shopper-1",
        CONVERSATION_ID,
        TURN_ID,
    )

    assert state["status"] == CopilotStatus.GROUNDED
    assert state["reason"] == "Cached answer"
    assert state["cache_status"] == "hit"
    assert state["cache_match"] == "exact"
    assert cache.store_calls == []


def test_miss_runs_agent_and_stores_grounded_response(monkeypatch):
    cache = FakeCache()
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")
    _stub_miss_path(monkeypatch)

    state = run_copilot(
        "Find a telescope",
        deps,
        "shopper-1",
        CONVERSATION_ID,
        TURN_ID,
    )

    assert state["reason"] == "Fresh answer"
    assert state["cache_status"] == "miss"
    assert len(cache.store_calls) == 1
    assert cache.store_calls[0]["answer_payload"]["status"] == "GROUNDED"


def test_cache_failure_is_fail_open(monkeypatch):
    cache = FakeCache(lookup_error=RuntimeError("valkey unavailable"))
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")
    _stub_miss_path(monkeypatch)

    state = run_copilot(
        "Find a telescope",
        deps,
        "shopper-1",
        CONVERSATION_ID,
        TURN_ID,
    )

    assert state["status"] == CopilotStatus.GROUNDED
    assert state["reason"] == "Fresh answer"
    assert state["cache_status"] == "miss"


def test_malformed_cache_entry_is_fail_open(monkeypatch):
    cache = FakeCache(
        {
            "answer_data": {"status": "GROUNDED", "unexpected": True},
            "cache_match": "exact",
            "cache_distance": 0.0,
        }
    )
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")
    _stub_miss_path(monkeypatch)

    state = run_copilot(
        "Find a telescope",
        deps,
        "shopper-1",
        CONVERSATION_ID,
        TURN_ID,
    )

    assert state["status"] == CopilotStatus.GROUNDED
    assert state["reason"] == "Fresh answer"
    assert state["cache_status"] == "miss"


def test_pending_cart_action_is_not_cached(monkeypatch):
    import copilot_graph

    cache = FakeCache()
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")
    _stub_miss_path(monkeypatch)

    def agent_with_action(state, _deps):
        state["pending_action"] = MagicMock()
        return "Please confirm the cart action."

    monkeypatch.setattr(copilot_graph, "run_react_agent", agent_with_action)

    run_copilot(
        "Add it to my cart",
        deps,
        "shopper-1",
        CONVERSATION_ID,
        TURN_ID,
    )

    assert cache.lookup_calls == []
    assert cache.store_calls == []


def test_tool_error_response_is_not_cached():
    cache = FakeCache()
    deps = _deps(cache)
    state = {
        "status": CopilotStatus.GROUNDED,
        "cache_eligible": False,
        "pending_action": None,
        "conversation_id": CONVERSATION_ID,
        "safe_message": "Find a telescope",
        "user_id": "shopper-1",
    }

    assert shopping_cache.store(cache, state, deps) is False
    assert cache.store_calls == []


def test_conversation_scope_isolated_without_raw_session_id(monkeypatch):
    cache = FakeCache()
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")

    shopping_cache.lookup(cache, "shopper-1", CONVERSATION_ID, "question", deps)
    shopping_cache.lookup(
        cache,
        "shopper-1",
        "33333333-3333-4333-8333-333333333333",
        "question",
        deps,
    )

    first_scope = cache.lookup_calls[0]["product_id"]
    second_scope = cache.lookup_calls[1]["product_id"]
    assert first_scope != second_scope
    assert CONVERSATION_ID not in first_scope


def test_semantic_cache_is_partitioned_by_request_type(monkeypatch):
    cache = FakeCache()
    deps = _deps(cache)
    monkeypatch.setattr(shopping_cache, "compute_source_snapshot", lambda *_: "source-v1")

    shopping_cache.lookup(
        cache, "shopper-1", CONVERSATION_ID, "Find a telescope", deps
    )
    shopping_cache.lookup(
        cache, "shopper-1", CONVERSATION_ID, "What do you remember?", deps
    )

    assert cache.lookup_calls[0]["product_id"] != cache.lookup_calls[1]["product_id"]


def test_source_snapshot_changes_with_catalog_or_reviews(monkeypatch):
    deps = _deps(FakeCache())
    monkeypatch.setattr(
        shopping_cache.conversation_store,
        "load",
        lambda *_: {
            "last_result_product_ids": ["product-1"],
            "selected_product_id": "product-1",
            "last_intent_query": "telescope",
            "last_category": "telescopes",
        },
    )
    product = demo_pb2.Product(
        id="product-1",
        name="Portable Telescope",
        description="Original description",
        categories=["telescopes"],
    )
    product.price_usd.units = 199
    deps.catalog_stub.GetProduct.return_value = product
    deps.reviews_stub.GetProductReviews.return_value = (
        demo_pb2.GetProductReviewsResponse(
            product_reviews=[
                demo_pb2.ProductReview(
                    id="review-1", score="5", description="Great optics"
                )
            ]
        )
    )

    original = shopping_cache.compute_source_snapshot(
        "Find a telescope", CONVERSATION_ID, deps
    )
    product.description = "Updated description"
    catalog_changed = shopping_cache.compute_source_snapshot(
        "Find a telescope", CONVERSATION_ID, deps
    )
    product.description = "Original description"
    deps.reviews_stub.GetProductReviews.return_value.product_reviews[
        0
    ].description = "Updated review"
    review_changed = shopping_cache.compute_source_snapshot(
        "Find a telescope", CONVERSATION_ID, deps
    )

    assert catalog_changed != original
    assert review_changed != original


def test_cache_and_model_metrics_are_recorded():
    class Instrument:
        def __init__(self):
            self.values = []

        def add(self, value, attributes):
            self.values.append((value, attributes))

        def record(self, value, attributes):
            self.values.append((value, attributes))

    class Meter:
        def __init__(self):
            self.instruments = {}

        def create_counter(self, name, **_kwargs):
            self.instruments[name] = Instrument()
            return self.instruments[name]

        def create_histogram(self, name, **_kwargs):
            self.instruments[name] = Instrument()
            return self.instruments[name]

    meter = Meter()
    copilot_metrics.init_metrics(meter)
    copilot_metrics.record_cache_lookup("hit", "exact", 2.5)
    copilot_metrics.record_model_call("bedrock", 12, 4)

    assert meter.instruments["shopping_copilot_cache_requests_total"].values
    assert meter.instruments["shopping_copilot_cache_lookup_duration_ms"].values
    assert meter.instruments["shopping_copilot_model_calls_total"].values
    assert meter.instruments["shopping_copilot_model_input_tokens_total"].values[0][0] == 12
    assert meter.instruments["shopping_copilot_model_output_tokens_total"].values[0][0] == 4
