# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from .common import base_success, block_response, make_plan, validate_common


def run(context: dict) -> dict:
    config, reasons = validate_common(context, expected_action_type="scale_deployment")
    if config is None or reasons:
        return block_response(context, "scale deployment plan blocked", reasons, config)
    if context.get("dry_run") is not True:
        return block_response(context, "plan requires dry_run=true", ["dry_run_required"], config)

    plan = make_plan(context, config)
    if int(plan["after"]["replicas"]) <= int(plan["before"]["replicas"]):
        return block_response(
            context,
            "scale deployment plan blocked",
            ["scale_capacity_exhausted"],
            config,
        )
    response = base_success(
        context,
        config,
        executed=False,
        message=(
            f"dry-run scale deployment/{config['target']} "
            f"from {plan['before'].get('replicas')} to {plan['after'].get('replicas')} replicas"
        ),
    )
    response["plan"] = {
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "expires_at": plan["expires_at"],
        "incident_id": context.get("incident_id"),
        "action_id": config["action_id"],
        "action_type": config["action_type"],
        "target": config["target"],
        "target_kind": config["target_kind"],
        "namespace": config["namespace"],
        "policy_id": context.get("policy_id"),
        "policy_approved": context.get("policy_approved"),
        "policy_expires_at": context.get("policy_expires_at"),
        "approval_id": context.get("approval_id"),
        "requested_by": context.get("requested_by"),
        "before": plan["before"],
        "after": plan["after"],
        "blast_radius_services": plan["blast_radius_services"],
    }
    response["rollback_token"] = plan["rollback_token"]
    response["rollback"]["target_replicas"] = plan["before"].get("replicas")
    return response

