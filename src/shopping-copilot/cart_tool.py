#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Cart confirmation tool for Shopping Copilot (A2.3).

AI NEVER calls CartService.AddItem directly. This module only:
  1. Creates a signed pending action token and stores it in Valkey (TTL 5 min).
  2. Provides confirm_cart_action() which validates the token and calls
     CartService.AddItem — this function is called by the ConfirmCartAction
     gRPC RPC, NOT by any LangGraph node.

Public API:
    create_pending_token(user_id, product_id, quantity, valkey_client) -> PendingCartAction
    confirm_cart_action(token, user_id, cart_stub, valkey_client) -> (bool, str)
"""

import json
import logging
import os
import secrets
import valkey as valkeylib
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc
from copilot_contracts import PendingCartAction

logger = logging.getLogger("cart_tool")

# Valkey key namespace for pending cart actions.
_PENDING_KEY_PREFIX = "copilot:pending:"
# Token TTL in seconds (5 minutes). After expiry, confirmation is rejected.
_TOKEN_TTL_SECONDS = 300


def _pending_key(token: str) -> str:
    return f"{_PENDING_KEY_PREFIX}{token}"


def make_valkey_client() -> valkeylib.Valkey:
    """Build a Valkey client from VALKEY_ADDR env var."""
    addr = os.environ.get("VALKEY_ADDR", "valkey-cart:6379")
    host, port_str = addr.rsplit(":", 1)
    return valkeylib.Valkey(host=host, port=int(port_str), decode_responses=True)


def create_pending_token(
    user_id: str,
    product_id: str,
    quantity: int,
    valkey_client: valkeylib.Valkey,
) -> PendingCartAction:
    """Create a pending cart action token and persist it in Valkey.

    The token is a cryptographically random URL-safe string. It is stored
    as a JSON blob under ``copilot:pending:{token}`` with a TTL of
    _TOKEN_TTL_SECONDS. The frontend must send this token back via the
    ConfirmCartAction RPC to execute the actual cart write.

    Returns:
        PendingCartAction with the generated token.
    """
    token = secrets.token_urlsafe(32)
    action = PendingCartAction(
        token=token,
        user_id=user_id,
        product_id=product_id,
        quantity=quantity,
    )
    payload = json.dumps({
        "user_id": action.user_id,
        "product_id": action.product_id,
        "quantity": action.quantity,
    })
    valkey_client.setex(_pending_key(token), _TOKEN_TTL_SECONDS, payload)
    logger.info(
        "Created pending cart action token for user_id=%r product_id=%r quantity=%d",
        user_id, product_id, quantity,
    )
    return action


def confirm_cart_action(
    token: str,
    user_id: str,
    cart_stub: demo_pb2_grpc.CartServiceStub,
    valkey_client: valkeylib.Valkey,
) -> tuple[bool, str]:
    """Validate a pending token and, if valid, write to cart exactly once.

    Enforces:
      - Token must exist (not expired).
      - Token's user_id must match the caller's user_id (no cross-user replay).
      - Token is deleted immediately after reading (prevents replay).

    Returns:
        (True, "") on success.
        (False, reason_string) on any failure.
    """
    key = _pending_key(token)

    # Atomic get-and-delete to prevent replay even under concurrent calls.
    payload_raw = valkey_client.getdel(key)

    if payload_raw is None:
        logger.info("Confirm cart: pending action not found or expired")
        return False, "Token expired or not found."

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        logger.error("Confirm cart: corrupt pending-action payload")
        return False, "Invalid token payload."

    stored_user_id = payload.get("user_id", "")
    product_id = payload.get("product_id", "")
    quantity = int(payload.get("quantity", 1))

    if stored_user_id != user_id:
        logger.info(
            "Confirm cart: user_id mismatch. expected=%r got=%r",
            stored_user_id, user_id,
        )
        return False, "Token does not belong to this user."

    # Execute the cart write — only possible path where CartService.AddItem is called.
    try:
        cart_stub.AddItem(demo_pb2.AddItemRequest(
            user_id=user_id,
            item=demo_pb2.CartItem(product_id=product_id, quantity=quantity),
        ))
        logger.info(
            "Cart write confirmed: user_id=%r product_id=%r quantity=%d",
            user_id, product_id, quantity,
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        logger.error("Cart write failed: %s", exc)
        return False, f"Cart service error: {exc}"


def make_cart_stub() -> demo_pb2_grpc.CartServiceStub:
    """Build a gRPC stub from the CART_ADDR env var."""
    addr = os.environ["CART_ADDR"]
    channel = grpc.insecure_channel(addr)
    return demo_pb2_grpc.CartServiceStub(channel)


# Deferred import to avoid circular issues; cart_tool is imported by
# copilot_server.py which also imports grpc for the server setup.
import grpc  # noqa: E402
# Change trail: @hungxqt - 2026-07-20 - Stop logging pending-action secrets in confirm_cart_action
