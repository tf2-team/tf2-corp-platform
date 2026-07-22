# Evidence Corroboration and Trace RCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corroborate non-hard metric anomalies with bounded log/trace failure evidence and allow the earliest upstream failing trace span to influence RCA.

**Architecture:** Extend the existing `Enricher` with one structured corroboration method and reuse the configured Jaeger/OpenSearch clients. The pipeline adjusts anomaly scores before RCA; `V001RcaEngine` accepts trace-root evidence as an optional input and keeps existing rankers as fallback.

**Tech Stack:** Python 3.11, Pydantic, existing HTTP integrations, `unittest`, conda env `capstone`.

## Global Constraints

- Evidence window is exactly 900 seconds.
- No new dependency or collector.
- Hard failures are error rate/error ratio, OOM, and decreasing ready pods.
- Missing failure evidence multiplies non-hard confidence by 0.50.
- One failure source adds 0.15; both log and trace add 0.30; confidence is capped at 1.0.
- Unconfigured or failed integrations preserve metric confidence.
- Latency-only spans cannot become root causes.

---

### Task 1: Structured Corroboration Evidence

**Files:**
- Modify: `aio/aiops/schemas/domain.py`
- Modify: `aio/aiops/schemas/__init__.py`
- Modify: `aio/aiops/enrichment/enricher.py`
- Test: `aio/tests/test_enrichment.py`

**Interfaces:**
- Consumes: `list[AnomalyFinding]`, configured Jaeger/OpenSearch clients, `window_seconds: int`.
- Produces: `Enricher.corroborate(findings, window_seconds) -> dict[str, TelemetryCorroboration]`.
- `TelemetryCorroboration` fields: `service`, `available_sources`, `log_failure`, `trace_failure`, `trace_root_service`, `trace_failure_timestamp`, `trace_reference`.

- [ ] **Step 1: Write failing enrichment tests**

Add fake-client tests proving the OpenSearch query contains a 900-second range plus failure-only terms, error traces expose the earliest failing service, latency-only traces do not set `trace_failure`, and client exceptions mark a source unavailable.

```python
evidence = enricher.corroborate([finding(timestamp=1000)], window_seconds=900)["checkout"]
self.assertEqual(evidence.available_sources, {"log", "trace"})
self.assertTrue(evidence.log_failure)
self.assertEqual(evidence.trace_root_service, "payment")
self.assertEqual(jaeger.calls[0]["start"], 100 * 1_000_000)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
conda run -n capstone python -m unittest tests.test_enrichment
```

Expected: failure because `TelemetryCorroboration` and `Enricher.corroborate` do not exist.

- [ ] **Step 3: Add the schema and bounded queries**

```python
class TelemetryCorroboration(AiopsModel):
    service: str
    available_sources: set[str] = Field(default_factory=set)
    log_failure: bool = False
    trace_failure: bool = False
    trace_root_service: str | None = None
    trace_failure_timestamp: int | None = None
    trace_reference: str | None = None
```

Implement one query per affected service. OpenSearch uses a service filter, timestamp range, and failure terms. Jaeger inspects spans for `error=true`, OTel `status.code=ERROR`, HTTP status `>=500`, or timeout text; it returns the earliest failing span. Exceptions omit the failed source from `available_sources`.

- [ ] **Step 4: Run enrichment tests and verify GREEN**

Run the command from Step 2. Expected: all `test_enrichment` tests pass.

---

### Task 2: Confidence Gate in Runtime

**Files:**
- Modify: `aio/config/hyperparameters.json`
- Modify: `aio/aiops/pipeline/runtime.py`
- Test: `aio/tests/test_runtime_pipeline.py`
- Test: `aio/tests/test_settings.py`

**Interfaces:**
- Consumes: Task 1 corroboration and prepared detector series.
- Produces: adjusted `list[AnomalyFinding]` and corroboration passed to RCA.

- [ ] **Step 1: Write failing confidence tests**

Cover hard failure unchanged, one-source bonus, dual-source bonus, successful empty evidence multiplying by 0.50, unavailable integrations preserving confidence, and decreasing ready pods treated as hard.

```python
self.assertEqual(adjusted_error.score, original_error.score)
self.assertEqual(adjusted_cpu_with_trace.score, 0.65)
self.assertEqual(adjusted_cpu_without_failure.score, 0.25)
self.assertEqual(adjusted_cpu_when_unavailable.score, 0.50)
```

- [ ] **Step 2: Run runtime tests and verify RED**

```bash
conda run -n capstone python -m unittest tests.test_runtime_pipeline tests.test_settings
```

Expected: failure because the gate and hyperparameters are absent.

- [ ] **Step 3: Implement score adjustment and pipeline wiring**

Add under `rca.anomaly`:

```json
"evidence_window_seconds": 900,
"no_evidence_multiplier": 0.5,
"single_evidence_bonus": 0.15,
"dual_evidence_bonus": 0.3
```

In `_run_v001_rca`, call `self.enricher.corroborate` after anomaly evaluation. Preserve findings when no source is available; otherwise apply the configured bonus or multiplier. Determine ready-pod direction from the matching detector series baseline and finding timestamp. Pass corroboration to `V001RcaEngine.rank`.

- [ ] **Step 4: Run runtime tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

---

### Task 3: Trace-Based RCA Candidate

**Files:**
- Modify: `aio/aiops/rca/engine.py`
- Test: `aio/tests/test_v001_anomaly_rca.py`

**Interfaces:**
- Consumes: `V001RcaEngine.rank(..., corroboration: dict[str, TelemetryCorroboration] | None = None)`.
- Produces: ordinary `RcaResult`; a valid trace root may include `trace_failure` in `root_cause_metrics`.

- [ ] **Step 1: Write failing RCA tests**

Prove an upstream trace error can nominate a topology service without its own metric anomaly, the earliest failing span wins, an unknown/off-path service is rejected, and latency-only evidence does not change RCA.

```python
result = engine.rank(findings, series, top_k=5, corroboration={"checkout": trace_evidence("payment")})
self.assertEqual(result.root_causes[0].service, "payment")
self.assertIn("trace_failure", result.root_causes[0].root_cause_metrics)
```

- [ ] **Step 2: Run RCA tests and verify RED**

```bash
conda run -n capstone python -m unittest tests.test_v001_anomaly_rca
```

Expected: failure because `rank` does not accept corroboration.

- [ ] **Step 3: Add trace evidence to existing ranking**

Validate the trace root against `RuntimeConfig.topology`, confirm it is the affected service or a transitive dependency, and add one synthetic root finding with affected anomaly confidence and failure timestamp. Reuse graph/RRF ranking; do not add a fourth ranker.

- [ ] **Step 4: Run RCA tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

---

### Task 4: Full Regression Verification

**Files:**
- Modify only files required by failures caused by Tasks 1-3.

- [ ] **Step 1: Run full suite**

```bash
conda run -n capstone python -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

```bash
python -m json.tool config/hyperparameters.json >/dev/null
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Review final diff**

Confirm queries are bounded, integration failures preserve confidence, raw log/trace payloads are not persisted, and no dependency was added.
