# Change: Cap product-catalog DB pool and recommendation gRPC workers

## Summary

Limited **product-catalog** PostgreSQL pool size and increased **recommendation** gRPC worker pool so multi-replica catalog HPA does not exhaust Postgres connections, and recommendation health probes can complete under load (clearing HPA `cpu: <unknown>` when pods were NotReady).

## Context

Under Locust load after raising product-catalog `maxReplicas` to 12:

* Postgres `max_connections=100` with ~70+ sessions (`otelu` idle heavy).
* Catalog errors: `pq: remaining connection slots are reserved for roles with the SUPERUSER attribute` / connection reset.
* Recommendation called `ListProducts` on a saturated catalog, filled a 10-thread gRPC pool, and readiness/liveness health RPCs timed out → NotReady → HPA CPU `<unknown>`.
* Chart change raises Postgres slots/resources and recommendation probe timeouts (separate repo).

## Before

* `product-catalog` `sql.DB`: no `SetMaxOpenConns` / idle / lifetime (unlimited open).
* `recommendation` gRPC server: fixed `max_workers=10` shared by business RPC and health.

## After

* **product-catalog** after `otelsql.Open`:
  * `SetMaxOpenConns(5)`
  * `SetMaxIdleConns(2)`
  * `SetConnMaxLifetime(5m)`
  * `SetConnMaxIdleTime(1m)`
* **recommendation**: `ThreadPoolExecutor(max_workers=int(os.environ.get("GRPC_MAX_WORKERS", "20")))`.

Math: 12 catalog pods × 5 open ≈ 60 app connections, under Postgres 200 (chart) or 100 with headroom for other services when pool is capped.

## Technical Design Decisions

* **Cap at app layer** — more reliable than only raising `max_connections`; idle pools were the main consumer.
* **5 open per pod** — enough for concurrent List/Get/Search under one process without multiplying idle sockets.
* **Env-tunable workers** — chart can set `GRPC_MAX_WORKERS` without rebuild for fine-tuning; default 20 doubles prior capacity.
* Rejected: in-process product cache only (larger product change); separate health server process (heavier).

## Implementation Details

1. Pool caps in `src/product-catalog/main.go` `initDatabase`.
2. Worker env default in `src/recommendation/recommendation_server.py`.
3. Change trails on both source files.

## Files Changed

* `src/product-catalog/main.go` — sql.DB pool limits.
* `src/recommendation/recommendation_server.py` — `GRPC_MAX_WORKERS` default 20.
* `docs/changes/2026-07-14-fix-recommendation-catalog-db-pressure.md` — this record.

## Dependencies and Cross-Repository Impact

* Related chart: `techx-corp-chart/docs/changes/2026-07-14-fix-recommendation-hpa-unknown-cpu.md` (postgres 200 connections, recommendation probes/resources, chart `GRPC_MAX_WORKERS=20` env).
* Requires image rebuild/push for `product-catalog` and `recommendation`, then chart values tag promote (dev auto / prod PR per CICD).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Catalog waits if pool busy instead of opening unbounded connections; recommendation health less likely to starve |
| **Infrastructure** | Lower Postgres session count under scale-out |
| **Deployment** | New images for two services |
| **Performance** | Possible slight queue on catalog under extreme concurrency per pod (pool 5) |
| **Reliability** | Fewer connection-slot errors and probe-driven restarts |
| **Backward compatibility** | Compatible; workers overridable via env |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Catalog unit tests | `cd src\product-catalog && go test ./...` | Run in CI / local if module available |
| Values inspect | pool lines present in main.go; workers env in recommendation_server.py | ✅ |

### Manual Verification

After images deploy:

```cmd
kubectl -n techx-corp-prod get pods -l app.kubernetes.io/component=recommendation
kubectl -n techx-corp-prod get hpa recommendation
kubectl -n techx-corp-prod exec postgresql-0 -- psql -U root -d otel -c "SELECT usename, count(*) FROM pg_stat_activity GROUP BY 1;"
```

Expect Ready pods, numeric CPU on HPA, bounded `otelu` connection count under load.

### Remaining Verification (Post-Merge)

* CI unit tests for product-catalog.
* Load test: no SUPERUSER slot errors; recommendation stays Ready.

## Migration or Deployment Notes

1. Build and push `product-catalog` and `recommendation` images (platform CI bake/promote).
2. Sync chart `0.48.0+` for postgres capacity and probe/env wiring.
3. No schema migration.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Catalog pool too small under single-pod extreme load | Low | Medium | Raise SetMaxOpenConns or maxReplicas carefully |
| More recommendation threads → more memory | Low | Low | Limits raised in chart; watch RSS |

**Rollback procedure:**

Revert the two source files and redeploy previous images.

<!-- Change trail: @hungxqt - 2026-07-14 - Catalog DB pool cap + recommendation gRPC workers. -->
