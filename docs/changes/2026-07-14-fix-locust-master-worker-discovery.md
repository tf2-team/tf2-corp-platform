# Change: Fix Locust Master Losing Workers (Stale Worker KeyError)

## Summary

Hardened the load-generator Locust process so distributed master mode no longer loses all workers after HPA/Spot worker churn. A `KeyError` on late messages from disconnected workers was killing `MasterRunner.client_listener`, after which the UI showed `worker_count: 0` until the master pod was restarted.

## Context

After migrating to Locust master/worker (`load-generator` + `load-generator-worker`), operators saw the Locust UI report zero workers while worker pods were `Running` and TCP connectivity to `load-generator:5557` succeeded.

Root cause on the live master:

* Master log: `KeyError` in `MasterRunner.handle_message` for a **stale** worker `node_id` (scaled-away pod).
* Greenlet failure: `MasterRunner.client_listener ... failed with KeyError`.
* After that crash, the master process stayed up (web UI healthy) but stopped processing worker join/heartbeat messages.
* Restarting the master immediately restored `worker_count` to match ready workers.

This is triggered by normal worker lifecycle events (HPA scale-down, Spot interrupt, pod restart), so restart-only recovery is not durable.

## Before

* `locustfile.py` loaded user classes only; no defense against Locust master handling messages for unknown workers.
* Master `client_listener` greenlet died on first `KeyError` from a stale worker.
* UI: `worker_count: 0` with workers still connected at the TCP layer until master restart.

## After

* `locustfile.py` installs a one-time patch on `MasterRunner.handle_message` that catches `KeyError`, logs a warning, and returns so `client_listener` keeps running.
* Existing workers continue to register/heartbeat after other workers disappear.
* Image rebuild/redeploy of `load-generator` (master and workers share the same image) is required for the fix to take effect in cluster.

## Technical Design Decisions

* **In-process monkeypatch vs Locust upgrade** — Patch is small, version-tolerant, and ships with the app image. Upgrading Locust alone is not guaranteed to cover this race in every 2.x line and would drag `locust-plugins` compatibility risk.
* **Catch only `KeyError`** — Preserves real bugs for other exception types; matches the observed failure mode.
* **Apply on every process (master and worker)** — Guard is no-op-safe on workers (`MasterRunner` class patch only matters when master runs).
* **Keep `--skip-log-setup`** — OTEL `LoggingInstrumentor` remains the log setup; the guard uses stdlib `logging.warning`.

Chart-side hardening (expect-workers, bind flags, NP, HPA scale-down) lives in `techx-corp-chart` — see related change doc.

## Implementation Details

1. Import-time helper `_install_master_stale_worker_guard()` wraps `MasterRunner.handle_message`.
2. Idempotent flag `_techx_stale_worker_guard` avoids double-wrapping on reload.
3. On `KeyError`, log `node_id` and message type, return `None`.

## Files Changed

* `src/load-generator/locustfile.py` — Stale-worker `KeyError` guard for distributed master.
* `docs/changes/2026-07-14-fix-locust-master-worker-discovery.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-14-fix-locust-master-worker-discovery.md` (expect-workers, bind ports, NetworkPolicy, worker HPA scale-down, probes).
* Deploy order: build/push new `load-generator` image → update chart image tag → restart master (and workers pick up same tag). Chart-only deploy does **not** include this process fix.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Master no longer permanently drops the worker pool after one stale worker message |
| **Infrastructure** | No change |
| **Deployment** | Requires new load-generator image tag promote |
| **Performance** | Negligible (exception path only) |
| **Security** | No change |
| **Reliability** | Locust distributed mode survives worker churn without master restart |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible (standalone and distributed) |
| **Observability** | Warning log when a stale worker message is ignored |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Python syntax | `python -m py_compile src/load-generator/locustfile.py` | Run locally if Python available |
| Unit tests | N/A (no load-generator unit tests) | N/A |

### Manual Verification

* Pre-fix cluster: master `worker_count: 0` with 3 Running workers; master log showed `KeyError` / `client_listener` failed; TCP `load-generator:5557` from worker succeeded.
* Master restart alone restored `workers=3` (confirms process-state failure, not DNS/Service).
* Post-image deploy: scale workers up/down and confirm master `worker_count` tracks Ready pods without master restart; optional log line for ignored stale node ids.

### Remaining Verification (Post-Merge)

1. Bake/push `load-generator` image including this `locustfile.py`.
2. Promote tag via chart values (dev auto / prod PR).
3. Roll master + workers; confirm Locust UI workers match HPA Ready count under scale events.

## Migration or Deployment Notes

```cmd
cd /d techx-corp-platform
REM build/push per platform CI or local bake for load-generator target
```

1. Ship platform image first (this change).
2. Apply chart hardening from the related chart change doc (can ship same window).
3. `kubectl rollout restart deployment/load-generator deployment/load-generator-worker -n <ns>` after tag update if needed.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Patch masks a different KeyError that should surface | Low | Low | Log warning includes node_id/type; only KeyError swallowed |
| Locust renames `handle_message` API | Low | Medium | Guard ImportError/attribute miss is soft-fail; re-test on Locust bumps |

**Rollback procedure:**

Revert `src/load-generator/locustfile.py` and redeploy previous image tag. Temporary recovery without image: restart master Deployment.

<!-- Change trail: @hungxqt - 2026-07-14 - Locust master stale-worker KeyError guard in load-generator image. -->
