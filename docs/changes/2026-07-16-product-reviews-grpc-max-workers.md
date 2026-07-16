# Change: product-reviews configurable gRPC worker pool

## Summary

Made the product-reviews gRPC `ThreadPoolExecutor` size configurable via `GRPC_MAX_WORKERS` (default **32**, minimum 4). Health `Check` and business RPCs share this pool; under concurrent `AskProductAIAssistant` (LLM) load the previous hard-coded **10** workers caused health RPCs to queue past kubelet probe timeouts.

## Context

* Prod `product-reviews` Events: `health rpc did not complete within 5s` on readiness and liveness; kubelet restarts (exit 137) when liveness used the same gRPC health path.
* `Check` is trivial (always SERVING) but still needs a free pool worker in Python gRPC.
* Chart companion change sets `GRPC_MAX_WORKERS=32` and switches liveness to TCP so busy pods are not killed even if readiness flaps.

## Before

* `grpc.server(futures.ThreadPoolExecutor(max_workers=10))` hard-coded.
* Startup log only reported listen port.

## After

* `max_workers = int(os.environ.get('GRPC_MAX_WORKERS', '32'))`, clamped to at least **4**.
* Startup log includes `grpc_max_workers=…`.

## Technical Design Decisions

* **Default 32 (not unlimited)** — enough concurrent short RPCs + health while several multi-second LLM calls run; avoids unbounded thread growth.
* **Env override** — chart can tune without code change; local Compose can leave unset (default 32).
* **No separate health server** — higher complexity; chart TCP liveness already covers “process alive” while readiness keeps gRPC load-shed semantics.
* **Rejected:** asyncio rewrite for this incident response.

## Implementation Details

1. Read `GRPC_MAX_WORKERS` when constructing the gRPC server in `product_reviews_server.py`.
2. Log the effective worker count at listen time.
3. Documented in this change record; chart wires the env var separately.

## Files Changed

**Application:**

* `src/product-reviews/product_reviews_server.py` — configurable `max_workers`.

**Documentation:**

* `docs/changes/2026-07-16-product-reviews-grpc-max-workers.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-16-product-reviews-probe-llm-saturation.md`
* Requires image build/push and chart tag promote for the worker change to hit the cluster.
* Chart probe change can ship first and already reduces restart storms.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | More concurrent gRPC handlers; health less likely to starve under LLM load |
| **Infrastructure** | No change |
| **Deployment** | Standard platform CI bake + chart tag promote |
| **Performance** | Higher concurrent LLM outbound calls per pod possible; watch CPU/memory |
| **Reliability** | Fewer false health timeouts when workers were the bottleneck |
| **Backward compatibility** | Default 32 if env unset; safe for local Compose |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Syntax | Python edit review | ✅ |
| Unit tests | No existing health/worker unit tests for this service | N/A |

### Manual Verification

None in-cluster from this change alone (image not published by agent).

### Remaining Verification (Post-Merge)

```cmd
cd /d techx-corp-platform
REM After image deploy:
kubectl -n techx-corp-prod logs deploy/product-reviews | findstr grpc_max_workers
```

Expect: `grpc_max_workers=32` (or chart override).

## Migration or Deployment Notes

1. Merge platform → CI builds release image.
2. Promote tag into chart `values-dev` / prod PR as usual.
3. Ensure chart includes `GRPC_MAX_WORKERS` (companion change) or rely on default 32 in code.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| More concurrent LLM calls overload downstream `llm` service | Medium | Medium | Lower `GRPC_MAX_WORKERS`; scale llm; sampling/rate limits |
| Higher memory per pod under peak concurrency | Low | Medium | 2Gi limit; monitor; reduce workers |

**Rollback procedure:**

Revert `product_reviews_server.py` to hard-coded `max_workers=10` and redeploy the previous image tag.

<!-- Change trail: @hungxqt - 2026-07-16 - Configurable GRPC_MAX_WORKERS for product-reviews health under LLM load. -->
