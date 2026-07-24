#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Normalize Shopping Copilot state for eval graders."""


def normalize_copilot_output(state: dict, cart_stub) -> dict:
    """Extract the stable fields used by deterministic Copilot graders."""
    pending = state.get("pending_action")
    return {
        "status": getattr(state.get("status"), "value", state.get("status")),
        "pending_action": (
            {
                "token": pending.token,
                "product_id": pending.product_id,
                "quantity": pending.quantity,
            }
            if pending
            else None
        ),
        "tool_calls": state.get("tool_calls", []),
        "cart_add_item_called": bool(getattr(cart_stub.AddItem, "called", False)),
    }
