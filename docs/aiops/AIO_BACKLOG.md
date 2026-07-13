# AIOps Prioritized Operations Backlog - Week 1 / Sprint 1

This backlog ranks the AIOps work for AIO4 / TF2. Requirements and system facts come from the Phase 3 source of truth:

- `phase3/onboarding/SLO.md` - official SLOs, error budgets, and measurement windows.
- `phase3/onboarding/ARCHITECTURE.md` - official service map and observability stack.
- `phase3/onboarding/INCIDENT_HISTORY.md` - closed historical incidents and remaining lessons.
- `phase3/RULES.md` - operating rules, required deliverables, and protected incident mechanisms.
- `phase3/techx-corp-platform/` and `phase3/techx-corp-chart/` - provided source, telemetry configuration, dashboards, and deployment configuration.

`baseline_metrics.md` is team-observed evidence from the current deployment. The PromQL templates used for QPS, error rate, and latency percentiles calculate from a rolling `[5m]` lookback.


---

## Prioritized Backlog

| Rank | ID | Priority | Deliverable | Why now |
|---:|---|---|---|---|
| 1 | [OPS-01](#ops-01---official-customer-flow-slo-coverage) | **P0** | Official customer-flow SLO coverage | Direct protection for customer commitments; checkout is revenue-critical. |
| 2 | [OPS-03](#ops-03---checkout-dependency-failure-detection) | **P0** | Checkout dependency failure detection | Reduces detection and diagnosis time on the revenue path. |
| 3 | [OPS-02](#ops-02---alert-db-connection-saturation) | **P0** | DB connection baseline and saturation alert | Recurrence protection for the high-impact historical checkout incident. |
| 4 | [OPS-04](#ops-04---flag-inventory--incident-signature-mapping) | **P1** | High-risk flag signatures, then full inventory | Improves incident readiness after core SLO/dependency protection exists. |
| 5 | [OPS-07](#ops-07---service-topology--blast-radius-map) | **P1** | Minimum topology first, then full evidence map | Enables RCA but does not directly protect an SLO by itself. |
| 6 | [OPS-05](#ops-05---llm-observability-dashboard--alerting) | **P1** | LLM observability | Important AI visibility, but the AI path has no hard availability or latency SLO. |
| 7 | [OPS-06](#ops-06---kafka-consumer-lag--error-alert) | **P2** | Kafka lag discovery and alerting | Async risk with no official threshold, confirmed current failure, or verified lag series yet. |

Priority rules:

- Complete P0 outcomes before full P1/P2 scope.
- A BTC directive or active incident preempts this order.
- Promote an item only when new deployment evidence changes likelihood or business impact; record the decision in the signed decision log/ADR.
- For OPS-04 and OPS-07, deliver the minimum high-risk coverage first. Full inventory/documentation remains P1 scope.

---

## OPS-01 - Official customer-flow SLO coverage

**Priority:** P0 - Rank 1

### Context

Phase 3 defines these official customer-flow commitments. They use a rolling 24-hour window for daily operations and are summarized weekly in Ops Review.

| Flow | Official Phase 3 objective |
|---|---:|
| Browse/search availability | non-5xx success >= 99.5% |
| Storefront browse latency | p95 < 1 second |
| Cart operations | success >= 99.5% |
| Checkout | success >= 99.0% |
| AI review summary | best-effort; must not show inaccurate summaries |

Checkout remains first within this item because Phase 3 identifies it as the most important revenue path. Phase 3 does not define a checkout latency SLO; checkout latency percentiles are diagnostic signals only.

The latest `baseline_metrics.md` test order records:

| Observed signal | Latest baseline |
|---|---:|
| Frontend error rate | `N/A` |
| Frontend p95 | ~15000ms |
| Cart error rate | `N/A` |
| Checkout QPS | ~3.16 req/s |
| Checkout error rate | ~7.87% |
| Checkout p50 | ~2000ms |
| Checkout p95 | ~8420ms |
| Checkout p99 | ~10200ms |
| Sample checkout trace latency | ~5.44s |


### Problem

There is no documented, validated mapping from every official customer flow to its Prometheus SLI and alert. Without that mapping, the team cannot reliably report SLO status or error-budget exhaustion. Checkout latency still needs monitoring as supporting evidence because Phase 3 incident history records it rising to several seconds during DB connection exhaustion.

### Proposed Solution

1. Create and sign off an SLI mapping table:

   `official flow -> customer event -> Prometheus series/labels -> rolling-24-hour query -> owner -> known limitation`

   Use the HTTP/RPC series already present in the Phase 3 APM dashboards, but validate the customer-facing route or RPC before treating a service metric as an official SLI.

2. Create a checkout `PlaceOrder` rolling-24-hour error-ratio alert aligned with the official 1% error budget.

   ```promql
   (
     (
       (
         sum(increase(rpc_server_duration_milliseconds_count{service_name="checkout", rpc_method="PlaceOrder", rpc_grpc_status_code!="0"}[24h]))
         /
         clamp_min(sum(increase(rpc_server_duration_milliseconds_count{service_name="checkout", rpc_method="PlaceOrder"}[24h])), 1)
       ) * 100
     )
     or
     (0 * sum(increase(rpc_server_duration_milliseconds_count{service_name="checkout", rpc_method="PlaceOrder"}[24h])))
   ) > 1
   ```

   Validate that `PlaceOrder` completion and gRPC status represent completed customer checkout attempts before activating the alert. If they do not, define the correct end-to-end SLI from available Phase 3 telemetry and record the mapping in the ADR.

3. Add rolling-24-hour availability/error-budget queries for browse/search and cart using only validated customer routes/RPCs. Alert at the official boundaries: 0.5% failed browse/search requests and 0.5% failed cart operations.

4. Add the official storefront p95 latency query using the validated customer-facing storefront series and alert when p95 is >= 1 second. Do not reuse this threshold for checkout.

5. Coordinate with AIE on the AI-summary correctness signal. Show the latest evaluation status or an explicit observability gap; do not infer correctness from latency or error rate.

6. Show checkout QPS, error rate, and p50/p95/p99 latency as diagnostic panels without an official checkout latency threshold.

7. Route SLO alerts to the TF2 on-call channel with flow, signal, value, official threshold, measurement window, dashboard link, trace/log link, runbook ID, and owner.

### Acceptance Criteria

- The SLI mapping covers browse/search availability, storefront p95, cart success, checkout success, and AI-summary correctness status/gap.
- Grafana shows rolling-24-hour status and error-budget state for every official numeric SLO.
- Alerts use the official boundaries: browse/search failure > 0.5%, storefront p95 >= 1 second, cart failure > 0.5%, and checkout failure > 1%.
- The chosen telemetry is demonstrated to represent the customer flow, or its limitation and replacement work are explicit.
- Alerts include SLO/error-budget context and the rolling-24-hour measurement window.
- Dashboard shows checkout QPS, p50/p95/p99, error rate, and latest trace evidence.
- Dashboard labels checkout latency as a diagnostic SLI, not an official SLO.
- AI-summary correctness is sourced from an AIE evaluation signal or marked as an open dependency, never guessed from operational metrics.
- Every alert can be verified with a controlled rule test without changing or disabling the protected Phase 3 incident mechanism.

### Verification

1. Exercise browse/search, cart, and checkout with controlled traffic and confirm that each selected counter changes as expected.
2. Compare dashboard queries with `baseline_metrics.md`, while keeping the sample window distinct from the official rolling-24-hour window.
3. Test each rule with recorded/synthetic metric input or a temporary test rule; do not redefine official thresholds.
4. Verify alert payloads link to the correct flow dashboard and representative trace/log evidence.
5. Review the SLI mapping and AI correctness dependency with AIE/CDO before marking OPS-01 complete.

### English Summary

Implement validated rolling-24-hour coverage for all official Phase 3 SLOs, with checkout first. Keep checkout latency diagnostic-only and obtain AI-summary correctness status from AIE evaluation evidence.

---

## OPS-02 - Alert DB connection saturation

**Priority:** P0 - Rank 3

### Context

Phase 3 incident history records a closed incident where DB connection exhaustion pushed checkout latency into seconds and reduced checkout success to around 95%. It also says high-load behavior has not been thoroughly verified. The provided Phase 3 source shows:

- `product-reviews/database.py` calls `psycopg2.connect(...)` for its DB operations.
- `product-catalog/main.go` registers DB statistics through `otelsql` and does not explicitly set maximum/idle connection limits.
- `baseline_metrics.md` does not currently contain a PostgreSQL connection baseline, so current saturation must be measured rather than assumed.

### Problem

AIOps needs early warning before DB connection pressure becomes checkout latency and timeout failures.

### Proposed Solution

1. Alert on PostgreSQL active backend pressure.

   ```promql
   sum(postgresql_backends) by (postgresql_database_name)
   ```

Derive the threshold from the target environment's configured `max_connections`, observed baseline, and controlled load evidence. Record and approve the chosen threshold in a signed ADR; Phase 3 does not prescribe a percentage.

2. Discover the client-side DB pool metrics actually exported in the target environment, especially for `product-catalog`.

   ```promql
   count by (__name__) ({__name__=~"db_client_connections_.*|db_sql_connection_.*"})
   ```

3. Build utilization/wait queries only from metric names and labels confirmed by discovery. For services without client pool metrics, record `N/A` and rely on `postgresql_backends`, service latency, traces, and logs.

### Acceptance Criteria

- PostgreSQL dashboard shows active backends, deadlocks, and database-level activity.
- Alert fires before backend usage reaches the saturation threshold.
- Runbook explains which services are likely DB clients: `product-catalog`, `product-reviews`, `accounting`.

### Verification

1. Run increased Locust traffic and observe `postgresql_backends`.
2. Record the exact DB client metric names and labels present for `product-catalog`.
3. Record missing client metrics as a known gap, not as zero.

### English Summary

Detect PostgreSQL saturation early using server-side backend metrics first, then client-side pool metrics where they actually exist.

---

## OPS-03 - Checkout dependency failure detection

**Priority:** P0 - Rank 2

### Context

Checkout depends on a chain of services:

`checkout -> cart -> product-catalog -> currency -> shipping/quote -> payment -> email -> kafka`

Phase 3 architecture shows that checkout depends on cart, product-catalog, currency, shipping/quote, payment, email, and Kafka. Phase 3 incident history also states that some components remain single points of failure, so dependency failure remains a revenue-path risk.

### Problem

When checkout fails, server-side checkout RPC error metrics can say "checkout is failing" but do not reliably identify the downstream dependency that caused the failure. AIOps needs span-level evidence for triage.

### Proposed Solution

1. Use spanmetrics to identify failing checkout spans.

   ```promql
   sum(rate(traces_span_metrics_calls_total{service_name="checkout", status_code="STATUS_CODE_ERROR"}[5m])) by (span_name)
   ```

2. Use spanmetrics to identify slow checkout spans.

   ```promql
   histogram_quantile(
     0.95,
     sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="checkout"}[5m])) by (le, span_name)
   )
   ```

3. Pair span evidence with Jaeger trace links and OpenSearch logs.

4. Map dependency symptoms to runbook entries:

   - payment failure or `paymentFailure` / `paymentUnreachable`
   - cart failure or `cartFailure`
   - shipping/quote latency or failure
   - product-catalog failure
   - Kafka publish failure

### Acceptance Criteria

- Alert identifies the likely failing span/dependency, not only "checkout failed".
- Dashboard shows checkout spans by error rate and p95 latency.
- Runbook maps each dependency to first response, evidence links, owner, and escalation path.

### Verification

1. Use recorded/synthetic telemetry for rule testing. Exercise a known incident flag only when explicitly authorized by BTC in a controlled environment.
2. Confirm alert names the likely dependency and links to a trace.
3. Confirm alerts are grouped to prevent alert storms when checkout cascades.

### English Summary

Detect checkout dependency failures using spanmetrics by `span_name`, not only checkout server RPC metrics.

---

## OPS-04 - Flag inventory + incident signature mapping

**Priority:** P1 - Rank 4. Promote only the signature for an active/imminent authorized incident when evidence requires it.

### Context

BTC injects incidents through `flagd`. The platform `demo.flagd.json` currently contains 15 flags, including:

- `llmInaccurateResponse`
- `llmRateLimitError`
- `productCatalogFailure`
- `recommendationCacheFailure`
- `adManualGc`
- `adHighCpu`
- `adFailure`
- `kafkaQueueProblems`
- `cartFailure`
- `paymentFailure`
- `paymentUnreachable`
- `loadGeneratorFloodHomepage`
- `imageSlowLoad`
- `failedReadinessProbe`
- `emailMemoryLeak`

Rules explicitly prohibit disabling, bypassing, or tampering with flagd.

### Problem

When a flag-driven incident is activated, AIOps needs to detect symptoms and map them to a runbook quickly without changing flagd.

### Proposed Solution

1. Map the highest-risk checkout/cart flags first, then complete the full flag inventory:

   `flag -> behavior -> affected service -> expected metric/log symptom -> likely SLO impact -> runbook`

2. Monitor flag-related logs in OpenSearch, for example:

   ```text
   search source=otel-logs-* | where body like "*feature flag*" or body like "*FeatureFlag*" or body like "*flagd*" | sort - observedTimestamp | head 100
   ```

3. Build incident signatures for the highest-risk flags:

   - `paymentFailure` / `paymentUnreachable` -> checkout errors
   - `kafkaQueueProblems` -> Kafka lag / consumer delay
   - `llmRateLimitError` -> product-reviews AI span errors or fallback
   - `failedReadinessProbe` / `cartFailure` -> cart health or checkout failures

### Acceptance Criteria

- High-risk checkout/cart flags are completed first; the full P1 deliverable covers all 15 current flags.
- Every high-risk flag maps to at least one metric/log/trace symptom.
- Every high-risk flag has a runbook stub.
- Documentation explicitly says "do not disable flagd".

### Verification

1. Use recorded/synthetic telemetry by default. Exercise a flag only with explicit BTC authorization in a controlled environment.
2. Verify logs/traces/metrics show the expected signature.
3. Verify the runbook recommendation is containment/escalation, not flag tampering.

### English Summary

Build a 15-flag incident inventory and map each flag to symptoms, severity, evidence, and runbooks.

---

## OPS-05 - LLM observability dashboard + alerting

**Priority:** P1 - Rank 6

### Context

The AI path is observed primarily through `product-reviews`. The `llm` Flask service itself is not directly OpenTelemetry-instrumented, so it does not appear as a standalone service in Jaeger. `baseline_metrics.md` shows:

- `product-reviews` QPS ~1.8 req/s
- `product-reviews` error rate: `N/A` in the measured 5m window
- `product-reviews` p50 ~3420ms
- `product-reviews` p95 ~8500ms
- `product-reviews` p99 ~9700ms

The custom metric `app_ai_assistant_counter_total` exists, but `gen_ai_client_*` metrics must be verified in Prometheus before being used as hard alert inputs.

### Problem

AIOps lacks reliable AI-layer visibility for latency, errors, rate limits, and token/cost signals. The LLM layer is best-effort, but it must not break product pages or hide failure symptoms.

### Proposed Solution

1. Track AI assistant request volume.

   ```promql
   sum(rate(app_ai_assistant_counter_total[5m])) by (service_name)
   ```

2. Track `product-reviews` AI assistant span latency.

   ```promql
   histogram_quantile(
     0.95,
     sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="product-reviews", span_name="get_ai_assistant_response"}[5m])) by (le)
   )
   ```

3. Track AI assistant span errors.

   ```promql
   sum(rate(traces_span_metrics_calls_total{service_name="product-reviews", span_name="get_ai_assistant_response", status_code="STATUS_CODE_ERROR"}[5m]))
   ```

4. Use `gen_ai_client_*` only after confirming the metrics exist in Prometheus. If missing, record `N/A` and use product-reviews span/log evidence until instrumentation is added.

5. Monitor rate-limit and inaccurate-response flags through logs:

   - `llmRateLimitError`
   - `llmInaccurateResponse`

### Acceptance Criteria

- Dashboard shows AI request volume, product-reviews AI span p95/p99, AI span errors, and flag-related evidence.
- `gen_ai_client_*` availability is documented as `present` or `N/A`.
- Alert fires when `llmRateLimitError` causes AI span errors or fallback behavior.

### Verification

1. Trigger AI assistant flow through product details.
2. Verify `app_ai_assistant_counter_total` increments.
3. Verify `get_ai_assistant_response` appears in spanmetrics or Jaeger.
4. Record whether `gen_ai_client_*` metrics exist.

### English Summary

Observe LLM behavior from the `product-reviews` side first. Treat `gen_ai_client_*` metrics as optional until verified.

---

## OPS-06 - Kafka consumer lag + error alert

**Priority:** P2 - Rank 7. Start after P0 and committed P1 outcomes unless an incident/directive changes its business impact.

### Context

Checkout publishes order events to Kafka. `accounting` and `fraud-detection` consume asynchronously. The `kafkaQueueProblems` flag can overload the producer path and slow consumers.

The provided Phase 3 Helm values configure the OpenTelemetry Collector `kafkametrics` receiver. This confirms the receiver configuration, but not the exact metric names present in the team's Prometheus deployment; those must be discovered and recorded.

### Problem

Async order processing can lag or fail without immediately breaking checkout, so customer-facing success can hide accounting/fraud-processing risk.

### Proposed Solution

1. Discover the Kafka metrics actually exported in the target environment.

   ```promql
   count by (__name__) ({__name__=~"kafka_.*"})
   ```

2. From the discovered series, identify consumer lag and group/topic labels. Record missing signals as `N/A`; do not assume a metric name or treat absence as zero.

3. Establish the normal lag range from the current deployment and controlled traffic. Approve any alert threshold and evaluation duration in a signed ADR because Phase 3 defines no Kafka lag threshold.

4. Add log-based evidence for checkout producer failures:

   - `Failed to write message`
   - `Failed to send message to Kafka`
   - `kafkaQueueProblems`

### Acceptance Criteria

- Dashboard shows Kafka lag by group/topic.
- Alert states its confirmed metric name and labels, or that it uses a documented log fallback.
- Runbook covers `accounting`, `fraud-detection`, checkout producer, and `kafkaQueueProblems`.

### Verification

1. Record the exact Kafka lag metric names and labels present in the target environment.
2. If missing, record `N/A` and use log/span fallback until collector config is updated.
3. Test with recorded/synthetic telemetry. Exercise `kafkaQueueProblems` only when explicitly authorized by BTC in a controlled environment.

### English Summary

Alert on Kafka lag where `kafkametrics` exists, and document fallback evidence for environments where Kafka metrics are missing.

---

## OPS-07 - Service topology / blast-radius map

**Priority:** P1 - Rank 5

### Context

Phase 3 documents around 18 services and multiple hard dependencies in the checkout path. Its incident history confirms that some components remain single points of failure.

### Problem

Without a topology and blast-radius map, incident triage and RCA take too long. AIOps needs a service map that links every critical node to metrics, traces, logs, owner, and runbook.

### Proposed Solution

1. Build the minimum checkout-path Mermaid topology first, then enrich it with full evidence links:

   `frontend -> checkout -> cart/product-catalog/currency/shipping/quote/payment/email/kafka -> accounting/fraud-detection`

2. Mark a component as a SPOF only after validating its deployed replicas, state durability, and failover behavior. Phase 3 specifically records unresolved single-instance risk in the cart storage path; other components require deployment evidence before classification.

3. Map telemetry signals:

   - service health: `traces_span_metrics_calls_total`
   - service latency: `traces_span_metrics_duration_milliseconds_bucket`
   - checkout operation: `rpc_server_duration_milliseconds_*`
   - PostgreSQL: `postgresql_backends`
   - Kafka: the lag metric confirmed by target-environment discovery, or documented log evidence
   - logs: OpenSearch `otel-logs-*`

### Acceptance Criteria

- A minimum checkout-path topology is available before full enrichment begins.
- The completed P1 topology map is stored in Markdown with Mermaid.
- Every checkout dependency has metrics, logs/traces, likely failure symptom, owner, and runbook.
- Map is checked against Jaeger traces and source code.

### Verification

1. Compare the static map with a Jaeger checkout trace.
2. Verify each node has at least one telemetry signal.
3. Record any missing signal as an observability gap.

### English Summary

Create the topology and blast-radius map needed for RCA and runbook matching across the checkout path.
