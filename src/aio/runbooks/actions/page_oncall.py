from __future__ import annotations

from datetime import UTC, datetime


def run(context: dict) -> dict:
    executed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target = context.get("target") or "platform-team"
    action_id = context.get("action_id") or "page_oncall"
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
        "verification": {"defined": False, "passed": None, "owner": "aiops-runtime"},
        "rollback": {"defined": False},
    }

