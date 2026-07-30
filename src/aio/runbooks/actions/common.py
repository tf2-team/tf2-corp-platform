# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

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
    "scale_frontend_proxy": {
        "action_id": "scale_frontend_proxy",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "frontend-proxy",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 1,
        "max_replicas": 3,
        "target_replicas": 3,
        "owner": "platform-edge-owner",
        "blast_radius_services": ["frontend", "checkout", "product-catalog", "cart"],
        "verification_query_id": "frontend-proxy.p95_latency_5m",
        "verification_signal_id": "frontend_proxy_p95_latency_5m",
        "verification_threshold": 1.5,
    },
    "scale_frontend": {
        "action_id": "scale_frontend",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "frontend",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 1,
        "max_replicas": 3,
        "target_replicas": 3,
        "owner": "frontend-owner",
        "blast_radius_services": ["frontend-proxy", "checkout", "product-catalog", "cart"],
        "verification_query_id": "frontend.p95_latency_5m",
        "verification_signal_id": "frontend_p95_latency_5m",
        "verification_threshold": 1.0,
    },
    "scale_checkout": {
        "action_id": "scale_checkout",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "checkout",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 1,
        "max_replicas": 3,
        "target_replicas": 3,
        "owner": "checkout-owner",
        "blast_radius_services": ["frontend", "frontend-proxy", "cart", "payment", "shipping", "email"],
        "verification_query_id": "checkout.p95_latency_5m",
        "verification_signal_id": "checkout_p95_latency_5m",
        "verification_threshold": 2.0,
    },
    "scale_cart": {
        "action_id": "scale_cart",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "cart",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 1,
        "max_replicas": 3,
        "target_replicas": 3,
        "owner": "cart-owner",
        "blast_radius_services": ["checkout", "frontend"],
        "verification_query_id": "cart.error_rate_5m",
        "verification_signal_id": "cart_error_rate_5m",
        "verification_threshold": 0.005,
    },
    "scale_product_catalog": {
        "action_id": "scale_product_catalog",
        "action_type": "scale_deployment",
        "rollback_action_type": "restore_deployment_replicas",
        "rollback_action_id": "restore_deployment_replicas",
        "target": "product-catalog",
        "target_kind": "Deployment",
        "namespace": "techx-corp-prod",
        "min_replicas": 2,
        "max_replicas": 12,
        "target_replicas": 3,
        "owner": "product-catalog-owner",
        "blast_radius_services": ["frontend", "recommendation", "product-reviews", "checkout"],
        "verification_query_id": "product-catalog.cpu_millicores",
        "verification_signal_id": "product_catalog_cpu_millicores",
        "verification_max_ratio": 0.9,
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
        "scaling_controller": "Deployment",
        "control_replicas": config["min_replicas"],
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
        execution = context.get("execution")
        if isinstance(execution, dict):
            action_id = execution.get("action_id") or context.get("original_action_id")
        else:
            action_id = context.get("original_action_id")
        if not action_id:
            target = context.get("target")
            for candidate in ALLOWLIST.values():
                if candidate.get("target") == target:
                    action_id = candidate["action_id"]
                    break
        action_id = action_id or "scale_product_catalog"
    config = copy.deepcopy(ALLOWLIST.get(action_id))
    if config is not None:
        executor_environment = context.get("_executor_environment")
        if isinstance(executor_environment, str) and executor_environment:
            config["namespace"] = executor_environment
    return config


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
    if isinstance(requested_target, str) and requested_target.lower() in PROTECTED_TARGETS:
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
    expected_policy_id = str(context.get("_executor_policy_id") or POLICY_ID)
    expected_policy_expiry_text = str(context.get("_executor_policy_expires_at") or POLICY_EXPIRES_AT)
    expected_approval_id = context.get("_executor_approval_id")
    if context.get("policy_id") != expected_policy_id:
        reasons.append("policy_id_mismatch")
    if context.get("policy_approved") is not True:
        reasons.append("policy_not_approved")
    approval_id = context.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        reasons.append("missing_approval")
    elif isinstance(expected_approval_id, str) and expected_approval_id and approval_id != expected_approval_id:
        reasons.append("approval_id_mismatch")

    try:
        configured_policy_expiry = parse_time(expected_policy_expiry_text)
        policy_expiry = parse_time(context.get("policy_expires_at"), configured_policy_expiry)
        if configured_policy_expiry <= utc_now() or policy_expiry <= utc_now():
            reasons.append("policy_expired")
        if policy_expiry > configured_policy_expiry:
            reasons.append("policy_expiry_exceeds_executor_policy")
    except (AttributeError, TypeError, ValueError):
        reasons.append("invalid_policy_expiry")
    if not context.get("incident_id"):
        reasons.append("missing_incident_id")
    if not context.get("reason"):
        reasons.append("missing_reason")
    if context.get("requested_by") not in (None, "aiops-runtime"):
        reasons.append("invalid_requester")

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
    autoscaler_max = int(before.get("autoscaler_max_replicas") or config["max_replicas"])
    effective_max = min(config["max_replicas"], autoscaler_max)
    target_replicas = min(max(current_replicas + 1, config["min_replicas"]), effective_max)
    after = {
        "replicas": target_replicas,
        "control_replicas": target_replicas,
        "scaling_controller": before.get("scaling_controller", "Deployment"),
    }
    requested_at = utc_now()
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
    for field in (
        "incident_id",
        "action_id",
        "action_type",
        "target",
        "target_kind",
        "namespace",
        "policy_id",
        "policy_approved",
        "policy_expires_at",
        "approval_id",
        "requested_by",
    ):
        if context.get(field) != plan.get(field):
            return plan, [f"{field}_mismatch"]
    try:
        expires_at = parse_time(plan.get("expires_at"))
    except (AttributeError, TypeError, ValueError):
        return plan, ["invalid_plan_expiry"]
    if expires_at <= utc_now():
        return plan, ["plan_expired"]
    current = get_snapshot(context, config)
    before = plan.get("before") or {}
    if current.get("scaling_controller") != before.get("scaling_controller"):
        return plan, ["scaling_controller_changed"]
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
        "verification": {
            "defined": True,
            "passed": None,
            "owner": "aiops-runtime",
            "query_id": config.get("verification_query_id"),
            "signal_id": config.get("verification_signal_id"),
            "threshold": config.get("verification_threshold"),
            "max_ratio": config.get("verification_max_ratio"),
        },
        "rollback": {"defined": True, "action_type": "restore_deployment_replicas"},
    }
