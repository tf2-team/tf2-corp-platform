#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Fail-open REST client for the self-hosted Mem0 service."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opentelemetry import trace


logger = logging.getLogger("mem0_client")
AGENT_ID = "shopping-copilot"
SCHEMA_VERSION = 1


def read_enabled() -> bool:
    return os.environ.get("MEM0_READ_ENABLED", "false").lower() == "true"


def write_enabled() -> bool:
    return os.environ.get("MEM0_WRITE_ENABLED", "false").lower() == "true"


def _request(path: str, payload: dict) -> dict:
    url = f"{os.environ.get('MEM0_API_URL', 'http://mem0:8000').rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("MEM0_API_KEY", "")
    if api_key:
        headers["X-API-Key"] = api_key
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = max(0.05, int(os.environ.get("MEM0_TIMEOUT_MS", "500")) / 1000)
    with urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
        return value if isinstance(value, dict) else {}


def _profile_user_id(user_id: str) -> str:
    value = (user_id or "").strip()
    return value if value.lower() not in {"anonymous", "none", "null"} else ""


def search(query: str, conversation_id: str = "", user_id: str = "") -> list[dict]:
    """Return active session and browser-profile memories; failures are misses."""
    if not read_enabled() or not query:
        return []
    filters = [
        {"run_id": conversation_id},
        {"user_id": _profile_user_id(user_id)},
    ]
    with trace.get_tracer("shopping-copilot").start_as_current_span(
        "retrieval mem0",
        attributes={"app.ai.retrieval.source": "mem0"},
    ) as span:
        try:
            results: list[dict] = []
            seen: set[str] = set()
            for scope in filters:
                if not next(iter(scope.values())):
                    continue
                try:
                    response = _request(
                        "/search",
                        {
                            "query": query[:500],
                            "filters": {
                                **scope,
                                "agent_id": os.environ.get("MEM0_AGENT_ID", AGENT_ID),
                                "schema_version": SCHEMA_VERSION,
                            },
                            "top_k": int(os.environ.get("MEM0_TOP_K", "5")),
                            "show_expired": False,
                        },
                    )
                except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                    logger.warning("Mem0 search unavailable: %s", type(exc).__name__)
                    continue
                for item in response.get("results", []):
                    if not isinstance(item, dict):
                        continue
                    memory_id = str(item.get("id") or item.get("memory") or "")
                    if memory_id and memory_id not in seen:
                        seen.add(memory_id)
                        results.append(item)
            span.set_attribute("app.ai.retrieval.result_count", len(results))
            span.set_attribute("app.ai.outcome", "ok")
            return results
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("error.type", type(exc).__name__)
            logger.warning("Mem0 search unavailable: %s", type(exc).__name__)
            return []


def add(
    content: str,
    conversation_id: str,
    user_id: str,
    turn_id: str,
    turn_sequence: int,
    memory_kind: str,
    constraint_type: str | None = None,
) -> bool:
    """Append one already-extracted fact without asking Mem0 to infer it again."""
    if not write_enabled() or not content or not conversation_id or not turn_id:
        return False
    ttl_days = int(os.environ.get("MEM0_MEMORY_TTL_DAYS", "30"))
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "memory_kind": memory_kind,
        "source_turn_id": turn_id,
        "source_turn_sequence": turn_sequence,
    }
    if constraint_type:
        metadata["constraint_type"] = constraint_type
    try:
        payload = {
            "messages": [{"role": "user", "content": content[:500]}],
            "run_id": conversation_id,
            "agent_id": os.environ.get("MEM0_AGENT_ID", AGENT_ID),
            "metadata": metadata,
            "infer": False,
        }
        if ttl_days > 0:
            payload["expiration_date"] = (date.today() + timedelta(days=ttl_days)).isoformat()
        profile_user_id = _profile_user_id(user_id)
        if profile_user_id:
            # ponytail: browser UUID is anonymous and single-device; use an auth subject for cross-device memory.
            payload["user_id"] = profile_user_id
        _request(
            "/memories",
            payload,
        )
        return True
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Mem0 write unavailable: %s", type(exc).__name__)
        return False
