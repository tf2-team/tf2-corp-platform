#!/usr/bin/python
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
        "before": plan["before"],
        "after": plan["after"],
        "blast_radius_services": plan["blast_radius_services"],
    }
    response["rollback_token"] = plan["rollback_token"]
    response["rollback"]["target_replicas"] = plan["before"].get("replicas")
    return response

