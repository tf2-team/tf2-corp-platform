---
runbookId: RB-SERVICE-ERROR-RATE
owner: platform-oncall
---

# Service Error Rate

Trigger: a confirmed adaptive error/latency/readiness/memory finding for a service without a more specific runbook.

1. Confirm service, metric, two-sample confirmation, current value, baseline, and signal quality from the incident payload.
2. Re-run the incident query and confirm that its denominator/source series exists.
3. Inspect correlated traces and bounded logs, then check readiness, restarts, rollout, and direct dependencies.
4. Assign the likely dependency only when topology and telemetry agree; otherwise retain `unknown`.
5. Escalate with query, time window, trace/log link, affected flow, and owner from topology config.

Verify recovery: no matching adaptive finding for two fresh cycles while the underlying metric remains available. Missing/stale data is not recovery.

Prohibited: disabling incident flags, fabricating a root cause, or restarting a service without evidence and approval.
