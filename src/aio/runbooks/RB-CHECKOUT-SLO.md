---
runbook_id: RB-CHECKOUT-SLO
version: "1.0"
owner: aio4-aiops
escalation: tf2-on-call
flow: checkout
detector_types:
  - official-slo
allowed_runtime_mode: dry-run
---

# Checkout official SLO breach

## Impact

Customers may be unable to complete `PlaceOrder`. Checkout success below 99.0% over the official rolling 24-hour window consumes the Phase 3 error budget.

## Preconditions and signal quality

- Confirm the event uses the qualified checkout completion SLI and rolling 24-hour window.
- Confirm the metric mapping, unit, labels, and query revision match signed SLI evidence.
- Treat missing, stale, invalid, fallback-only, low-traffic, or unverified data as unknown rather than healthy.
- Checkout latency is diagnostic only and cannot create this official breach by itself.

## Evidence to collect

- Official SLI value, threshold, request count, evaluation time, query ID, and configuration revision.
- Five-minute and fifteen-minute checkout errors, latency, and request volume.
- Likely dependency ranking with bounded Jaeger, OpenSearch, and Kubernetes links when available.
- Incident timeline, notification attempts, runtime mode, dry-run result, and verification observations.

## First response

1. Acknowledge the direct Grafana alert without waiting for AIOps correlation.
2. Confirm customer impact and whether the qualified official SLI is fresh.
3. Use the checkout dependency runbook when evidence identifies a downstream service.
4. Escalate to TF2 on-call and the owning dependency team with the incident ID and evidence links.

## Prohibited actions

- Do not disable, redirect, mutate, or bypass flagd, OpenFeature, or BTC incident delivery.
- Do not restart or delete a stateful or single-replica workload.
- Do not mutate databases, Secrets, or broad Kubernetes scope.
- Do not scale without current cost evidence, human approval, and CDO ownership.
- Do not claim recovery from missing or stale telemetry.

## Dry-run recommendation

Record an evidence-backed recommendation for the owning team. The P0 runtime must not execute a live mutation.

## Verification

Require the qualified official checkout SLI to be fresh and within objective for the configured consecutive recovery cycles. Record every verification observation and the final state.

## Rollback and escalation

P0 has no automated mutation to roll back. If verification is unavailable or the SLI remains breached, keep the incident open or escalated and hand off to TF2 on-call.

## Communication template

`[SEV1][checkout] Official checkout success SLO breached. Incident=<id>; value=<value>; window=24h; likely_dependency=<name-or-unknown>; mode=dry-run; verification=<state>.`

