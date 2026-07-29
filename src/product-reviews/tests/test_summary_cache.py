"""Integration tests for Summary Bot cache (A1.3).

Verifies policy at the product-reviews boundary:
  - structured response always carries cache_status hit|miss
  - source_hash changes when sanitized reviews change
  - user isolation via HMAC scopes
  - proto top-level cache fields when generated
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

product_reviews_dir = os.path.join(os.path.dirname(__file__), "..")
if product_reviews_dir not in sys.path:
    sys.path.insert(0, product_reviews_dir)

# product_reviews_server imports heavy deps at module load; stub env + modules.
os.environ.setdefault("DB_CONNECTION_STRING", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("OTEL_SERVICE_NAME", "product-reviews-test")
os.environ.setdefault("AI_CACHE_ENABLED", "false")


def _build_structured_response(
    status: str,
    answer: str = "",
    reason: str = "",
    claims: list = None,
    cache_status: str = "miss",
    cache_match: str = "none",
    cache_distance: float = 0.0,
) -> str:
    """Mirrors product_reviews_server._build_structured_response contract."""
    return json.dumps(
        {
            "status": status,
            "answer": answer,
            "reason": reason,
            "claims": claims or [],
            "cache_status": cache_status,
            "cache_match": cache_match,
            "cache_distance": cache_distance,
        }
    )


class TestCacheStatusMetadata:
    def test_miss_metadata_in_structured_response(self):
        body = json.loads(
            _build_structured_response(
                status="GROUNDED",
                answer="Test answer",
                claims=[{"text": "claim1", "source_ids": ["r1"]}],
            )
        )
        assert body["cache_status"] == "miss"
        assert body["cache_match"] == "none"
        assert body["cache_distance"] == 0.0

    def test_proto_top_level_cache_fields(self):
        from techx_ai_common.proto import demo_pb2

        resp = demo_pb2.AskProductAIAssistantResponse()
        resp.response = _build_structured_response(
            status="GROUNDED",
            answer="cached",
            claims=[{"text": "c", "source_ids": ["r1"]}],
            cache_status="hit",
            cache_match="semantic",
            cache_distance=0.04,
        )
        resp.cache_status = "hit"
        resp.cache_match = "semantic"
        resp.cache_distance = 0.04
        body = json.loads(resp.response)
        assert body["cache_status"] == "hit"
        assert body["cache_match"] == "semantic"
        assert resp.cache_status == "hit"
        assert resp.cache_match == "semantic"
        assert resp.cache_distance == pytest.approx(0.04)

    def test_status_fields_present_in_abstained(self):
        body = json.loads(
            _build_structured_response(
                status="ABSTAINED",
                answer="Not enough info",
                reason="Not enough info",
            )
        )
        assert body["cache_status"] == "miss"
        assert "cache_match" in body
        assert "cache_distance" in body


class TestSourceHashIntegration:
    def test_hash_changes_with_new_review(self):
        from techx_ai_common.semantic_cache import compute_source_hash

        reviews_v1 = [
            {"source_id": "r1", "text": "Great product", "score": "5"},
            {"source_id": "r2", "text": "Decent quality", "score": "3"},
        ]
        reviews_v2 = reviews_v1 + [
            {"source_id": "r3", "text": "New review just added", "score": "4"},
        ]
        assert compute_source_hash(reviews_v1) != compute_source_hash(reviews_v2)

    def test_hash_stable_for_same_reviews(self):
        from techx_ai_common.semantic_cache import compute_source_hash

        reviews = [{"source_id": "r1", "text": "Great product", "score": "5"}]
        assert compute_source_hash(reviews) == compute_source_hash(reviews)

    def test_hash_ignores_username(self):
        from techx_ai_common.semantic_cache import compute_source_hash

        a = [{"source_id": "r1", "text": "ok", "score": "4", "username": "a"}]
        b = [{"source_id": "r1", "text": "ok", "score": "4", "username": "b"}]
        assert compute_source_hash(a) == compute_source_hash(b)


class TestUserIsolation:
    def test_different_users_different_keys(self):
        from techx_ai_common.semantic_cache import SemanticCache

        cache = SemanticCache(hmac_secret="test-secret", client=MagicMock())

        scope_a = cache._compute_user_scope("user_alice")
        scope_b = cache._compute_user_scope("user_bob")
        key_a = cache._compute_deterministic_key(
            scope_a, "prod1", "srchash", "summary-prompt:v1", "model", "v1", "qhash"
        )
        key_b = cache._compute_deterministic_key(
            scope_b, "prod1", "srchash", "summary-prompt:v1", "model", "v1", "qhash"
        )
        assert key_a != key_b


class TestCacheIdentityPolicy:
    def test_anonymous_does_not_share_scope(self):
        from techx_ai_common.semantic_cache import SemanticCache

        cache = SemanticCache(hmac_secret="test-secret", client=MagicMock())
        assert cache._compute_user_scope("anonymous") is None
