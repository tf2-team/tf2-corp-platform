#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Small Valkey-backed store for isolated Shopping Copilot conversations.

The store deliberately keeps only bounded routing context. Product details are
always rehydrated from Catalog by product id; no catalog payload is copied into
Valkey and no state is shared between conversation ids.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("conversation_store")

KEY_PREFIX = "copilot:conversation:"
DEFAULT_TTL_SECONDS = 86400
MAX_RECENT_TURNS = 8
MAX_RESULT_IDS = 10


def _key(conversation_id: str) -> str:
    return f"{KEY_PREFIX}{conversation_id}"


def _memory_turn_key(conversation_id: str, turn_id: str) -> str:
    return f"{KEY_PREFIX}{conversation_id}:memory-turn:{turn_id}"


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state_version": 0,
        "last_turn_sequence": 0,
        "recent_turns": [],
        "last_result_product_ids": [],
        "selected_product_id": "",
        "pending_action_token": "",
        "last_intent_query": "",
        "last_category": "",
    }


def load(conversation_id: str, client: Any) -> dict[str, Any]:
    if not conversation_id or client is None:
        return empty_state()
    try:
        raw = client.get(_key(conversation_id))
        if not raw:
            return empty_state()
        value = json.loads(raw)
        state = empty_state()
        if isinstance(value, dict):
            state.update(value)
        return state
    except Exception as exc:
        logger.warning("Conversation state load failed; using empty state: %s", exc)
        return empty_state()


def begin_turn(
    conversation_id: str,
    turn_id: str,
    client: Any,
) -> dict[str, Any]:
    """Load state and allocate a monotonic sequence, idempotent for retries."""
    state = load(conversation_id, client)
    if not conversation_id or not turn_id or client is None:
        return state
    existing = {item.get("turn_id") for item in state["recent_turns"] if isinstance(item, dict)}
    if turn_id in existing:
        for item in reversed(state["recent_turns"]):
            if item.get("turn_id") == turn_id:
                state["last_turn_sequence"] = int(item.get("turn_sequence", state["last_turn_sequence"]))
                return state
    state["last_turn_sequence"] = int(state["last_turn_sequence"]) + 1
    state["state_version"] = int(state["state_version"]) + 1
    state["recent_turns"] = (
        state["recent_turns"]
        + [{"turn_id": turn_id, "turn_sequence": state["last_turn_sequence"]}]
    )[-MAX_RECENT_TURNS:]
    save(conversation_id, state, client)
    return state


def save(conversation_id: str, state: dict[str, Any], client: Any) -> None:
    if not conversation_id or client is None:
        return
    state = dict(state)
    state["last_result_product_ids"] = list(state.get("last_result_product_ids", []))[-MAX_RESULT_IDS:]
    state["recent_turns"] = list(state.get("recent_turns", []))[-MAX_RECENT_TURNS:]
    ttl = int(os.environ.get("COPILOT_CONVERSATION_TTL_SECONDS", DEFAULT_TTL_SECONDS))
    try:
        client.setex(_key(conversation_id), ttl, json.dumps(state, separators=(",", ":")))
    except Exception as exc:
        logger.warning("Conversation state save failed: %s", exc)


def update_after_catalog(
    conversation_id: str,
    state: dict[str, Any],
    product_ids: list[str],
    selected_product_id: str = "",
    client: Any = None,
) -> dict[str, Any]:
    state = dict(state)
    state["last_result_product_ids"] = product_ids[:MAX_RESULT_IDS]
    if selected_product_id:
        state["selected_product_id"] = selected_product_id
    save(conversation_id, state, client)
    return state


def memory_turn_written(conversation_id: str, turn_id: str, client: Any) -> bool:
    if not conversation_id or not turn_id or client is None:
        return False
    try:
        return bool(client.get(_memory_turn_key(conversation_id, turn_id)))
    except Exception:
        return False


def mark_memory_turn_written(conversation_id: str, turn_id: str, client: Any) -> None:
    if not conversation_id or not turn_id or client is None:
        return
    try:
        ttl = int(os.environ.get("COPILOT_CONVERSATION_TTL_SECONDS", DEFAULT_TTL_SECONDS))
        client.setex(_memory_turn_key(conversation_id, turn_id), ttl, "1")
    except Exception as exc:
        logger.warning("Memory turn marker save failed: %s", exc)
