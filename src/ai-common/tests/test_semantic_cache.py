#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for techx_ai_common.semantic_cache (A1.3).

Covers:
  - Question normalisation
  - HMAC user-scope isolation (anonymous bypass)
  - Deterministic key construction
  - compute_source_hash (source_id | score | text, sorted)
  - Exact lookup hit / miss
  - Semantic KNN lookup (mocked FT.SEARCH)
  - Fail-open behaviour when Valkey is unreachable
  - Only GROUNDED responses are cached
"""

import hashlib
import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from techx_ai_common.semantic_cache import SemanticCache, compute_source_hash


@pytest.fixture
def mock_valkey():
    client = MagicMock()
    # Inject mock client so tests do not open a real Valkey connection.
    cache = SemanticCache(hmac_secret="test-secret-key", client=client)
    return cache, client


@pytest.fixture
def fake_embedding():
    vec = np.ones(384, dtype=np.float32)
    return vec.tobytes()


@pytest.fixture
def grounded_payload():
    return {
        "status": "GROUNDED",
        "answer": "This product is highly rated.",
        "claims": [{"text": "highly rated", "source_ids": ["r1", "r2"]}],
    }


@pytest.fixture
def abstained_payload():
    return {
        "status": "ABSTAINED",
        "answer": "",
        "reason": "Not enough information",
    }


class TestNormalizeQuestion:
    def test_strips_whitespace(self, mock_valkey):
        cache, _ = mock_valkey
        assert cache._normalize_question("  Hello World  ") == "hello world"

    def test_lowercases(self, mock_valkey):
        cache, _ = mock_valkey
        assert cache._normalize_question("Is This Good?") == "is this good?"


class TestUserScope:
    def test_anonymous_bypasses_scope(self, mock_valkey):
        cache, _ = mock_valkey
        assert cache._compute_user_scope("anonymous") is None
        assert cache._compute_user_scope("") is None
        assert cache._compute_user_scope(None) is None

    def test_different_users_get_different_scopes(self, mock_valkey):
        cache, _ = mock_valkey
        assert cache._compute_user_scope("user_alice") != cache._compute_user_scope(
            "user_bob"
        )

    def test_same_user_gets_same_scope(self, mock_valkey):
        cache, _ = mock_valkey
        assert cache._compute_user_scope("user_alice") == cache._compute_user_scope(
            "user_alice"
        )

    def test_scope_is_hex_64_chars(self, mock_valkey):
        cache, _ = mock_valkey
        scope = cache._compute_user_scope("user_alice")
        assert len(scope) == 64
        int(scope, 16)


class TestDeterministicKey:
    def test_key_starts_with_prefix(self, mock_valkey):
        cache, _ = mock_valkey
        key = cache._compute_deterministic_key(
            "scope", "prod1", "srchash", "summary-prompt:v1", "model", "v1", "qhash"
        )
        assert key.startswith("ai:cache:summary:")

    def test_different_source_hash_different_key(self, mock_valkey):
        cache, _ = mock_valkey
        k1 = cache._compute_deterministic_key(
            "scope", "prod1", "hash_old", "v1", "model", "v1", "qhash"
        )
        k2 = cache._compute_deterministic_key(
            "scope", "prod1", "hash_new", "v1", "model", "v1", "qhash"
        )
        assert k1 != k2


class TestComputeSourceHash:
    def test_same_reviews_same_hash(self):
        reviews = [
            {"source_id": "r1", "text": "great", "score": "5"},
            {"source_id": "r2", "text": "bad", "score": "1"},
        ]
        assert compute_source_hash(reviews) == compute_source_hash(reviews)

    def test_different_reviews_different_hash(self):
        r1 = [{"source_id": "r1", "text": "great", "score": "5"}]
        r2 = [
            {"source_id": "r1", "text": "great", "score": "5"},
            {"source_id": "r2", "text": "ok", "score": "3"},
        ]
        assert compute_source_hash(r1) != compute_source_hash(r2)

    def test_order_independent(self):
        r1 = [
            {"source_id": "r2", "text": "b", "score": "2"},
            {"source_id": "r1", "text": "a", "score": "1"},
        ]
        r2 = [
            {"source_id": "r1", "text": "a", "score": "1"},
            {"source_id": "r2", "text": "b", "score": "2"},
        ]
        assert compute_source_hash(r1) == compute_source_hash(r2)

    def test_excludes_username_from_hash_input(self):
        # username must not affect hash (PII isolation)
        a = [{"source_id": "r1", "text": "great", "score": "5", "username": "alice"}]
        b = [{"source_id": "r1", "text": "great", "score": "5", "username": "bob"}]
        assert compute_source_hash(a) == compute_source_hash(b)

    def test_empty_list(self):
        h = compute_source_hash([])
        assert isinstance(h, str) and len(h) == 64
        assert h == hashlib.sha256(b"").hexdigest()

    def test_pydantic_models(self):
        from techx_ai_common.contracts import SafeReview

        r1 = SafeReview(source_id="r1", text="good product", score=5)
        r2 = SafeReview(source_id="r2", text="not bad", score=3)
        h = compute_source_hash([r1, r2])
        assert isinstance(h, str) and len(h) == 64


class TestExactLookup:
    @patch.object(SemanticCache, "_get_embedding")
    def test_exact_hit(self, mock_embed, mock_valkey, fake_embedding):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        stored_answer = {"answer": "Great product!", "claims": [], "status": "GROUNDED"}
        client.hgetall.return_value = {
            b"source_hash": b"abc123",
            b"answer_json": json.dumps(stored_answer).encode(),
            b"embedding": fake_embedding,
        }
        result = cache.lookup(
            user_id="alice",
            product_id="prod1",
            question="Is this good?",
            source_hash="abc123",
        )
        assert result is not None
        assert result["cache_match"] == "exact"
        assert result["cache_distance"] == 0.0
        assert result["answer_data"]["answer"] == "Great product!"
        mock_embed.assert_not_called()

    @patch.object(SemanticCache, "_get_embedding")
    def test_exact_miss_empty_record(self, mock_embed, mock_valkey, fake_embedding):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        client.hgetall.return_value = {}
        client.execute_command.return_value = [0]
        assert (
            cache.lookup(
                user_id="alice",
                product_id="prod1",
                question="Is this good?",
                source_hash="abc123",
            )
            is None
        )

    @patch.object(SemanticCache, "_get_embedding")
    def test_exact_miss_source_hash_mismatch(
        self, mock_embed, mock_valkey, fake_embedding
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        client.hgetall.return_value = {
            b"source_hash": b"old_hash",
            b"answer_json": json.dumps({"answer": "stale"}).encode(),
        }
        client.execute_command.return_value = [0]
        assert (
            cache.lookup(
                user_id="alice",
                product_id="prod1",
                question="Is this good?",
                source_hash="new_hash",
            )
            is None
        )

    @patch.object(SemanticCache, "_get_embedding")
    def test_anonymous_user_bypasses_lookup(
        self, mock_embed, mock_valkey, fake_embedding
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        assert (
            cache.lookup(
                user_id="anonymous",
                product_id="prod1",
                question="q",
                source_hash="h",
            )
            is None
        )
        client.hgetall.assert_not_called()


class TestSemanticKNNLookup:
    @patch.object(SemanticCache, "_get_embedding")
    def test_semantic_hit_within_distance(
        self, mock_embed, mock_valkey, fake_embedding
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        client.hgetall.return_value = {}
        stored_answer = {"answer": "Paraphrased hit!", "claims": []}
        client.execute_command.return_value = [
            1,
            b"ai:cache:summary:some_key",
            [
                b"answer_json",
                json.dumps(stored_answer).encode(),
                b"dist",
                b"0.05",
            ],
        ]
        result = cache.lookup(
            user_id="alice",
            product_id="prod1",
            question="How is this product?",
            source_hash="abc123",
        )
        assert result is not None
        assert result["cache_match"] == "semantic"
        assert result["cache_distance"] == 0.05
        # Ensure hybrid filters include kind + scopes
        args = client.execute_command.call_args[0]
        query = args[2]
        assert "@kind:{summary}" in query
        assert "@product_scope:{prod1}" in query
        assert "@source_hash:{abc123}" in query

    @patch.object(SemanticCache, "_get_embedding")
    def test_semantic_miss_distance_too_far(
        self, mock_embed, mock_valkey, fake_embedding
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        client.hgetall.return_value = {}
        client.execute_command.return_value = [
            1,
            b"ai:cache:summary:some_key",
            [b"answer_json", b'{"answer": "too far"}', b"dist", b"0.50"],
        ]
        assert (
            cache.lookup(
                user_id="alice",
                product_id="prod1",
                question="Something unrelated",
                source_hash="abc123",
            )
            is None
        )


class TestFailOpen:
    @patch.object(SemanticCache, "_get_embedding")
    def test_lookup_fails_open_on_connection_error(
        self, mock_embed, mock_valkey, fake_embedding
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        client.hgetall.side_effect = ConnectionError("Valkey down")
        assert (
            cache.lookup(
                user_id="alice", product_id="prod1", question="test", source_hash="hash"
            )
            is None
        )

    @patch.object(SemanticCache, "_get_embedding")
    def test_store_fails_open_on_connection_error(
        self, mock_embed, mock_valkey, fake_embedding, grounded_payload
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        pipe_mock = MagicMock()
        client.pipeline.return_value = pipe_mock
        pipe_mock.execute.side_effect = ConnectionError("Valkey down")
        assert (
            cache.store(
                user_id="alice",
                product_id="prod1",
                question="test",
                source_hash="hash",
                answer_payload=grounded_payload,
            )
            is False
        )


class TestStoreOnlyGrounded:
    @patch.object(SemanticCache, "_get_embedding")
    def test_grounded_response_is_stored(
        self, mock_embed, mock_valkey, fake_embedding, grounded_payload
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        pipe_mock = MagicMock()
        client.pipeline.return_value = pipe_mock
        assert cache.store(
            user_id="alice",
            product_id="prod1",
            question="good?",
            source_hash="srchash",
            answer_payload=grounded_payload,
        )
        pipe_mock.hset.assert_called_once()
        pipe_mock.expire.assert_called_once()
        pipe_mock.execute.assert_called_once()

    @patch.object(SemanticCache, "_get_embedding")
    def test_abstained_response_is_not_stored(
        self, mock_embed, mock_valkey, fake_embedding, abstained_payload
    ):
        cache, client = mock_valkey
        mock_embed.return_value = fake_embedding
        assert (
            cache.store(
                user_id="alice",
                product_id="prod1",
                question="good?",
                source_hash="srchash",
                answer_payload=abstained_payload,
            )
            is False
        )
        client.pipeline.assert_not_called()


def test_semantic_cache_is_exported_from_shared_package():
    from techx_ai_common import SemanticCache as PublicSemanticCache

    assert PublicSemanticCache is SemanticCache
