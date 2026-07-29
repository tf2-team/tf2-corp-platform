# Self-heal end-to-end runtime

## Implemented control loop

The runtime now uses the versioned executor API for the Phase 3 golden action:

```text
detector
  -> remediation history decision
  -> local policy approval
  -> executor plan (dry-run and before snapshot)
  -> executor execute (resourceVersion guarded)
  -> persistent fresh-telemetry verification
  -> succeeded and incident recovered
     OR verification failed/inconclusive timeout
        -> executor rollback
        -> rollback snapshot verification
```

The runtime never receives Kubernetes write credentials. Only the executor
service owns its namespace-scoped deployment client.

## Safety gates

Live behavior is disabled by default on both sides.

Runtime gates:

- `AIOPS_SELF_HEAL_ENABLED=true`
- `AIOPS_POLICY_MODE=live-approved`
- a non-placeholder `AIOPS_LIVE_EXECUTOR_URL`
- a signed/approved `AIOPS_SELF_HEAL_APPROVAL_ID`
- catalog action approval, protected-target policy, verification, and rollback

Executor gates:

- `AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY=true`
- a configured `AIOPS_LIVE_EXECUTOR_TOKEN`
- the `scale_product_catalog` allowlist
- policy id and policy expiry
- dry-run plan and plan expiry
- Kubernetes `resourceVersion` optimistic concurrency
- target single-flight, persistent idempotency, and cooldown
- rollback token tied to the execution snapshot
- namespace-scoped Kubernetes RBAC

Do not enable either live gate until the platform owner approves the target
namespace, policy expiry, token Secret, PVC, RBAC, and NetworkPolicy.

## Verification ownership and rule

The AIOps runtime owns post-action verification. It accepts only samples whose
`sample_timestamp` is later than the executor's `executed_at`.

For the golden CPU-saturation action, the verification signal is
`product_catalog_cpu_millicores`, measured as average CPU millicores per
matching workload pod rather than aggregate service CPU. By default, recovery
requires two fresh, consecutive samples at or below the incident threshold and
the executor independently requires the requested ready-pod count. Two
consecutive failed samples, or no conclusive telemetry before the deadline,
triggers rollback.

The thresholds are configurable through:

- `AIOPS_SELF_HEAL_VERIFICATION_DEADLINE_SECONDS`
- `AIOPS_SELF_HEAL_MIN_FRESH_SAMPLES`
- `AIOPS_SELF_HEAL_CONSECUTIVE_PASSES`
- `AIOPS_SELF_HEAL_FAILURE_SAMPLES`

## Persistence and audit

The runtime SQLite store persists `self_heal_workflows` and append-only
`self_heal_audit_events`. The executor SQLite store persists plans, executions,
idempotency keys, target cooldowns, and append-only executor audit events.

The combined audit chain is:

```text
incident -> plan -> execute -> verification samples
         -> verification passed
         OR verification failed -> rollback -> escalation if rollback fails
```

An incident is persisted as `recovered` only after the executor accepts a
passing fresh-telemetry result.

## Non-cluster validation

The test suite uses a fake Kubernetes deployment gateway. It covers:

- plan -> live execute -> status -> verification -> rollback;
- explicit live-apply and authentication gates;
- protected/stale/idempotent behavior from the CDO handoff;
- detector-driven action selection and execution;
- two-sample fresh-telemetry success;
- repeated verification failure rollback;
- missing telemetry timeout rollback;
- append-only runtime and executor audit trails.

These tests prove the control logic without granting cluster mutation. A
dev/demo cluster smoke with live approval is still required before deployment.
