from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

SCHEMA_VERSION = "1.0"
POLICY_ID = "phase3-scale-policy-v1"
POLICY_EXPIRES_AT = "2026-08-31T23:59:59Z"
PLAN_TTL_SECONDS = 600

ALLOWLIST = {
    "scale_product_catalog": {
        "action_id": "scale_product_catalog",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "product-catalog",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 2,
        "max_replicas": 3,
        "target_replicas": 3,
        "blast_radius_services": ["frontend", "recommendation", "product-reviews", "checkout"],
        "verification_query_id": "product-catalog.p95_latency_5m",
    }
}

PROTECTED_TARGETS = {
    "postgresql",
    "kafka",
    "valkey-cart",
    "redis",
    "flagd",
    "openfeature",
    "aiops-runtime",
    "observability",
    "payment",
}

PROTECTED_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease", "linkerd", "monitoring", "observability"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str | None, default: datetime | None = None) -> datetime:
    if not value:
        return default or utc_now()
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def default_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "Deployment",
        "namespace": config["namespace"],
        "name": config["target"],
        "replicas": config["min_replicas"],
        "ready_replicas": config["min_replicas"],
        "resource_version": "phase2-mock-resource-version",
    }


def get_snapshot(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    snapshot = (
        context.get("kubernetes_snapshot")
        or context.get("current")
        or context.get("before")
        or context.get("deployment")
        or default_snapshot(config)
    )
    if not isinstance(snapshot, dict):
        return default_snapshot(config)
    merged = default_snapshot(config)
    merged.update(snapshot)
    return merged


def resolved_config(context: dict[str, Any]) -> dict[str, Any] | None:
    action_id = context.get("action_id")
    if action_id == "restore_deployment_replicas":
        action_id = context.get("original_action_id") or "scale_product_catalog"
    return copy.deepcopy(ALLOWLIST.get(action_id))


def block_response(context: dict[str, Any], message: str, reasons: list[str], config: dict[str, Any] | None = None) -> dict[str, Any]:
    target = (config or {}).get("target") or context.get("target", "unknown")
    namespace = (config or {}).get("namespace") or context.get("namespace")
    return {
        "ok": True,
        "executed": False,
        "action_id": context.get("action_id", "unknown"),
        "action_type": context.get("action_type"),
        "target": target,
        "target_kind": (config or {}).get("target_kind") or context.get("target_kind"),
        "namespace": namespace,
        "message": message,
        "reasons": reasons,
        "verification": {"defined": True, "passed": None, "owner": "aiops-runtime"},
        "rollback": {"defined": True, "action_type": "restore_deployment_replicas"},
    }


def validate_common(context: dict[str, Any], *, expected_action_type: str, allow_restore: bool = False) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    config = resolved_config(context)
    if config is None:
        reasons.append("action_not_allowlisted")
        return None, reasons

    if context.get("schema_version") not in (None, SCHEMA_VERSION):
        reasons.append("unsupported_schema_version")
    if context.get("action_type") != expected_action_type:
        reasons.append("action_type_mismatch")
    requested_target = context.get("target")
    requested_namespace = context.get("namespace")
    if requested_target in PROTECTED_TARGETS:
        reasons.append("protected_target")
    if requested_namespace in PROTECTED_NAMESPACES:
        reasons.append("protected_namespace")
    if requested_target not in (None, config["target"]):
        reasons.append("target_mismatch")
    if context.get("target_kind") not in (None, config["target_kind"]):
        reasons.append("target_kind_mismatch")
    if requested_namespace not in (None, config["namespace"]):
        reasons.append("namespace_mismatch")
    if config["target"] in PROTECTED_TARGETS:
        reasons.append("protected_target")
    if config["namespace"] in PROTECTED_NAMESPACES:
        reasons.append("protected_namespace")
    if context.get("target_kind") in {"StatefulSet", "StatefulWorkload"}:
        reasons.append("stateful_target")
    if context.get("policy_id") != POLICY_ID:
        reasons.append("policy_id_mismatch")
    if context.get("policy_approved") is not True:
        reasons.append("policy_not_approved")

    policy_expiry = parse_time(context.get("policy_expires_at"), parse_time(POLICY_EXPIRES_AT))
    if policy_expiry <= utc_now():
        reasons.append("policy_expired")

    idempotency_key = context.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.startswith("sha256:") or len(idempotency_key) < 16:
        reasons.append("invalid_idempotency_key")

    if not allow_restore and expected_action_type != config["action_type"]:
        reasons.append("allowlist_action_type_mismatch")

    return config, reasons


def plan_payload(context: dict[str, Any], config: dict[str, Any], before: dict[str, Any], after: dict[str, Any], expires_at: str) -> dict[str, Any]:
    return {
        "action_id": config["action_id"],
        "action_type": config["action_type"],
        "target": config["target"],
        "target_kind": config["target_kind"],
        "namespace": config["namespace"],
        "incident_id": context.get("incident_id"),
        "before": {
            "replicas": before.get("replicas"),
            "resource_version": before.get("resource_version"),
        },
        "after": after,
        "expires_at": expires_at,
    }


def make_plan(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    before = get_snapshot(context, config)
    current_replicas = int(before.get("replicas", config["min_replicas"]))
    target_replicas = min(max(current_replicas + 1, config["min_replicas"]), config["max_replicas"])
    target_replicas = min(target_replicas, config["target_replicas"])
    after = {"replicas": target_replicas}
    requested_at = parse_time(context.get("requested_at"))
    expires_at = isoformat(requested_at + timedelta(seconds=PLAN_TTL_SECONDS))
    payload = plan_payload(context, config, before, after, expires_at)
    plan_hash = stable_hash(payload)
    rollback_payload = {
        "incident_id": context.get("incident_id"),
        "action_id": config["action_id"],
        "target": config["target"],
        "namespace": config["namespace"],
        "resource_version": before.get("resource_version"),
        "target_replicas": before.get("replicas"),
        "plan_hash": plan_hash,
    }
    rollback_token = "rbt:" + stable_hash(rollback_payload).split(":", 1)[1]
    return {
        "plan_id": "plan-" + plan_hash.split(":", 1)[1][:16],
        "plan_hash": plan_hash,
        "expires_at": expires_at,
        "before": before,
        "after": after,
        "blast_radius_services": config["blast_radius_services"],
        "rollback_token": rollback_token,
    }


def verify_plan_context(context: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    plan = context.get("plan")
    if not isinstance(plan, dict):
        return None, ["missing_plan"]
    expected_hash = context.get("plan_hash")
    if not expected_hash or plan.get("plan_hash") != expected_hash:
        return plan, ["plan_hash_mismatch"]
    if context.get("rollback_token") != plan.get("rollback_token"):
        return plan, ["rollback_token_mismatch"]
    expires_at = parse_time(plan.get("expires_at"))
    if expires_at <= utc_now():
        return plan, ["plan_expired"]
    current = get_snapshot(context, config)
    before = plan.get("before") or {}
    if current.get("resource_version") != before.get("resource_version"):
        return plan, ["resource_version_mismatch"]
    return plan, []


def base_success(context: dict[str, Any], config: dict[str, Any], *, executed: bool, message: str) -> dict[str, Any]:
    return {
        "ok": True,
        "executed": executed,
        "action_id": context.get("action_id", config["action_id"]),
        "action_type": context.get("action_type", config["action_type"]),
        "target": config["target"],
        "target_kind": config["target_kind"],
        "namespace": config["namespace"],
        "message": message,
        "verification": {"defined": True, "passed": None, "owner": "aiops-runtime"},
        "rollback": {"defined": True, "action_type": "restore_deployment_replicas"},
    }
