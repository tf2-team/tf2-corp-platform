# 07 - Baseline vs Cache-enabled summary (A1.3)

**Date measured:** 2026-07-27  
**Stack:** docker compose + `docker-compose.ai-dev.yml`  
**Model:** Bedrock `us.amazon.nova-2-lite-v1:0` (`LLM_PROVIDER=bedrock`, region `us-east-1`)  
**Cache config:** `AI_CACHE_TTL_SECONDS=3600`, `AI_CACHE_MAX_DISTANCE=0.40`  
**Replay script:** `src/product-reviews/scripts/replay_summary_cache.py` (7 requests / set)

## Comparison table

| Metric | Baseline (`AI_CACHE_ENABLED=false`) | Cache enabled (empty cache at start) | Saving / notes |
|---|---:|---:|---|
| Requests | 7 | 7 | same scenario set |
| Cache hits | 0 | 2 | exact=1, semantic=1 |
| Cache hit-rate | 0.0% | 28.6% | +28.6 pp |
| Cache misses | 7 | 5 | isolation + first-fill |
| Mean latency (ms) | 5160.3 | 5885.1 | overall mix |
| p95 latency (ms) | 16886.2 | 18706.9 | cold miss dominates p95 |
| Mean latency hit (ms) | 0.0 | 1495.9 | hit path skips LLM |
| Mean latency miss (ms) | 5160.3 | 7640.8 | Bedrock path |
| Model-call proxy (miss count) | 7 | 5 | hits do not re-call model |

## DoD proof rows (from `04-replay-cache-enabled.jsonl`)

| Scenario | Result |
|---|---|
| Same user/product/question attempt=1 | `miss` (store) |
| Same user/product/question attempt=2 | `hit` + `exact` |
| Paraphrase same product/user | `hit` + `semantic` (distance ~0.349, threshold 0.40) |
| Same question, different product | `miss` |
| Same product/question, different user | `miss` (user isolation) |
| anonymous x 2 | `miss` (bypass / no share) |

## Latency observation

- Exact/semantic **hit** mean ~ **1495.9 ms**
- **Miss** mean ~ **7640.8 ms** (Bedrock invoked)
- Relative miss-to-hit speedup ~ **5.11x** on this run

## Cost note

JSONL replay does not emit token counters. Model-call **proxy** for this fixed 7-request set:

- Baseline model invocations ~ **7**
- Cache-enabled model invocations ~ **5** (2 hits skipped LLM)
- Estimated invocation reduction ~ **28.6%** on this replay set

Pair with Bedrock pricing for `us.amazon.nova-2-lite-v1:0` in `us-east-1` and optional Grafana metrics
(`ai_cache_model_calls_total`, token counters) if scraped.

## Related artifacts

- `01-tests-output.txt`
- `02-valkey-index.txt`
- `03-replay-baseline.jsonl`
- `04-replay-cache-enabled.jsonl`
- `08-ttl-check.txt`
- `09-fail-open.txt`
- `10-source-invalidation.txt`
