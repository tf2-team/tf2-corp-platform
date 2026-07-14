---
runbook_id: RB-MONITORING-LOSS
version: "1.0"
owner: aio4-aiops
escalation: tf2-on-call
flow: monitoring
detector_types:
  - no-data
allowed_runtime_mode: dry-run
---

# Monitoring signal loss

## Impact

A required collector, query, series, or runtime signal is missing, stale, invalid, or unavailable. Dependent health and recovery conclusions are unknown.

## Preconditions and signal quality

- Distinguish expected zero traffic from an absent series or failed query.
- Compare the last sample time with the configured freshness limit and scrape/evaluation cadence.
- Group signals only when evidence supports a shared monitoring-source failure.

## Evidence to collect

- Missing signal IDs, source adapter, collection status, last successful sample, and gap duration.
- Prometheus/Grafana availability and AIOps scheduler/collector self-metrics.
- Query/config revision, error class, retry attempts, and affected detector list.
- Independent direct Grafana runtime-loss alert state.

## First response

1. Confirm the gap independently from the AIOps runtime when possible.
2. Identify whether the failure is collection, transport, source, parsing, validation, or freshness.
3. Preserve direct official SLO alert routes while restoring telemetry.
4. Notify TF2 on-call when official health or verification is obscured.

## Prohibited actions

- Never replace missing, stale, invalid, fallback-only, or unverified values with zero or healthy.
- Never resolve another incident using unavailable verification data.
- Do not restart stateful/single-replica telemetry components automatically.
- Do not disable direct Grafana routes to hide duplicate alerts.

## Dry-run recommendation

Recommend bounded diagnostic steps and the responsible monitoring owner. Do not mutate monitoring or application infrastructure automatically.

## Verification

Require each affected required signal to be fresh, valid, and qualified for configured consecutive cycles. Record total gap duration and dependent detector recovery.

## Rollback and escalation

If telemetry remains unavailable, keep dependent incidents open or escalated. Human infrastructure changes must have their own rollback and evidence.

## Communication template

`[monitoring loss] Incident=<id>; source=<adapter>; missing_signals=<ids>; gap=<duration>; affected_detectors=<ids>; verification=inconclusive.`

