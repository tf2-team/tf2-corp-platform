#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import UTC, datetime

from .common import base_success, block_response, stable_hash, validate_common


def run(context: dict) -> dict:
    config, reasons = validate_common(context, expected_action_type="restore_deployment_replicas", allow_restore=True)
    if config is None or reasons:
        return block_response(context, "restore deployment replicas blocked", reasons, config)
    if context.get("dry_run") is True:
        return block_response(context, "rollback requires dry_run=false", ["rollback_requires_dry_run_false"], config)
    if context.get("live_apply") is True:
        return block_response(context, "live apply is not enabled for Phase 2 action scripts", ["live_apply_disabled_phase2"], config)

    execution = context.get("execution")
    if not isinstance(execution, dict):
        return block_response(context, "rollback requires execution snapshot", ["missing_execution"], config)
    if context.get("rollback_token") != execution.get("rollback_token"):
        return block_response(context, "rollback token mismatch", ["rollback_token_mismatch"], config)

    execution_before = execution.get("before") or {}
    execution_after = execution.get("after") or {}
    current = context.get("kubernetes_snapshot") or execution_after
    before = {
        "replicas": current.get("replicas"),
        "resource_version": current.get("resource_version", execution_after.get("resource_version")),
    }
    after = {
        "replicas": execution_before.get("replicas"),
        "resource_version": context.get("restored_resource_version", "phase2-restored-resource-version"),
    }
    executed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rollback_seed = {
        "execution_id": execution.get("execution_id"),
        "rollback_token": context.get("rollback_token"),
        "idempotency_key": context.get("idempotency_key"),
    }
    rollback_id = "rb-" + stable_hash(rollback_seed).split(":", 1)[1][:16]

    response = base_success(
        context,
        config,
        executed=True,
        message=f"restored deployment/{config['target']} replicas from {before.get('replicas')} to {after.get('replicas')}",
    )
    response.update(
        {
            "rollback_id": rollback_id,
            "execution_id": execution.get("execution_id"),
            "executed_at": executed_at,
            "before": before,
            "after": after,
        }
    )
    response["rollback"]["target_replicas"] = after.get("replicas")
    return response

