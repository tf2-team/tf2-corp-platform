---
runbookId: RB-DATASTORE-POSTGRESQL
owner: data-platform-oncall
---

# PostgreSQL Datastore Issue

## Scope

Use this runbook when AIOps links an incident to `postgresql`, database pool saturation, slow queries, connection errors, or dependent services such as `checkout`, `product-catalog`, `product-reviews`, or `accounting`.

## First checks

- Confirm which service is failing and whether PostgreSQL is the root cause or only a downstream symptom.
- Check connection pool usage, active connections, slow queries, lock waits, and recent migrations.
- Check caller error rates and latency for checkout/catalog/reviews/accounting.
- Check RDS or managed database health if the database is external.

## Do not do

- Do not restart, scale, or mutate PostgreSQL from AIOps.
- Do not kill sessions or change pool sizes without data-platform approval.
- Do not treat database telemetry gaps as recovery.

## Safe actions

- Page `data-platform-oncall` with affected services, query/log samples, connection metrics, and incident id.
- Reduce caller load only through approved feature flags or traffic controls.
- Keep remediation as page-only unless a reviewed database runbook explicitly approves an action.

## Escalation

Escalate to data platform and service owner of the highest-impact caller.

