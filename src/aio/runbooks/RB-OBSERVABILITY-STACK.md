---
runbookId: RB-OBSERVABILITY-STACK
owner: platform-oncall
---

# Observability Stack Issue

## Scope

Use this runbook when Prometheus, Jaeger, OpenSearch, Grafana, or OTel collector telemetry is degraded or unavailable.

## First checks

- Check Prometheus targets, scrape freshness, query latency, and storage health.
- Check OTel collector queue, exporter errors, and receiver status.
- Check Jaeger and OpenSearch ingestion/search availability.
- Check Grafana health and whether alert/webhook delivery is affected.
- Compare missing telemetry with service logs before declaring service recovery.

## Do not do

- Do not auto-remediate observability stateful components from AIOps.
- Do not mark incidents recovered when telemetry is stale or missing.
- Do not delete indexes, traces, or metric data as a first response.

## Safe actions

- Page `platform-oncall`.
- Use port-forward or internal service checks to isolate which telemetry backend is failing.
- Switch AIOps to conservative/page-only handling if telemetry freshness cannot be trusted.

## Escalation

Escalate with affected telemetry type, query examples, target status, and first failing timestamp.

