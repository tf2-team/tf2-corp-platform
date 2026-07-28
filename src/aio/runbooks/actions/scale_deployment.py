from __future__ import annotations

from datetime import UTC, datetime

from .common import base_success, block_response, stable_hash, validate_common, verify_plan_context


def run(context: dict) -> dict:
    config, reasons = validate_common(context, expected_action_type="scale_deployment")
    if config is None or reasons:
        return block_response(context, "scale deployment blocked", reasons, config)
    if context.get("dry_run") is True:
        return block_response(context, "execute requires dry_run=false", ["execute_requires_dry_run_false"], config)
    if context.get("live_apply") is True:
        return block_response(context, "live apply is not enabled for Phase 2 action scripts", ["live_apply_disabled_phase2"], config)

    plan, plan_reasons = verify_plan_context(context, config)
    if plan_reasons:
        return block_response(context, "scale deployment plan validation failed", plan_reasons, config)

    before = dict(plan.get("before") or {})
    after = dict(plan.get("after") or {})
    executed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    execution_seed = {
        "incident_id": context.get("incident_id"),
        "action_id": config["action_id"],
        "plan_hash": context.get("plan_hash"),
        "idempotency_key": context.get("idempotency_key"),
    }
    execution_id = "exec-" + stable_hash(execution_seed).split(":", 1)[1][:16]

    response = base_success(
        context,
        config,
        executed=True,
        message=f"scaled deployment/{config['target']} from {before.get('replicas')} to {after.get('replicas')} replicas",
    )
    response.update(
        {
            "execution_id": execution_id,
            "executed_at": executed_at,
            "before": before,
            "after": after,
            "rollback_token": context.get("rollback_token"),
        }
    )
    response["verification"]["fresh_after"] = executed_at
    response["rollback"]["target_replicas"] = before.get("replicas")
    return response

