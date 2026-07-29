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


def search(query: str, conversation_id: str) -> list[dict]:
    """Return scoped active memories; every transport/schema failure is a miss."""
    if not read_enabled() or not query or not conversation_id:
        return []
    try:
        response = _request(
            "/search",
            {
                "query": query[:500],
                "filters": {
                    "run_id": conversation_id,
                    "agent_id": os.environ.get("MEM0_AGENT_ID", AGENT_ID),
                    "schema_version": SCHEMA_VERSION,
                },
                "top_k": int(os.environ.get("MEM0_TOP_K", "5")),
                "show_expired": False,
            },
        )
        results = response.get("results", [])
        return [item for item in results if isinstance(item, dict)]
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Mem0 search unavailable: %s", type(exc).__name__)
        return []


def add(
    content: str,
    conversation_id: str,
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
        _request(
            "/memories",
            {
                "messages": [{"role": "user", "content": content[:500]}],
                "run_id": conversation_id,
                "agent_id": os.environ.get("MEM0_AGENT_ID", AGENT_ID),
                "metadata": metadata,
                "expiration_date": (date.today() + timedelta(days=ttl_days)).isoformat(),
                "infer": False,
            },
        )
        return True
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Mem0 write unavailable: %s", type(exc).__name__)
        return False
