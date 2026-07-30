#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Hybrid semantic cache adapter for Summary Bot (A1.3).

Shared Valkey adapter: exact key lookup + filtered vector KNN.
Policy (when to cache, how to hash reviews) stays in the caller service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Union

import numpy as np

from .contracts import GroundedResponse, ResponseStatus, SafeReview

logger = logging.getLogger("semantic_cache")

# Default scopes for Summary Bot; callers may override.
DEFAULT_PROMPT_SCOPE = "summary-prompt:v1"
DEFAULT_EMBEDDING_SCOPE = "all-MiniLM-L6-v2:v1"
DEFAULT_INDEX_NAME = "ai_summary_cache_idx"
DEFAULT_KEY_PREFIX = "ai:cache:summary:"

_TAG_ESCAPE_RE = re.compile(r"([,.<>{}\[\]\"':;!@#$%^&*()\-+=~|/\\])")


def _escape_tag(value: str) -> str:
    """Escape RediSearch/Valkey TAG special characters."""
    return _TAG_ESCAPE_RE.sub(r"\\\1", value)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def compute_source_hash(reviews: list) -> str:
    """SHA-256 of sanitized reviews, sorted by source_id.

    Hash input per handoff (no username / PII)::

        source_id | score | normalized text
    """
    rows: List[str] = []
    for r in reviews:
        if hasattr(r, "model_dump"):
            data = r.model_dump()
        elif isinstance(r, dict):
            data = r
        else:
            continue
        source_id = str(data.get("source_id") or data.get("id") or "").strip()
        if not source_id:
            continue
        score = data.get("score")
        score_str = "" if score is None else str(score)
        text = data.get("text") or data.get("description") or ""
        rows.append(f"{source_id}|{score_str}|{_normalize_text(str(text))}")

    rows.sort()
    payload = "\n".join(rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_cache_enabled() -> bool:
    return os.environ.get("AI_CACHE_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class SemanticCache:
    """Exact + semantic hybrid cache with fail-open behaviour."""

    def __init__(
        self,
        index_name: str = DEFAULT_INDEX_NAME,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        ttl_seconds: int = 3600,
        max_distance: float = 0.12,
        hmac_secret: Optional[str] = None,
        client: Any = None,
        kind: str = "summary",
    ):
        self.index_name = index_name
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.max_distance = max_distance
        self.hmac_secret = hmac_secret or "default-local-secret-for-dev"
        self.kind = kind
        self._client = client
        self._client_initialized = client is not None

    @property
    def client(self):
        if not self._client_initialized:
            try:
                self._client = self._create_client()
            except Exception:
                logger.debug("Valkey client init failed (fail-open)", exc_info=True)
                self._client = None
            self._client_initialized = True
        return self._client

    @classmethod
    def from_env(cls) -> "SemanticCache":
        """Build from AI_CACHE_* environment variables."""
        ttl = int(os.environ.get("AI_CACHE_TTL_SECONDS", "3600"))
        max_distance = float(os.environ.get("AI_CACHE_MAX_DISTANCE", "0.12"))
        secret = os.environ.get(
            "AI_CACHE_USER_HMAC_SECRET", "default-local-secret-for-dev"
        )
        return cls(
            ttl_seconds=ttl,
            max_distance=max_distance,
            hmac_secret=secret,
        )

    def _create_client(self):
        import valkey  # lazy: keeps unit tests importable without Valkey installed

        addr = os.environ.get("AI_CACHE_ADDR", "valkey-ai-cache:6379")
        if ":" in addr:
            host, port_str = addr.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                host, port = addr, 6379
        else:
            host, port = addr, 6379

        password = os.environ.get("AI_CACHE_PASSWORD") or None
        use_tls = os.environ.get("AI_CACHE_TLS", "false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        kwargs: Dict[str, Any] = {
            "host": host,
            "port": port,
            "decode_responses": False,
            "socket_timeout": 2.0,
            "socket_connect_timeout": 2.0,
        }
        if password:
            kwargs["password"] = password
        if use_tls:
            kwargs["ssl"] = True
        return valkey.Valkey(**kwargs)

    def _compute_user_scope(self, user_id: str) -> Optional[str]:
        """HMAC user scope. Returns None when cache must be bypassed."""
        if not user_id or user_id.strip().lower() in ("anonymous", "none", "null"):
            return None
        return hmac.new(
            self.hmac_secret.encode("utf-8"),
            user_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _compute_deterministic_key(
        self,
        user_scope: str,
        product_id: str,
        source_hash: str,
        prompt_scope: str,
        model_scope: str,
        embedding_scope: str,
        question_hash: str,
    ) -> str:
        payload = {
            "user_scope": user_scope,
            "product_scope": product_id,
            "source_hash": source_hash,
            "prompt_scope": prompt_scope,
            "model_scope": model_scope,
            "embedding_scope": embedding_scope,
            "question_hash": question_hash,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"{self.key_prefix}{digest}"

    @staticmethod
    def _normalize_question(question: str) -> str:
        return _normalize_text(question)

    def _get_embedding(self, question: str) -> bytes:
        from .retrieval import _get_model

        model = _get_model()
        emb = model.encode(question)
        emb = np.asarray(emb, dtype=np.float32)
        return emb.tobytes()  # little-endian float32

    def lookup(
        self,
        user_id: str,
        product_id: str,
        question: str,
        source_hash: str,
        prompt_scope: str = DEFAULT_PROMPT_SCOPE,
        model_scope: str = "provider:model",
        embedding_scope: str = DEFAULT_EMBEDDING_SCOPE,
    ) -> Optional[Dict[str, Any]]:
        """Return cached answer or None (fail-open / bypass).

        Result keys: answer_data, cache_match (exact|semantic), cache_distance.
        """
        user_scope = self._compute_user_scope(user_id)
        if user_scope is None:
            return None

        question_normalized = self._normalize_question(question)
        question_hash = hashlib.sha256(
            question_normalized.encode("utf-8")
        ).hexdigest()

        key = self._compute_deterministic_key(
            user_scope,
            product_id,
            source_hash,
            prompt_scope,
            model_scope,
            embedding_scope,
            question_hash,
        )

        if self.client is None:
            return None

        try:
            # Stage 1: exact lookup
            record = self.client.hgetall(key)
            if record:
                stored_source = record.get(b"source_hash", b"").decode("utf-8")
                if stored_source == source_hash:
                    answer = json.loads(record[b"answer_json"].decode("utf-8"))
                    return {
                        "answer_data": answer,
                        "cache_match": "exact",
                        "cache_distance": 0.0,
                    }
                logger.debug("Exact match rejected: source_hash mismatch")

            # Stage 2: semantic KNN with hybrid filters
            try:
                embedding = self._get_embedding(question_normalized)
            except Exception:
                logger.debug(
                    "Embedding failed during lookup (fail-open)", exc_info=True
                )
                return None
            return self._semantic_knn_lookup(
                user_scope=user_scope,
                product_id=product_id,
                source_hash=source_hash,
                prompt_scope=prompt_scope,
                model_scope=model_scope,
                embedding_scope=embedding_scope,
                embedding=embedding,
            )
        except Exception:
            logger.debug("Cache lookup failed (fail-open)", exc_info=True)
            return None

    def _semantic_knn_lookup(
        self,
        user_scope: str,
        product_id: str,
        source_hash: str,
        prompt_scope: str,
        model_scope: str,
        embedding_scope: str,
        embedding: bytes,
    ) -> Optional[Dict[str, Any]]:
        filter_expr = (
            f"@kind:{{{_escape_tag(self.kind)}}} "
            f"@user_scope:{{{_escape_tag(user_scope)}}} "
            f"@product_scope:{{{_escape_tag(product_id)}}} "
            f"@source_hash:{{{_escape_tag(source_hash)}}} "
            f"@prompt_scope:{{{_escape_tag(prompt_scope)}}} "
            f"@model_scope:{{{_escape_tag(model_scope)}}} "
            f"@embedding_scope:{{{_escape_tag(embedding_scope)}}}"
        )
        knn_query = f"({filter_expr})=>[KNN 1 @embedding $vec AS dist]"

        try:
            raw = self.client.execute_command(
                "FT.SEARCH",
                self.index_name,
                knn_query,
                "PARAMS",
                "2",
                "vec",
                embedding,
                "LIMIT",
                "0",
                "1",
                "DIALECT",
                "2",
            )
        except Exception:
            logger.error(f"FT.SEARCH failed (fail-open), knn_query={knn_query}", exc_info=True)
            return None

        # raw: [total, key1, [field, value, ...], ...]
        if not raw or raw[0] == 0:
            return None

        fields = raw[2]
        field_dict: Dict[bytes, bytes] = {}
        for i in range(0, len(fields), 2):
            field_dict[fields[i]] = fields[i + 1]

        distance = float(field_dict.get(b"dist", b"1.0"))
        if distance > self.max_distance:
            return None

        answer_json_raw = field_dict.get(b"answer_json")
        if not answer_json_raw:
            return None

        answer = json.loads(answer_json_raw.decode("utf-8"))
        return {
            "answer_data": answer,
            "cache_match": "semantic",
            "cache_distance": distance,
        }

    def store(
        self,
        user_id: str,
        product_id: str,
        question: str,
        source_hash: str,
        answer_payload: Union[GroundedResponse, Dict[str, Any]],
        prompt_scope: str = DEFAULT_PROMPT_SCOPE,
        model_scope: str = "provider:model",
        embedding_scope: str = DEFAULT_EMBEDDING_SCOPE,
    ) -> bool:
        """Cache a GROUNDED payload. Returns True if store attempted successfully."""
        status_value: Any
        if isinstance(answer_payload, GroundedResponse):
            status_value = answer_payload.status
            if status_value != ResponseStatus.GROUNDED and status_value != "GROUNDED":
                return False
            payload = answer_payload.model_dump(mode="json")
        elif isinstance(answer_payload, dict):
            status_value = answer_payload.get("status")
            if status_value not in (ResponseStatus.GROUNDED, "GROUNDED"):
                return False
            payload = answer_payload
        else:
            return False

        user_scope = self._compute_user_scope(user_id)
        if user_scope is None:
            return False

        question_normalized = self._normalize_question(question)
        question_hash = hashlib.sha256(
            question_normalized.encode("utf-8")
        ).hexdigest()

        try:
            embedding = self._get_embedding(question_normalized)
        except Exception:
            logger.debug("Embedding failed during store (fail-open)", exc_info=True)
            return False

        record = {
            "kind": self.kind,
            "user_scope": user_scope,
            "product_scope": product_id,
            "source_hash": source_hash,
            "prompt_scope": prompt_scope,
            "model_scope": model_scope,
            "embedding_scope": embedding_scope,
            "question_hash": question_hash,
            "answer_json": json.dumps(payload, default=str),
            "embedding": embedding,
            "created_at": str(int(time.time())),
        }
        key = self._compute_deterministic_key(
            user_scope,
            product_id,
            source_hash,
            prompt_scope,
            model_scope,
            embedding_scope,
            question_hash,
        )

        if self.client is None:
            return False

        try:
            pipe = self.client.pipeline()
            pipe.hset(key, mapping=record)
            pipe.expire(key, self.ttl_seconds)
            pipe.execute()
            return True
        except Exception:
            logger.debug("Cache store failed (fail-open)", exc_info=True)
            return False
