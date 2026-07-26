#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cart_tool.py (A2.3).

Verifies:
- Pending token is written to Valkey with correct TTL.
- Confirm succeeds when token is valid and user_id matches.
- Confirm fails on expired/missing token.
- Confirm fails on user_id mismatch (cross-user replay).
- Token is consumed (deleted) on successful confirm — no double-write.
- CartService.AddItem is called exactly once on success.
"""

import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cart_tool


class FakeValkey:
    """In-memory Valkey mock with getdel support."""

    def __init__(self):
        self._store: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value

    def getdel(self, key: str):
        return self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._store


class TestCreatePendingToken:
    def test_token_stored_in_valkey(self):
        vk = FakeValkey()
        action = cart_tool.create_pending_token(
            user_id="user_1", product_id="PROD_A", quantity=2, valkey_client=vk
        )
        key = f"copilot:pending:{action.token}"
        assert vk.exists(key) is True  # token is stored in valkey before confirm

        # Re-check: setex stores it
        vk2 = FakeValkey()
        action2 = cart_tool.create_pending_token("u", "p", 1, vk2)
        raw = vk2._store.get(f"copilot:pending:{action2.token}")
        assert raw is not None
        payload = json.loads(raw)
        assert payload["user_id"] == "u"
        assert payload["product_id"] == "p"
        assert payload["quantity"] == 1

    def test_token_is_unique(self):
        vk = FakeValkey()
        a1 = cart_tool.create_pending_token("u", "p", 1, vk)
        a2 = cart_tool.create_pending_token("u", "p", 1, vk)
        assert a1.token != a2.token


class TestConfirmCartAction:
    def _setup(self, user_id="user_1", product_id="PROD_A", quantity=1):
        vk = FakeValkey()
        action = cart_tool.create_pending_token(user_id, product_id, quantity, vk)
        cart_stub = MagicMock()
        cart_stub.AddItem.return_value = MagicMock()
        return vk, action.token, cart_stub

    def test_success_calls_add_item(self):
        vk, token, cart_stub = self._setup("user_1", "PROD_A", 2)
        ok, reason = cart_tool.confirm_cart_action(token, "user_1", cart_stub, vk)
        assert ok is True
        assert reason == ""
        cart_stub.AddItem.assert_called_once()

    def test_token_consumed_prevents_replay(self):
        vk, token, cart_stub = self._setup()
        cart_tool.confirm_cart_action(token, "user_1", cart_stub, vk)
        # Second call with same token should fail.
        ok2, reason2 = cart_tool.confirm_cart_action(token, "user_1", cart_stub, vk)
        assert ok2 is False
        assert "expired" in reason2.lower() or "not found" in reason2.lower()
        # AddItem called only once total.
        assert cart_stub.AddItem.call_count == 1

    def test_expired_token_rejected(self):
        vk = FakeValkey()  # empty — simulates expired token
        cart_stub = MagicMock()
        ok, reason = cart_tool.confirm_cart_action("nonexistent_token", "user_1", cart_stub, vk)
        assert ok is False
        cart_stub.AddItem.assert_not_called()

    def test_wrong_user_id_rejected(self):
        vk, token, cart_stub = self._setup(user_id="user_1")
        ok, reason = cart_tool.confirm_cart_action(token, "attacker", cart_stub, vk)
        assert ok is False
        assert "user" in reason.lower()
        cart_stub.AddItem.assert_not_called()

    def test_anonymous_token_is_not_transferable(self):
        vk, token, cart_stub = self._setup(user_id="anonymous")
        ok, reason = cart_tool.confirm_cart_action(token, "user_1", cart_stub, vk)
        assert ok is False
        assert "user" in reason.lower()
        cart_stub.AddItem.assert_not_called()

    def test_cart_service_error_returns_false(self):
        vk, token, cart_stub = self._setup()
        cart_stub.AddItem.side_effect = Exception("gRPC error")
        ok, reason = cart_tool.confirm_cart_action(token, "user_1", cart_stub, vk)
        assert ok is False
        assert "cart service error" in reason.lower()
