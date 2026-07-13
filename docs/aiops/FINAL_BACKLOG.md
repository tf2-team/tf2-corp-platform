# TF2 Consolidated Backlog

This document is the consolidated backlog for Task Force 2, combining the AIE AI Shopping Experience backlog and the AIOps operations backlog.

- **OPS - AIOps operational reliability:** protect official Phase 3 SLOs, shorten detection/diagnosis time, and map incident evidence to runbooks.
- **AIE - AI Shopping Experience:** make AI answers grounded and safe, then expand into a shopping copilot with search, review Q&A, cart confirmation, and bounded multi-turn orchestration.

## 1. Executive Summary

The highest priority is not to add more AI capability or more dashboards in isolation. The priority is to protect the revenue path and user trust before expanding system behavior:

1. **Official customer-flow SLOs must be measurable and alertable.** Browse/search, storefront latency, cart success, checkout success, and AI-summary correctness must each have a validated signal or an explicit gap.
2. **Checkout needs dependency-level failure detection.** Checkout is the revenue path, and failures must identify likely downstream causes, not only say "checkout failed."
3. **AI must not answer without evidence.** Review summaries and product Q&A must cite real reviews or abstain when evidence is missing.
4. **AI must treat user/review content as untrusted.** Prompt injection, PII leakage, unsafe tool calls, and raw prompt logging must be guarded before adding more tools.
5. **AI must not write to cart without confirmation.** Cart writes require backend-enforced confirmation tied to the correct user, product, quantity, and expiry.
6. **Best-effort dependencies must not break customer flows.** LLM, Kafka, DB, and downstream service failures need fallback, alerting, and runbook coverage.

The delivery order below puts P0 operational protection and AIE safety foundations first, then adds Shopping Copilot capability, then hardens resilience, topology, flags, Kafka, and multi-turn behavior.

## 2. Current State

### AIOps operational state

- Phase 3 defines official customer-flow SLOs for browse/search availability, storefront p95 latency, cart success, checkout success, and AI review summary correctness.
- Checkout is the most important revenue path and depends on cart, product-catalog, currency, shipping/quote, payment, email, and Kafka.
- `baseline_metrics.md` shows checkout QPS around 3.16 req/s, checkout error rate around 7.87%, checkout p95 around 8420ms, and a sample checkout trace around 5.44s.
- Phase 3 incident history records DB connection exhaustion pushing checkout latency into seconds and reducing checkout success to around 95%.
- The platform has Prometheus, Grafana, OpenTelemetry, Jaeger, OpenSearch, and `flagd`, but some metric names and labels must be discovered before alerts are treated as production SLO signals.
- `flagd` is a protected incident mechanism and must not be disabled, bypassed, or tampered with.

### AIE AI shopping state

- Main AI entry point is `phase3/techx-corp-platform/src/product-reviews/product_reviews_server.py`.
- `AskProductAIAssistant` receives `product_id` and `question`, calls the LLM once for tool choice, executes a backend tool, then calls the LLM again for the final answer.
- Current tool registry includes `fetch_product_reviews` and `fetch_product_info`.
- Response gRPC currently returns plain text through `AskProductAIAssistantResponse.response`.
- Frontend `ProductAIAssistant.provider.tsx` keeps only one `aiResponse`; it does not yet support conversation state.
- `ProductCatalogService.SearchProducts`, `CartService.AddItem`, Valkey, Mem0, OpenTelemetry, Prometheus, Jaeger, Grafana, and OpenSearch are available to reuse.

### Gaps

| Gap | Impact | Backlog items |
| --- | --- | --- |
| Official customer-flow SLOs are not fully mapped to validated Prometheus SLIs and alerts. | SLO status and error-budget burn cannot be reported reliably. | OPS-01 |
| Checkout failures do not clearly identify downstream dependency symptoms. | MTTD/MTTR stay high on the revenue path. | OPS-03 |
| DB connection saturation is not baselined or alerted early. | Historical checkout incident can recur. | OPS-02 |
| Flag-driven incident signatures are not mapped to symptoms/runbooks. | Incident response depends on manual discovery. | OPS-04 |
| Service topology and blast radius are not linked to evidence. | RCA is slower and less repeatable. | OPS-07 |
| LLM metrics and AI fallback behavior are incomplete. | AI failures can be hidden or misdiagnosed. | OPS-05, A1.3 |
| Kafka lag metric names and alert thresholds are not verified. | Async accounting/fraud delay can go unnoticed. | OPS-06 |
| AI final answers are not validated against citations. | AI can hallucinate with confidence. | A1.1, A2.2 |
| Reviews, questions, tool arguments, and logs may contain untrusted raw content. | Prompt injection, PII leakage, and unsafe tool calls are possible. | A1.2 |
| Product search is basic and not structured around natural-language constraints. | Copilot can return poor results or invent products. | A2.1 |
| Cart write actions do not have an AI-specific pending confirmation model. | AI could change cart state before explicit user confirmation. | A2.3 |
| There is no conversation ID, reference resolution, or bounded agent loop. | Multi-turn assistant behavior is fragile and can exceed tool/LLM budget. | A2.4 |

### Components to reuse

- `ProductReviewService.AskProductAIAssistant` as the initial AI entry point.
- `database.fetch_product_reviews_from_db` and `fetch_product_reviews` as review evidence sources.
- `ProductCatalogService.SearchProducts` as the catalog search boundary.
- `CartService.AddItem` as the only final cart write path after confirmation.
- Valkey for validated AI cache and pending cart action state.
- Mem0 for short-term/session memory in the Shopping Copilot.
- OpenTelemetry, Prometheus, Grafana, Jaeger, and OpenSearch for metrics, traces, logs, and dashboards.
- Existing spanmetrics and RPC metrics where labels are verified in the target environment.

## 3. Priority And Dependency Map

The order below combines operational urgency and AI safety dependencies. P0 items protect official commitments and trust boundaries first. P1 items expand incident readiness and Copilot MVP behavior. P2 items harden resilience, async monitoring, and multi-turn orchestration after the core paths are safe.

| Rank | Item | Priority | Depends on | Reason |
| ---: | --- | --- | --- | --- |
| 1 | OPS-01 Official Customer-Flow SLO Coverage | P0 | None | Establishes validated SLO reporting and alerting for Phase 3 commitments, with checkout first. |
| 2 | OPS-03 Checkout Dependency Failure Detection | P0 | OPS-01 | Reduces diagnosis time on the revenue path by naming likely failing spans/dependencies. |
| 3 | OPS-02 DB Connection Saturation Alert | P0 | OPS-01 | Protects against recurrence of the historical DB exhaustion checkout incident. |
| 4 | A1.1 Verified Summarization, Grounding, and Citations | P1 | None | Prevents AI review answers from making unsupported claims. |
| 5 | A1.2 Prompt Injection, PII, and Tool Guardrails | P1 | None | Establishes safety controls before adding more tools and cart capability. |
| 6 | A2.1 Natural Language Product Discovery | P1 | A1.2 | Gives the copilot real catalog-backed product IDs without allowing unsafe tool expansion. |
| 7 | A2.2 Review-Grounded Product Q&A | P1 | A1.1, A2.1 | Uses real product IDs and the grounding pipeline to answer review questions safely. |
| 8 | A2.3 Confirmation-Controlled Cart Actions | P1 | A1.2, A2.1 | Allows AI to prepare cart actions while backend confirmation protects the write path. |
| 9 | OPS-04 Flag Inventory and Incident Signature Mapping | P1 | OPS-01, OPS-03 | Improves incident readiness after core SLO and dependency protection exists. |
| 10 | OPS-07 Service Topology and Blast-Radius Map | P1 | OPS-03 | Connects checkout dependencies to telemetry, owners, runbooks, and RCA evidence. |
| 11 | OPS-05 LLM Observability Dashboard and Alerting | P1 | A1.2, A1.3 partial | Makes the AI path visible through product-reviews spans, counters, logs, and verified gen-ai metrics. |
| 12 | A1.3 Resilience and Cost Optimization | P2 | A1.1, A1.2 | Adds timeout, fallback, validated cache, and cost controls after answers are safe to cache. |
| 13 | OPS-06 Kafka Consumer Lag and Error Alert | P2 | OPS-03 | Covers async order-processing risk after customer-facing P0 protection is in place. |
| 14 | A2.4 Multi-Turn Conversation and Bounded Orchestration | P2 | A2.1, A2.2, A2.3 | Adds memory/reference resolution only after single-turn search, Q&A, and cart confirmation work safely. |

### Dependency Notes

- **OPS-01 should start first** because every official SLO and alert must be tied to a validated customer-flow signal.
- **OPS-03 and OPS-02 are P0** because they protect checkout detection and the known DB saturation failure mode.
- **A1.1 and A1.2 can run in parallel** because one controls answer correctness while the other controls input/tool/telemetry safety.
- **A2.1 needs A1.2** because product discovery expands the agent tool surface.
- **A2.2 needs A1.1 and A2.1** because review Q&A must use the correct product and grounded evidence.
- **A2.3 needs A1.2 and A2.1** because cart writes must be scoped to safe tool arguments and real product IDs.
- **A1.3 should not cache unvalidated answers**; it depends on grounding and guardrail decisions.
- **A2.4 should not be first** because multi-turn state complicates unsafe or ungrounded single-turn behavior.

## 4. Backlog Items

### OPS-01 - Official Customer-Flow SLO Coverage

**Why:** Phase 3 SLOs are the operating contract. Without validated customer-flow SLIs and alerts, TF2 cannot reliably report SLO health, error-budget burn, or AI-summary correctness status.

**What:** Map each official customer flow to a validated Prometheus query, dashboard panel, alert, owner, limitation, and runbook. Prioritize checkout success, but cover browse/search, storefront latency, cart success, and AI-summary correctness status or gap.

**Acceptance Criteria:**

- SLI mapping covers browse/search availability, storefront p95, cart success, checkout success, and AI-summary correctness status/gap.
- Grafana shows rolling-24-hour status and error-budget state for every official numeric SLO.
- Alerts use official thresholds: browse/search failure > 0.5%, storefront p95 >= 1 second, cart failure > 0.5%, checkout failure > 1%.
- Checkout latency is shown as diagnostic only, not as an official checkout latency SLO.
- AI-summary correctness comes from AIE evaluation evidence or is marked as an open dependency.
- Alerts include flow, signal, value, threshold, window, dashboard link, trace/log link, runbook ID, and owner.
- Rules are verified without changing or disabling protected Phase 3 incident mechanisms.

**Reuse / Open-source:**

- Use existing Prometheus RPC/HTTP/spanmetrics series after validating route/RPC labels.
- Use existing Grafana, Alertmanager, Jaeger, OpenSearch, and OpenTelemetry setup.
- Use `baseline_metrics.md` only as observed evidence, not as the official SLO window.

### OPS-03 - Checkout Dependency Failure Detection

**Why:** Checkout failures need dependency-level evidence so on-call can distinguish payment, cart, catalog, shipping, Kafka, or other downstream symptoms quickly.

**What:** Add checkout spanmetric panels and alerts grouped by `span_name`, with trace/log links and runbook mappings for likely downstream failures.

**Acceptance Criteria:**

- Alert identifies the likely failing span/dependency, not only "checkout failed."
- Dashboard shows checkout spans by error rate and p95 latency.
- Runbook maps dependency symptoms to first response, evidence links, owner, and escalation path.
- Alerts are grouped to prevent alert storms during cascading failures.
- Verification uses recorded/synthetic telemetry unless BTC explicitly authorizes controlled flag use.

**Reuse / Open-source:**

- Use `traces_span_metrics_calls_total` and `traces_span_metrics_duration_milliseconds_bucket`.
- Use Jaeger trace links and OpenSearch logs for correlated evidence.
- Reuse Phase 3 architecture dependency chain for checkout.

### OPS-02 - DB Connection Saturation Alert

**Why:** Phase 3 incident history records DB connection exhaustion as a high-impact checkout failure mode. TF2 needs early warning before backend pressure becomes checkout latency and errors.

**What:** Build PostgreSQL backend pressure dashboard/alert first, then discover and use client-side DB pool metrics where they actually exist.

**Acceptance Criteria:**

- PostgreSQL dashboard shows active backends, deadlocks, and database-level activity.
- Alert fires before backend usage reaches the approved saturation threshold.
- Threshold is derived from target `max_connections`, observed baseline, and controlled load evidence, then recorded in an ADR.
- Client-side DB pool metrics are documented as present with exact names/labels or marked `N/A`.
- Runbook identifies likely DB clients: `product-catalog`, `product-reviews`, and `accounting`.

**Reuse / Open-source:**

- Use `sum(postgresql_backends) by (postgresql_database_name)` as the server-side starting point.
- Discover DB client metrics with a metric-name query before creating client-side alerts.
- Use existing Prometheus/Grafana and load-test evidence.

### A1.1 - Verified Summarization, Grounding, and Citations

**Why:** Users need to trust that AI review answers are based on real reviews, not model guesses. Unsupported confident claims reduce trust and can mislead purchase decisions.

**What:** AI review responses must be grounded in source reviews. If evidence is missing, the system must abstain instead of guessing.

**Acceptance Criteria:**

- AI answer contains only claims with valid evidence from reviews.
- Response includes citations or source references sufficient for review.
- Questions without evidence return abstention.
- A fixed eval set exists for before/after comparison.
- A repro script runs factuality, citation correctness, and abstention checks.

**Reuse / Open-source:**

- Reuse `fetch_product_reviews_from_db` and `fetch_product_reviews`.
- Use Instructor + Pydantic for structured answer, claims, and citations.
- Use Ragas for offline grounding/hallucination eval, outside the runtime path.

### A1.2 - Prompt Injection, PII, and Tool Guardrails

**Why:** Reviews and user questions are untrusted input. Without guardrails, malicious content can override policy, leak system prompts, alter tool arguments, or expose PII in LLM requests/logs/traces.

**What:** Add input, output, tool-call, and telemetry guardrails. Backend must control allowed tools, allowed arguments, data sent to LLMs, and data emitted to logs/traces.

**Acceptance Criteria:**

- Tool calls outside the allow-list are rejected.
- Tool arguments outside allowed scope are rejected.
- PII does not appear verbatim in logs, traces, or LLM requests.
- Requests to reveal system prompts or override policy are blocked.
- Repro cases cover prompt injection, PII leakage, and system prompt leakage.

**Reuse / Open-source:**

- Reuse and extend the tool allow-list in `product_reviews_server.py`.
- Use Presidio for PII detection/redaction.
- Use LLM Guard for prompt injection, system prompt extraction, and output leakage scanning.
- Emit only safe metadata through OpenTelemetry.

### A2.1 - Natural Language Product Discovery

**Why:** Shopping Copilot must help users find products with natural-language constraints while returning only real catalog products.

**What:** Parse natural-language needs into safe structured fields such as `query`, `max_price`, and `category`. Backend applies predefined SQL filters against the real catalog. Do not use Text-to-SQL in the MVP.

**Acceptance Criteria:**

- Natural-language query returns products from the catalog.
- Important constraints such as price and category are applied correctly.
- No-results cases do not invent products.
- Results include product IDs for Q&A and cart actions.
- Repro cases cover natural-language search, constraint matching, and no-results behavior.

**Reuse / Open-source:**

- Reuse `ProductCatalogService.SearchProducts` as the search boundary.
- Reuse `product_catalog_stub` after proto/stub regeneration.
- Use Instructor + Pydantic for structured intent parsing.
- Extend `SearchProductsRequest` and `product-catalog` dynamic filtering with safe predefined SQL filters.
- Trace safe search metadata through OpenTelemetry.

### A2.2 - Review-Grounded Product Q&A

**Why:** After users find a product, they need review-based answers about that specific product. Answers must not use another product's reviews or fill gaps with guesses.

**What:** Answer product questions using only reviews for the selected product, reusing the A1.1 grounding/citation/abstention pipeline.

**Acceptance Criteria:**

- Product answers include evidence from that product's reviews.
- Missing evidence returns abstention.
- Reviews from other products are not used.
- Tests cover supported question, unsupported question, and wrong-product case.
- Repro cases cover grounded QA, unsupported question, and wrong-product answer.

**Dependencies:**

- Depends on A1.1 for grounding/citation/abstention.
- Depends on A2.1 for a trusted product ID from catalog search.

**Reuse / Open-source:**

- Reuse A1.1 grounding pipeline.
- Reuse review data and `fetch_product_reviews`.

### A2.3 - Confirmation-Controlled Cart Actions

**Why:** Add-to-cart is a write action. AI must not change cart state because of a misunderstanding or prompt injection.

**What:** AI may prepare a pending add-to-cart action, but backend performs the write only after valid user confirmation.

**Acceptance Criteria:**

- Cart state does not change before confirmation.
- Confirmation applies only to the correct user, product, and quantity.
- Expired or replayed confirmation cannot create a write.
- AI cannot checkout, empty cart, process payment, or refund.
- Repro cases prove cart is unchanged before confirmation and replay/expired confirmation is rejected.

**Dependencies:**

- Depends on A1.2 for guardrails and tool-scope enforcement.
- Depends on A2.1 for a trusted product ID.

**Reuse / Open-source:**

- Reuse `CartService.AddItem`; do not create a separate cart write path.
- Reuse Valkey for pending action/confirmation state.
- Use Python standard library token/signing logic where sufficient.
- Emit safe audit metadata for cart tool calls and confirmation results.

### OPS-04 - Flag Inventory and Incident Signature Mapping

**Why:** BTC injects incidents through `flagd`. AIOps needs symptoms, severity, and runbook mapping without tampering with the protected flag mechanism.

**What:** Build a flag inventory mapping each current flag to affected service, expected metric/log/trace symptoms, likely SLO impact, and runbook. Prioritize high-risk checkout/cart flags first.

**Acceptance Criteria:**

- High-risk checkout/cart flags are completed first; full P1 deliverable covers all 15 current flags.
- Every high-risk flag maps to at least one metric/log/trace symptom.
- Every high-risk flag has a runbook stub.
- Documentation explicitly says "do not disable flagd."
- Verification uses recorded/synthetic telemetry by default; real flag exercise requires explicit BTC authorization.

**Reuse / Open-source:**

- Use existing `demo.flagd.json` inventory.
- Use OpenSearch logs, Jaeger traces, and Prometheus metrics.
- Focus first on `paymentFailure`, `paymentUnreachable`, `cartFailure`, `kafkaQueueProblems`, `llmRateLimitError`, and `failedReadinessProbe`.

### OPS-07 - Service Topology and Blast-Radius Map

**Why:** Incident triage and RCA are slower without a checked topology that links critical services to metrics, traces, logs, owners, and runbooks.

**What:** Build a minimum checkout-path Mermaid topology first, then enrich it with evidence links and validated SPOF notes.

**Acceptance Criteria:**

- Minimum checkout-path topology is available before full enrichment begins.
- Completed topology map is stored in Markdown with Mermaid.
- Every checkout dependency has metrics, logs/traces, likely failure symptom, owner, and runbook.
- SPOF labels are backed by deployment evidence, not assumptions.
- Map is checked against Jaeger traces and source code.

**Reuse / Open-source:**

- Use Phase 3 architecture and checkout traces.
- Use `traces_span_metrics_*`, `rpc_server_duration_milliseconds_*`, `postgresql_backends`, confirmed Kafka metrics or log fallback, and OpenSearch logs.

### OPS-05 - LLM Observability Dashboard and Alerting

**Why:** The LLM path is best-effort, but it must not break product pages or hide latency, fallback, rate-limit, and inaccurate-response symptoms.

**What:** Observe AI behavior from `product-reviews` first, then add direct gen-ai metrics only after confirming they exist in Prometheus.

**Acceptance Criteria:**

- Dashboard shows AI request volume, product-reviews AI span p95/p99, AI span errors, and flag-related evidence.
- `gen_ai_client_*` availability is documented as `present` or `N/A`.
- Alert fires when `llmRateLimitError` causes AI span errors or fallback behavior.
- AI correctness is linked to AIE evaluation status, not inferred from latency or error rate.

**Reuse / Open-source:**

- Use `app_ai_assistant_counter_total`.
- Use `get_ai_assistant_response` spanmetrics where present.
- Use OpenSearch logs for `llmRateLimitError` and `llmInaccurateResponse`.
- Reuse OpenTelemetry/Grafana/Prometheus.

### A1.3 - Resilience and Cost Optimization

**Why:** LLM is a best-effort dependency. LLM delay or failure must not break product pages, and repeated valid requests should not waste cost.

**What:** Add timeout, fallback, cache for validated responses, and metrics for latency, fallback, cache hit/miss, guardrail failures, and grounding failures.

**Acceptance Criteria:**

- LLM error or timeout returns safe fallback.
- Product page does not fail only because AI dependency fails.
- Only validated responses are cached.
- Metrics cover latency, fallback, cache, and validation result.
- Repro cases cover timeout, rate limit, fallback, and cache behavior.

**Dependencies:**

- Depends on A1.1 because only grounded responses should be cached.
- Depends on A1.2 because guardrail results affect cache and metrics.

**Reuse / Open-source:**

- Reuse Valkey for AI cache.
- Use Tenacity for retry/backoff.
- Use valkey-py for Python Valkey access.
- Reuse OpenTelemetry, Prometheus, and Grafana.

### OPS-06 - Kafka Consumer Lag and Error Alert

**Why:** Checkout can succeed while async accounting/fraud processing lags or fails. TF2 needs visibility into that hidden operational risk.

**What:** Discover Kafka metrics in the target environment, then build lag and producer-failure monitoring from confirmed series or documented log fallback.

**Acceptance Criteria:**

- Dashboard shows Kafka lag by group/topic when confirmed metrics exist.
- Alert states confirmed metric name and labels, or explicitly uses documented log fallback.
- Threshold and duration are approved in an ADR because Phase 3 defines no Kafka lag threshold.
- Runbook covers `accounting`, `fraud-detection`, checkout producer, and `kafkaQueueProblems`.
- Flag exercise requires explicit BTC authorization.

**Reuse / Open-source:**

- Use the configured OpenTelemetry Collector `kafkametrics` receiver where metrics are present.
- Discover metric names with `count by (__name__) ({__name__=~"kafka_.*"})`.
- Use logs for `Failed to write message`, `Failed to send message to Kafka`, and `kafkaQueueProblems`.

### A2.4 - Multi-Turn Conversation and Bounded Orchestration

**Why:** Users will ask follow-up questions using references such as "the first one" or "add that one." The agent needs conversation state, but tool loops must be bounded.

**What:** Use LangGraph for bounded multi-turn/tool-calling orchestration and graph state. Use Mem0 for short-term/session memory to resolve context across turns.

**Acceptance Criteria:**

- System resolves references inside the same conversation.
- LangGraph state stores intermediate results for a user turn without becoming the source of truth over catalog/review data.
- Mem0 short-term memory stores session context and is isolated by user/session.
- Agent has hard limits for rounds, tool calls, and deadline.
- Budget exceeded returns fallback instead of more tool calls.
- Repro cases cover reference resolution, loop limit, and budget exceeded.

**Dependencies:**

- Depends on A2.1 for product references.
- Depends on A2.2 for grounded multi-turn Q&A.
- Depends on A2.3 for safe pending cart actions across turns.

**Reuse / Open-source:**

- Use LangGraph for orchestration, graph state, bounded loops, and tool-calling control flow.
- Use Mem0 for short-term/session memory in MVP.
- Reuse OpenTelemetry/logging for safe metadata on each tool call.

## 5. Proposed Delivery Order

### Phase 1 - P0 Operational Protection and AI Safety Foundation

1. OPS-01 Official Customer-Flow SLO Coverage
2. OPS-03 Checkout Dependency Failure Detection
3. OPS-02 DB Connection Saturation Alert
4. A1.1 Verified Summarization, Grounding, and Citations
5. A1.2 Prompt Injection, PII, and Tool Guardrails

Outcome: TF2 can report and alert on official customer-flow commitments, detect checkout dependency failures faster, protect the known DB saturation risk, and make AI review responses safer before expanding capability.

### Phase 2 - Shopping Copilot MVP and Incident Readiness

1. A2.1 Natural Language Product Discovery
2. A2.2 Review-Grounded Product Q&A
3. A2.3 Confirmation-Controlled Cart Actions
4. OPS-04 Flag Inventory and Incident Signature Mapping
5. OPS-07 Service Topology and Blast-Radius Map
6. OPS-05 LLM Observability Dashboard and Alerting

Outcome: Users can search real catalog products, ask grounded review questions, and prepare cart actions through confirmation, while operations gains stronger flag/runbook/topology coverage and AI-path observability.

### Phase 3 - Resilience, Async Monitoring, and Multi-Turn Hardening

1. A1.3 Resilience and Cost Optimization
2. OPS-06 Kafka Consumer Lag and Error Alert
3. A2.4 Multi-Turn Conversation and Bounded Orchestration

Outcome: AI failures degrade safely, repeated valid responses are cached, async order-processing risk is visible, and multi-turn Copilot behavior is bounded by explicit memory and execution budgets.
