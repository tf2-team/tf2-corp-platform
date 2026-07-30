#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Request-level hybrid cache policy for the stateful Shopping Copilot.

The shared ``SemanticCache`` owns Valkey exact/KNN mechanics. This module owns
Copilot-specific policy: conversation scoping, source snapshots, safe payload
serialization, response hydration, and cacheability rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any

from techx_ai_common.contracts import GroundedResponse, SafeReviewSet
from techx_ai_common.semantic_cache import (
    DEFAULT_EMBEDDING_SCOPE,
    SemanticCache,
    compute_source_hash,
    is_cache_enabled,
)
from techx_ai_common.proto import demo_pb2

from copilot_contracts import CopilotProductResult, CopilotStatus
import conversation_store
import mem0_client
import metrics as copilot_metrics


logger = logging.getLogger("shopping_cache")

INDEX_NAME = "ai_copilot_cache_idx"
KEY_PREFIX = "ai:cache:copilot:"
KIND = "shopping-copilot"
PROMPT_SCOPE = "shopping-react-agent:v1"
_ACTION_RE = re.compile(
    r"\b(add|buy|purchase|checkout|confirm|remove|delete|clear)\b.{0,30}\b(cart|basket|order)\b"
    r"|\b(cart|basket)\b.{0,30}\b(add|remove|delete|clear|confirm)\b"
    r"|\bthêm\b.{0,30}\bgiỏ\b|\bxoá\b.{0,30}\bgiỏ\b",
    re.IGNORECASE,
)


def create_cache() -> SemanticCache | None:
    if not is_cache_enabled():
        return None
    try:
        return SemanticCache(
            index_name=INDEX_NAME,
            key_prefix=KEY_PREFIX,
            ttl_seconds=int(os.environ.get("AI_CACHE_TTL_SECONDS", "3600")),
            max_distance=float(os.environ.get("AI_CACHE_MAX_DISTANCE", "0.12")),
            hmac_secret=os.environ.get(
                "AI_CACHE_USER_HMAC_SECRET", "default-local-secret-for-dev"
            ),
            kind=KIND,
        )
    except (TypeError, ValueError):
        logger.warning("Invalid AI cache configuration; disabling cache", exc_info=True)
        return None


def _model_scope() -> str:
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    if provider == "bedrock":
        model = os.environ.get("BEDROCK_MODEL_ID", "unknown")
    else:
        model = os.environ.get("LLM_MODEL", "unknown")
    return f"{provider}:{model}"


def _request_scope(question: str) -> str:
    normalized = " ".join(question.lower().split())
    if any(word in normalized for word in ("remember", "recall", "nhớ")):
        return "memory"
    if any(word in normalized for word in ("find", "recommend", "option", "search", "tìm", "gợi ý")):
        return "discovery"
    if any(word in normalized for word in ("review", "rating", "detail", "describe", "đánh giá", "chi tiết")):
        return "product"
    if any(word in normalized for word in ("budget", "prefer", "need", "want", "ngân sách", "muốn", "cần")):
        return "preference"
    return "general"


def _cacheable_question(question: str) -> bool:
    return not bool(_ACTION_RE.search(question))


def _conversation_scope(
    cache: SemanticCache,
    conversation_id: str,
    question: str,
) -> str:
    value = f"{conversation_id or 'stateless'}:{_request_scope(question)}"
    return hmac.new(
        cache.hmac_secret.encode("utf-8"),
        f"conversation:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _stable_conversation_state(conversation_id: str, client: Any) -> dict[str, Any]:
    stored = conversation_store.load(conversation_id, client)
    return {
        "last_result_product_ids": list(stored.get("last_result_product_ids", [])),
        "selected_product_id": stored.get("selected_product_id", ""),
        "last_intent_query": stored.get("last_intent_query", ""),
        "last_category": stored.get("last_category", ""),
    }


def _memory_fingerprint(question: str, conversation_id: str) -> list[str]:
    if not mem0_client.read_enabled() or not conversation_id:
        return []
    memories = mem0_client.search(question, conversation_id)
    return sorted(
        item["memory"].strip()
        for item in memories
        if isinstance(item.get("memory"), str) and item["memory"].strip()
    )


def _catalog_and_review_fingerprint(
    product_ids: list[str],
    deps: Any,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for product_id in sorted(set(product_ids)):
        try:
            product = deps.catalog_stub.GetProduct(
                demo_pb2.GetProductRequest(id=product_id)
            )
            product_data = {
                "product_id": getattr(product, "id", "") or product_id,
                "name": getattr(product, "name", ""),
                "description": getattr(product, "description", ""),
                "picture": getattr(product, "picture", ""),
                "price_units": getattr(product.price_usd, "units", 0),
                "price_nanos": getattr(product.price_usd, "nanos", 0),
                "currency_code": getattr(product.price_usd, "currency_code", ""),
                "categories": sorted(getattr(product, "categories", [])),
            }
        except Exception:
            product_data = {"product_id": product_id, "unavailable": True}

        review_hash = ""
        try:
            response = deps.reviews_stub.GetProductReviews(
                demo_pb2.GetProductReviewsRequest(product_id=product_id)
            )
            review_hash = compute_source_hash(
                [
                    {
                        "source_id": review.id,
                        "score": review.score,
                        "description": review.description,
                    }
                    for review in response.product_reviews
                ]
            )
        except Exception:
            review_hash = "unavailable"

        sources.append({"catalog": product_data, "review_hash": review_hash})
    return sources


def compute_source_snapshot(
    question: str,
    conversation_id: str,
    deps: Any,
) -> str:
    conversation = _stable_conversation_state(conversation_id, deps.valkey_client)
    payload = {
        "conversation": conversation,
        "memory": _memory_fingerprint(question, conversation_id),
        "sources": _catalog_and_review_fingerprint(
            conversation["last_result_product_ids"], deps
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def lookup(
    cache: SemanticCache | None,
    user_id: str,
    conversation_id: str,
    question: str,
    deps: Any,
) -> dict[str, Any] | None:
    if (
        cache is None
        or not conversation_id
        or not user_id
        or user_id.strip().lower() in ("anonymous", "none", "null")
        or not _cacheable_question(question)
    ):
        copilot_metrics.record_cache_lookup("bypass")
        return None

    started = time.perf_counter()
    try:
        source_hash = compute_source_snapshot(question, conversation_id, deps)
        result = cache.lookup(
            user_id=user_id,
            product_id=_conversation_scope(cache, conversation_id, question),
            question=question,
            source_hash=source_hash,
            prompt_scope=PROMPT_SCOPE,
            model_scope=_model_scope(),
            embedding_scope=DEFAULT_EMBEDDING_SCOPE,
        )
        duration_ms = (time.perf_counter() - started) * 1000
        if result is None:
            copilot_metrics.record_cache_lookup("miss", "none", duration_ms)
            return None
        return {**result, "_lookup_duration_ms": duration_ms}
    except Exception:
        copilot_metrics.record_cache_lookup(
            "error", "none", (time.perf_counter() - started) * 1000
        )
        return None


def record_hit(cache_result: dict[str, Any]) -> None:
    copilot_metrics.record_cache_lookup(
        "hit",
        cache_result["cache_match"],
        float(cache_result.get("_lookup_duration_ms", 0.0)),
    )


def record_invalid_hit(cache_result: dict[str, Any]) -> None:
    copilot_metrics.record_cache_lookup(
        "error",
        "none",
        float(cache_result.get("_lookup_duration_ms", 0.0)),
    )


def serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    qa_result = state.get("qa_result")
    safe_reviews = state.get("safe_reviews")
    return {
        "status": "GROUNDED",
        "state": {
            "reason": state.get("reason", ""),
            "interpreted_criteria": state.get("interpreted_criteria", ""),
            "catalog_results": [
                product.model_dump(mode="json")
                for product in state.get("catalog_results", [])
            ],
            "qa_result": (
                qa_result.model_dump(mode="json") if qa_result is not None else None
            ),
            "safe_reviews": (
                safe_reviews.model_dump(mode="json")
                if safe_reviews is not None
                else None
            ),
        },
    }


def hydrate_state(
    initial_state: dict[str, Any],
    cache_result: dict[str, Any],
) -> dict[str, Any]:
    cached = cache_result["answer_data"]["state"]
    qa_payload = cached.get("qa_result")
    reviews_payload = cached.get("safe_reviews")
    return {
        **initial_state,
        "status": CopilotStatus.GROUNDED,
        "reason": cached.get("reason", ""),
        "interpreted_criteria": cached.get("interpreted_criteria", ""),
        "catalog_results": [
            CopilotProductResult.model_validate(product)
            for product in cached.get("catalog_results", [])
        ],
        "qa_result": (
            GroundedResponse.model_validate(qa_payload) if qa_payload else None
        ),
        "safe_reviews": (
            SafeReviewSet.model_validate(reviews_payload) if reviews_payload else None
        ),
        "cache_status": "hit",
        "cache_match": cache_result["cache_match"],
        "cache_distance": float(cache_result["cache_distance"]),
    }


def store(
    cache: SemanticCache | None,
    state: dict[str, Any],
    deps: Any,
) -> bool:
    if (
        cache is None
        or state.get("status") != CopilotStatus.GROUNDED
        or state.get("cache_eligible") is False
        or state.get("pending_action") is not None
        or not state.get("conversation_id")
        or not _cacheable_question(state.get("safe_message", ""))
    ):
        return False
    try:
        return cache.store(
            user_id=state["user_id"],
            product_id=_conversation_scope(
                cache, state["conversation_id"], state["safe_message"]
            ),
            question=state["safe_message"],
            source_hash=compute_source_snapshot(
                state["safe_message"], state["conversation_id"], deps
            ),
            answer_payload=serialize_state(state),
            prompt_scope=PROMPT_SCOPE,
            model_scope=_model_scope(),
            embedding_scope=DEFAULT_EMBEDDING_SCOPE,
        )
    except Exception:
        return False
