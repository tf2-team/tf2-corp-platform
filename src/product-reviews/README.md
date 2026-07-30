# Product Reviews Service

This service returns product reviews for a specific product, along with an
AI-generated summary of the product reviews.

## Local Build

To build the protos, run from the root directory:

```sh
make docker-generate-protobuf
```

## Docker Build

From the root directory, run:

```sh
docker compose build product-reviews
```

## Hybrid Semantic Cache (A1.3 Summary Bot)

Valkey hybrid cache (exact key + filtered vector KNN) reduces repeated model
calls for grounded review Q&A. Shared adapter: `techx_ai_common.semantic_cache`.

### Setup

```powershell
docker compose up -d valkey-ai-cache ai-cache-bootstrap
docker exec valkey-ai-cache valkey-cli PING
docker exec valkey-ai-cache valkey-cli FT._LIST
```

Expect `PONG` and index `ai_summary_cache_idx`.

Environment (see compose defaults):

| Variable | Default | Meaning |
|---|---|---|
| `AI_CACHE_ENABLED` | `false` | Master feature flag |
| `AI_CACHE_ADDR` | `valkey-ai-cache:6379` | Valkey endpoint |
| `AI_CACHE_TTL_SECONDS` | `3600` | Entry TTL |
| `AI_CACHE_MAX_DISTANCE` | `0.12` | Max cosine distance for semantic hit |
| `AI_CACHE_USER_HMAC_SECRET` | local secret | HMAC for `user_scope` |

Identity metadata on `AskProductAIAssistant`:

- `x-user-id` — stable cache boundary (required for hit/store; missing/anonymous → bypass)
- `x-session-id` — rate-limit boundary

`source_hash` is computed from **sanitized** reviews (`source_id|score|text`, sorted)
before question retrieval so review edits invalidate cache.

### Tests

```powershell
$env:AI_CACHE_ENABLED="true"
python -m pytest src/ai-common/tests/test_semantic_cache.py -v
python -m pytest src/product-reviews/tests/test_summary_cache.py -v
```

### Replay evidence

```powershell
# Service must run with AI_CACHE_ENABLED=true
python src/product-reviews/scripts/replay_summary_cache.py --host localhost --port <grpc-port> --output replay.jsonl
```

JSONL lines include `cache_status`, `cache_match`, `cache_distance`, `latency_ms`.
Run once with cache off (baseline) and once with cache on (empty start) to compare
hit-rate, model calls, tokens, and cost from metrics.

## LLM Configuration

Use Amazon Bedrock Nova through `.env`:

``` yaml
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=global.amazon.nova-2-lite-v1:0
BEDROCK_MAX_TOKENS=1024
```

Supply AWS credentials locally (or an IRSA role in Kubernetes), then start the
stack:

```sh
docker compose up -d
```

The runtime uses the Bedrock Converse API. Never commit long-lived AWS
credentials; use an AWS profile locally and IRSA in Kubernetes.
