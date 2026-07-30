#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime

from .common import AUTHORIZED_REQUESTER


def run(context: dict) -> dict:
    executed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target = context.get("target")
    action_id = context.get("action_id")
    if not isinstance(target, str) or not target or not isinstance(action_id, str) or not action_id:
        raise ValueError("page action requires configured action_id and target")
    message = f"page-only notification recorded for {target}"
    if context.get("dry_run") is True:
        message = f"dry-run page-only notification for {target}"

    return {
        "ok": True,
        "executed": False,
        "action_id": action_id,
        "action_type": "page",
        "target": target,
        "target_kind": "OnCall",
        "namespace": context.get("namespace"),
        "message": message,
        "executed_at": executed_at,
        "audit_only": True,
        "verification": {"defined": False, "passed": None, "owner": AUTHORIZED_REQUESTER},
        "rollback": {"defined": False},
    }

