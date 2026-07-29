---
runbookId: RB-AIOPS-RUNTIME
owner: platform-oncall
---

# AIOps Runtime Health

## Scope

Use this runbook when `aiops-runtime` is unhealthy, not collecting telemetry, not writing state, or not dispatching notifications.

## First checks

- Check `/health/live`, `/health/ready`, and `/metrics` on the AIOps runtime.
- Check pod status, restarts, image tag, config map, secret refs, and PVC mount.
- Check SQLite/WAL state directory is writable and has free space.
- Check Prometheus, Jaeger, OpenSearch, Kubernetes proxy/client, and notification webhook configuration.
- Check `AIOPS_POLICY_MODE`, `AIOPS_SELF_HEAL_ENABLED`, and executor URL before any self-heal test.

## Do not do

- Do not delete SQLite state or PVC to fix readiness.
- Do not enable live-approved mode while runtime dependencies are failing.
- Do not give AIOps runtime Kubernetes write permission; mutation must go through the live executor.

## Safe actions

- Restart the runtime only after confirming state volume is intact.
- Disable auto-run temporarily if collector failures are causing repeated crashes.
- Fall back to dry-run and manual on-call handling if executor or verification dependencies are unavailable.

## Escalation

Escalate to `platform-oncall`; include runtime logs, readiness reason, current config env, and state path.

