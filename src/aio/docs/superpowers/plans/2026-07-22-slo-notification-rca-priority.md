# SLO Notification and RCA Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify on every configured latency or error-rate SLO breach and use that breach as the primary RCA impact signal.

**Architecture:** Reuse existing threshold detectors, incident storage, deduplication, and notification delivery. Convert threshold-breach incidents into impact findings, exclude both latency and error rate from root-cause metrics, retain error rate as a hard-failure gate, and correlate candidates against every breached SLO impact series.

**Tech Stack:** Python 3.11, Pydantic models, `unittest`, JSON runtime configuration, conda env `capstone`.

## Global Constraints

- Latency and error rate remain impact signals and never appear in `root_cause_metrics`.
- Error rate remains a hard-failure gate.
- Existing evidence corroboration, deduplication, and normal-growth suppression behavior remains unchanged.
- Add no dependency or new abstraction.

---

### Task 1: SLO Threshold Notifications

**Files:**
- Modify: `aio/config/runtime.json`
- Modify: `aio/tests/test_runtime_config.py`
- Test: `aio/tests/test_prod_simulation.py`

**Interfaces:**
- Consumes: existing `build_detectors(...)` and `AiopsPipeline.run_once(...)`.
- Produces: enabled `ops04_checkout_latency_p95` and `auto_*_error_rate` threshold detectors.

- [x] **Step 1: Write failing behavior tests**

Add production-pipeline tests that submit `checkout_p95_latency_5m=16.0` and `payment_error_rate_5m=0.2`, then assert notification runbooks `RB-CHECKOUT-LATENCY` and `RB-SERVICE-ERROR-RATE`. Update the runtime-config expectation so these detector IDs must be built and every `auto_*_error_rate` detector must be enabled.

- [x] **Step 2: Verify RED**

Run:

```bash
conda run -n capstone python -m unittest tests.test_runtime_config tests.test_prod_simulation
```

Expected: FAIL because the latency and automatic error-rate detectors are currently disabled.

- [x] **Step 3: Enable existing detectors**

Set `enabled` to `true` for `ops04_checkout_latency_p95` and every detector whose ID matches `auto_*_error_rate` in `aio/config/runtime.json`. Leave duplicate legacy detector `ops05_cart_error_rate` disabled.

- [x] **Step 4: Verify GREEN**

Run the Task 1 test command and expect all tests to pass.

---

### Task 2: SLO Breaches as RCA Impact Findings

**Files:**
- Modify: `aio/aiops/pipeline/runtime.py`
- Modify: `aio/aiops/rca/engine.py`
- Test: `aio/tests/test_runtime_pipeline.py`
- Test: `aio/tests/test_v001_anomaly_rca.py`

**Interfaces:**
- Consumes: `Incident.events`, `CandidateEvent.reason`, `CandidateEvent.signal_id`, and existing `AnomalyFinding`.
- Produces: `_slo_impact_findings(incidents: list[Incident]) -> list[AnomalyFinding]`; `V001RcaEngine._correlation_scores(..., impact_series=...)` accepts all series for primary-impact selection.

- [x] **Step 1: Write failing RCA tests**

Add one pipeline test proving a threshold-breach incident becomes an RCA anomaly even if anomaly algorithms do not flag it. Add one RCA test with checkout latency as the impact series and payment CPU as a correlated candidate; assert payment evidence contains `correlation_score=1.000` and latency is absent from root-cause metrics.

- [x] **Step 2: Verify RED**

Run:

```bash
conda run -n capstone python -m unittest tests.test_runtime_pipeline tests.test_v001_anomaly_rca
```

Expected: FAIL because incidents are not converted into RCA findings and latency is excluded before primary-series selection.

- [x] **Step 3: Add minimal impact conversion**

In `AiopsPipeline._run_v001_rca`, derive one `AnomalyFinding(algorithm="slo_threshold", score=1.0)` per unique threshold-breached latency/error-rate signal. Include these findings when collecting corroboration, then prepend them to corroborated anomaly findings so the SLO breach wins equal-score primary selection.

- [x] **Step 4: Use all series only for primary impact selection**

Keep `rca_series` context-free for candidate ranking. Pass the full series list only to `_primary_series`, then calculate correlations against the existing context-free `rca_series` list.

- [x] **Step 5: Verify GREEN and regressions**

Run:

```bash
conda run -n capstone python -m unittest tests.test_runtime_pipeline tests.test_v001_anomaly_rca
conda run -n capstone python -m unittest discover -s tests -p 'test_*.py'
python -m json.tool config/runtime.json
git diff --check
```

Expected: all tests pass, JSON is valid, and no whitespace errors are reported.

---

### Task 3: Separate SLO Impact from Root Cause

**Files:**
- Modify: `aio/aiops/rca/engine.py`
- Test: `aio/tests/test_v001_anomaly_rca.py`

**Interfaces:**
- Consumes: existing `slo_threshold` findings and `MetricSeries.signal_id`.
- Produces: `_is_context_metric(...)` classifies latency and error rate as impact-only; `_correlation_scores(...)` uses all matching SLO impact series.

- [x] **Step 1: Write failing RCA tests**

Change the existing context-metric test to include CPU and require `root_cause_metrics == ["cpu_millicores"]`. Keep the busy-infra hard-failure test but require error rate to be absent from its returned metrics. Add a dual-impact test where checkout latency correlates with payment CPU and checkout error rate correlates with cart CPU; require both candidates to report `correlation_score=1.000`.

- [x] **Step 2: Verify RED**

Run:

```bash
conda run -n capstone python -m unittest tests.test_v001_anomaly_rca
```

Expected: FAIL because error rate is still a root-cause metric and correlation currently selects only one primary impact series.

- [x] **Step 3: Exclude error rate from root cause while retaining the gate**

Extend `_is_context_metric` to return true for `_is_error_metric(metric)`. Do not change `_hard_failure`, `_is_error_metric`, or `_failure_signal_increased`.

- [x] **Step 4: Correlate against every breached SLO impact series**

In `_correlation_scores`, collect series matching findings whose algorithm is `slo_threshold`. For each RCA candidate metric, use the maximum absolute Pearson score across those impact series. Fall back to the existing single primary selection when no SLO finding has a matching series.

- [x] **Step 5: Verify GREEN and regressions**

Run:

```bash
conda run -n capstone python -m unittest tests.test_v001_anomaly_rca
conda run -n capstone python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

Expected: all tests pass and no whitespace errors are reported.

---

### Task 4: Close SLO-only RCA and Notification Gaps

**Files:**
- Modify: `aio/aiops/pipeline/runtime.py`
- Modify: `aio/aiops/rca/engine.py`
- Modify: `aio/aiops/storage/sqlite.py`
- Modify: `aio/aiops/integrations/http.py`
- Modify: `aio/aiops/integrations/prometheus.py`
- Modify: `aio/aiops/config/settings.py`
- Test: `aio/tests/test_runtime_pipeline.py`
- Test: `aio/tests/test_v001_anomaly_rca.py`
- Test: `aio/tests/test_integrations.py`

**Interfaces:**
- Consumes: existing SLO incidents, drift thresholds, pending notification outbox, and `Settings`.
- Produces: drift-seeded RCA candidates for latency/error-rate SLO-only incidents, RCA-enriched pending notifications, and configurable Prometheus timeout.

- [x] **Step 1: Write failing regression tests**

Require `checkout_bad_ratio_24h` to stay outside `slo_threshold`, require a significant payment CPU drift to become RCA evidence when the only finding is an SLO impact, require the checkout notification summary to include the RCA service and metric, and require Prometheus to use `prometheus_timeout_seconds=30`.

- [x] **Step 2: Verify RED**

Run:

```bash
conda run -n capstone python -m unittest tests.test_runtime_pipeline.RuntimePipelineTest.test_bad_ratio_slo_incident_is_added_to_rca_anomalies tests.test_v001_anomaly_rca.V001AnomalyRcaTest.test_rca_uses_significant_drift_when_only_slo_impact_exists tests.test_runtime_pipeline.RuntimePipelineTest.test_pipeline_adds_rca_root_incident_when_slo_incident_exists_for_different_service tests.test_integrations.IntegrationClientTest.test_prometheus_uses_configured_timeout
```

Expected: FAIL on all four missing behaviors.

- [x] **Step 3: Implement the minimum shared fixes**

Keep SLO impact conversion limited to latency/error-rate signals. Reuse `_drift_metrics` to seed root findings only when an SLO impact exists and normal anomaly findings are absent. Update current pending SLO messages after RCA. Pass the Prometheus-specific timeout setting through the existing HTTP client.

- [x] **Step 4: Verify GREEN and regressions**

Run the targeted command from Step 2, then:

```bash
conda run -n capstone python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

Expected: all tests pass and no whitespace errors are reported.
