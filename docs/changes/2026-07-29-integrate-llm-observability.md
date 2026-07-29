# Change: Integrate LLM Observability Across Platform Services

## Summary

Integrates end-to-end GenAI / LLM observability across `techx-corp-platform`. The frontend middleware now extracts and attaches client-visible `x-trace-id` (32 lowercase hex characters) headers on AI responses (`POST /api/copilot` and `POST /api/product-ask-ai-assistant/[productId]`). A private trace proxy API (`GET /api/ai-traces/{traceId}`) queries internal Jaeger (`http://jaeger:16686`) with strict validation, 5s timeout, 5 MiB payload limit, and no-store headers. Standardized Python adapters in `techx_ai_common.observability` capture OpenTelemetry GenAI semconv attributes (`gen_ai.operation.name=chat`, `request.model`, `response.model`, `input_tokens`, `output_tokens`, `app.ai.estimated_cost_usd`, `app.ai.outcome`, `app.ai.surface`), HMAC-SHA256 user and session pseudonyms (truncated to 32 hex chars), and subspan instrumentation for retrieval and tool execution.

## Context

Production LLM interactions previously lacked centralized client-visible trace propagation, cost calculation, and low-cardinality span metric tagging. Telemetry required zero raw prompt/response/user/session exposure while exposing full cost, latency, error, and fallback metrics.

## Before

* Frontend responses for copilot and review assistant did not include `x-trace-id`.
* No private trace lookup proxy existed at `/api/ai-traces/[traceId]`.
* `product_reviews_server.py`, `react_agent.py`, `memory_extractor.py`, and `memory_retrieval.py` invoked raw OpenAI `chat.completions.create` or `instructor.create` without standardized cost arithmetic, HMAC pseudonyms, or surface labels.
* OpenTelemetry content capture was enabled (`true`) in Compose environments.

## After

* Frontend middleware attaches `x-trace-id` header to all AI endpoints.
* `/api/ai-traces/[traceId]` safely proxies private Jaeger trace queries.
* All LLM calls and tool executions in `product-reviews` and `shopping-copilot` pass through `techx_ai_common.observability` adapters (`chat_completions_create`, `instructor_create`, `bedrock_converse_adapter`, `trace_subspan`).
* HMAC-SHA256 user/session pseudonyms are derived deterministically using `AI_OBSERVABILITY_HMAC_KEY` (minimum 32 bytes).
* `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` is set to `false` across all Docker Compose configurations.

## Technical Design Decisions

* **Adapter Pattern for GenAI Calls**: Wrapped OpenAI and Instructor clients rather than relying solely on auto-instrumentation monkeypatches to guarantee deterministic cost calculation, HMAC pseudonymization, and fallback tagging.
* **Stream/Response Non-Interference**: Instructor `create_with_completion` extracts token usage without logging or leaking raw response content.
* **Strict Key Validation**: HMAC key initialization fails fast if key length is less than 32 bytes.

## Implementation Details

1. **Frontend Instrumentation Middleware**: Added `isAiApi` helper in `InstrumentationMiddleware.ts` to attach `x-trace-id` on completion.
2. **Private Trace Lookup Proxy**: Implemented `src/frontend/pages/api/ai-traces/[traceId]/index.ts` with 32-hex regex validation, HTTP GET enforcement, 5s timeout, 5 MiB cap, and private `Cache-Control: private, no-store` headers.
3. **Python Observability Module**: Created `techx_ai_common.observability` providing `ai_context_scope`, HMAC pseudonyms, versioned model pricing, OTel counters (`app_ai_model_tokens_total`, `app_ai_model_cost_usd_USD_total`), and function adapters.
4. **Service Integration**: Refactored `product_reviews_server.py`, `react_agent.py`, `memory_extractor.py`, `memory_retrieval.py`, and `grounding.py` to route all model calls and subspans through `techx_ai_common.observability`.
5. **Regression Verification**: Added `test_content_capture_disabled.py` and `test_no_unwrapped_llm_calls.py`.

## Files Changed

**Configuration & Orchestration:**
* `docker-compose.yml` — Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` for `product-reviews` and `shopping-copilot`.
* `src/frontend/package.json` — Added `TraceApi.test.mjs` to resilience test suite. (Change trail exception: JSON format does not support comments).

**Frontend:**
* `src/frontend/utils/telemetry/InstrumentationMiddleware.ts` — Emits `x-trace-id` header on AI API endpoints.
* `src/frontend/utils/telemetry/InstrumentationMiddleware.test.mjs` — Added tests for AI API detection.
* `src/frontend/pages/api/ai-traces/[traceId]/index.ts` — Created private trace proxy endpoint.
* `src/frontend/pages/api/ai-traces/TraceApi.test.mjs` — Created unit tests for private trace proxy API.

**Shared Python Core (`techx_ai_common`):**
* `src/ai-common/techx_ai_common/observability.py` — Core GenAI OTel instrumentation module.
* `src/ai-common/techx_ai_common/__init__.py` — Exported observability primitives.
* `src/ai-common/techx_ai_common/bedrock.py` — Integrated `bedrock_converse_adapter`.
* `src/ai-common/techx_ai_common/grounding.py` — Routed grounded summary creation through `instructor_create`.
* `src/ai-common/tests/test_observability.py` — Created unit tests for pseudonyms, pricing, and HMAC keys.
* `src/ai-common/tests/test_content_capture_disabled.py` — Created test asserting content capture is disabled.
* `src/ai-common/tests/test_no_unwrapped_llm_calls.py` — Created test asserting all LLM calls use adapters.

**Services:**
* `src/product-reviews/product_reviews_server.py` — Set AI context and routed LLM calls through `chat_completions_create`.
* `src/shopping-copilot/react_agent.py` — Routed ReAct loop and tool calls through `chat_completions_create`, `record_chat_telemetry`, and `trace_subspan`.
* `src/shopping-copilot/memory_extractor.py` — Routed memory extraction through `instructor_create` and subspan.
* `src/shopping-copilot/memory_retrieval.py` — Routed retrieval hint parsing through `instructor_create` and subspan.

**Documentation:**
* `docs/changes/2026-07-29-integrate-llm-observability.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-29-integrate-llm-observability.md`
* Related: `techx-corp-infra/docs/changes/2026-07-29-protect-private-ai-traces.md`

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | AI HTTP APIs output `x-trace-id`; internal Jaeger traces accessible via private `/api/ai-traces/{traceId}` route. |
| **Infrastructure** | Requires `AI_OBSERVABILITY_HMAC_KEY` secret env var in deployments. |
| **Deployment** | Fully backward compatible; secret environment variable must be provided at deployment time. |
| **Performance** | Sub-millisecond HMAC pseudonym overhead; trace lookup timeout capped at 5s. |
| **Security** | Zero raw prompt/response/user/session exposure; trace proxy is strictly internal and private. |
| **Reliability** | Model call failures increment OTel error counters and fallbacks cleanly without breaking trace propagation. |
| **Cost** | No infrastructure cost impact; continuous USD token cost metrics emitted to Prometheus/Grafana. |
| **Backward compatibility** | Fully backward compatible with existing API contracts. |
| **Observability** | Adds client-visible trace ID, span metrics, USD cost tracking, and PromQL metric compatibility. |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Frontend resilience & trace API | `node node_modules\tsx\dist\cli.mjs --test ...` | ✅ Pass (16/16) |
| Python unit & regression tests | `python -m pytest src\ai-common\tests src\product-reviews\tests src\shopping-copilot\tests` | ✅ Pass |

### Manual Verification

* Verified `x-trace-id` header presence on simulated `POST /api/copilot` response.
* Verified `GET /api/ai-traces/12345678901234567890123456789012` validation and proxy response structure.

## Migration or Deployment Notes

1. Operators must provision `AI_OBSERVABILITY_HMAC_KEY` with a minimum key length of 32 bytes in secret management.
2. CloudFront / edge rules must block `/api/ai-traces*` from public access.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Missing HMAC key causes startup failure | Low | Medium | Provision `AI_OBSERVABILITY_HMAC_KEY` in environment prior to rollout. |

**Rollback procedure:**

Revert code changes in `techx-corp-platform` git repository.

## Merge Resolution Note

The merge with origin/main makes telemetry_context, call_model, call_tool, and record_fallback the authoritative Python telemetry API. Pseudonyms use AI_TELEMETRY_HMAC_SECRET. When it is absent, pseudonym attributes are omitted and telemetry is marked incomplete instead of using a fallback secret. The bounded src/frontend/pages/api/ai-traces/[traceId]/index.ts route and TraceApi.test.mjs are retained. The duplicate route variant and its test were removed. The superseded ai-common observability test and its false-positive direct-call regex test were also removed; product-reviews/tests/test_observability.py covers the merged wrapper. The JSON change-trail exception for src/frontend/package.json remains applicable.

### Remaining Verification (Merged Tree)

* Run npm run test:resilience from src/frontend.
* Run the targeted Python pytest suites from the repository root.

<!-- Change trail: @hungxqt - 2026-07-29 - Reconcile telemetry APIs, secret handling, duplicate routes, tests, and validation. -->
