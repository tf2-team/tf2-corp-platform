---
runbook_id: RB-DB-SATURATION
version: "1.0"
title: PostgreSQL backend saturation
severity: P0
owner: aio4-aiops
escalation: tf2-on-call
flows:
  - database-pressure
services:
  - postgresql
detector_types:
  - saturation
signal_refs:
  - postgresql_backend_usage_ratio_5m
  - postgresql_active_backends_5m
allowed_runtime_mode: dry-run
evidence_required:
  - active backend count and maximum connection source
  - pressure ratio and threshold
  - affected service errors or latency
  - database owner and configuration revision
prohibited_actions:
  - restart PostgreSQL or stateful database pods
  - change database configuration, schema, users, credentials, or data
  - delete pods, Secrets, volumes, or persistent claims
verification:
  signal_refs:
    - postgresql_backend_usage_ratio_5m
    - postgresql_active_backends_5m
  consecutive_cycles: 2
communication_template: "[database pressure] Incident=<id>; backends=<active>/<maximum>; ratio=<value>; affected_flows=<flows>; mode=dry-run; verification=<state>."
---

# PostgreSQL backend saturation

## Impact

High active-backend usage or connection pressure may degrade browse, cart, checkout, or supporting services.

## Preconditions and signal quality

- Use the deployed PostgreSQL `max_connections` value and the signed DB threshold ADR.
- Confirm active backend data is fresh, correctly scoped, and measured in connections.
- Treat unavailable client-pool metrics as unavailable rather than zero.
- Require supporting trend or service symptoms according to detector configuration.

## Evidence to collect

- Active backends, discovered maximum, pressure ratio, threshold, trend, and time bounds.
- Deadlocks, connection waits, client-pool metrics when present, and affected service errors/latency.
- Bounded trace/log evidence, database owner, configuration revision, and incident timeline.

## First response

1. Confirm whether customer flows are affected and identify database clients.
2. Notify TF2 on-call, the database owner, and affected application owners.
3. Inspect connection leaks, query pressure, pool behavior, and traffic changes using read-only evidence.
4. Let CDO/application owners decide any pool, capacity, or managed-service change.

## Prohibited actions

- Never restart PostgreSQL or a stateful database pod automatically.
- Never change database configuration, schema, users, credentials, or data.
- Never delete pods, Secrets, volumes, or persistent claims.
- Never scale without current cost evidence, human approval, and CDO ownership.

## Dry-run recommendation

Record investigation or load-containment recommendations with evidence, owner, safety results, and verification criteria. P0 performs no database mutation.

## Verification

Require fresh backend pressure and affected-service signals to remain within recovery bounds for configured consecutive cycles. Missing database telemetry is inconclusive.

## Rollback and escalation

P0 has no automated database action. Escalate persistent or unverifiable pressure to the database owner and CDO; record any human action and its rollback separately.

## Communication template

`[database pressure] Incident=<id>; backends=<active>/<maximum>; ratio=<value>; affected_flows=<flows>; mode=dry-run; verification=<state>.`

