# ADR-DETECT-001 - Mandate 7a Anomaly Detector Architecture

> Status: Proposed, pending reviewer sign-off  
> Owner: Nguyen Quy Hung  
> Reviewers: Pending team review  
> Last updated: 2026-07-15  
> Related docs: `docs/aiops/mandate/MANDATE-07a-detection-analysis.md`

## Summary

For Mandate 7a, we will use the in-repository Python AIOps detector as the first anomaly detection architecture. The detector is lightweight, observe-only, and evaluation-first. It reads existing telemetry-shaped metric series, computes a historical baseline, scores abnormal behavior, and passes evidence into the RCA ranking path.

This ADR does not approve production auto-remediation. It only approves the detector architecture and the documentation/evaluation path required for Mandate 7a review.

## Problem

The team needs a baseline anomaly detection approach that can identify abnormal service behavior and provide root-cause candidates without adding operational risk. The task requires:

1. Code evidence that baseline and detector logic exist.
2. A metrics analysis document covering at least three important service metrics.
3. An ADR explaining the detector architecture and how it integrates with the current AIOps prototype.

The detector must satisfy these constraints:

- Do not slow down user-facing services.
- Do not add a new expensive telemetry or ML cluster.
- Do not interfere with SRE fault injection.
- Do not mutate `flagd`.
- Do not require production deployment for this phase.

## Current Evidence

The current AIOps prototype already contains the relevant runtime pieces:


| Area                    | File                               | Purpose                                                                               |
| ----------------------- | ---------------------------------- | ------------------------------------------------------------------------------------- |
| Runtime config          | `src/aio/config/runtime.json`      | Defines topology, signals, detector ids, thresholds, policy, and RCA enablement.      |
| Baseline helpers        | `src/aio/aiops/anomaly/stats.py`   | Provides median, IQR, standard deviation, and robust score helpers.                   |
| Detector implementation | `src/aio/aiops/anomaly/v001.py`    | Contains EWMA/STL-style residual detection and service-level metric scoring.          |
| RCA engine              | `src/aio/aiops/rca/engine.py`      | Combines topology/graph evidence and metric scores into ranked root-cause candidates. |
| Evaluation runner       | `src/aio/evaluate/e2e_pipeline.py` | Runs anomaly/RCA evaluation on dataset folders and emits incident/RCA metrics.        |


## Decision

Use the Python AIOps detector path already present in `src/aio` as the Mandate 7a detector architecture.

The selected architecture is:

```text
Telemetry or evaluation dataset
  -> MetricSeries normalization
  -> Baseline calculation
  -> Anomaly scoring
  -> RCA ranking
  -> Incident/RCA evidence output
```

The detector will run outside the user request path. For Mandate 7a, the output is evidence for review and evaluation, not an automatic production action.

## Detailed Design

### 1. Input Contract

Detector input is normalized into `MetricSeries` objects. Each series represents one metric for one service.

Expected fields:


| Field       | Meaning                                                                          |
| ----------- | -------------------------------------------------------------------------------- |
| `service`   | Service that owns the metric, for example `checkout` or `payment`.               |
| `metric`    | Metric family/name, for example `latency`, `error`, or `checkout_bad_ratio_24h`. |
| `signal_id` | Stable signal identifier used by detector/RCA output.                            |
| `points`    | Ordered timestamp/value points.                                                  |


The detector should not depend on live production-only objects. It can run against existing telemetry or dataset-shaped CSV input.

### 2. Baseline Calculation

For each metric series, the detector reserves the last two values as a confirmation window and compares both against the earlier historical baseline.

Baseline policy:

```text
confirmation_values = last 2 points
historical_values = all earlier points (minimum 30)
residuals = observed - EWMA trend - optional seasonal component
center = mean(historical_residuals)
spread = max(stddev(historical_residuals), configured_minimum_deviation / z_threshold)
scores = [abs(value - center) / spread for value in confirmation_residuals]
fire = every score exceeds its configured threshold
```

The minimum deviation is configured per signal, so flat ratio baselines remain detectable without embedding metric scale in Python.

Why EWMA/STL residual scoring:

- Maintains a per-service, per-signal adaptive baseline.
- Requires two consecutive abnormal samples to suppress one-point spikes.
- Uses configuration-backed minimum deviations for flat baselines.
- Remains lightweight and does not need a separate model-serving cluster.

### 3. Anomaly Scoring

The selected detector path uses lightweight statistical scoring:


| Method                | Purpose                                                    | Current evidence                 |
| --------------------- | ---------------------------------------------------------- | -------------------------------- |
| EWMA residual scoring | Detect drift/spike in one time series after smoothing.     | `src/aio/aiops/anomaly/v001.py`  |
| Service-level scoring | Combine multiple metric deviations inside one service.     | `src/aio/aiops/anomaly/v001.py`  |
| Isolation Forest scoring | Corroborate multiple aligned metrics inside one service. | `src/aio/aiops/anomaly/v001.py` |
| Adaptive event conversion | Convert confirmed findings into normal incidents, notifications, and runbook routes. | `src/aio/aiops/anomaly/events.py` |


Cross-service ranking uses the checked service topology and repo-native median/IQR robust scores. The current implementation does not contain or claim a BARO/BOCPD detector.

### 4. Runtime Signals And Thresholds

Current enabled configured runtime detectors include:


| Detector                            | Signal                           | Service                     | Threshold | Purpose                                               |
| ----------------------------------- | -------------------------------- | --------------------------- | --------- | ----------------------------------------------------- |
| `ops01_checkout_slo`                | `checkout_bad_ratio_24h`         | checkout                    | `0.01`    | Detect checkout SLO breach.                           |
| `ops03_checkout_payment_dependency` | `checkout_payment_error_rate_5m` | checkout/payment dependency | `0.05`    | Detect checkout failure caused by payment dependency. |
| `ops04_checkout_latency_p95` | `checkout_p95_latency_5m` | checkout | `0.5s` | Detect user-visible checkout latency. |
| `ops06_product_catalog_cpu` | `product_catalog_cpu_millicores` | product-catalog | `50` | Detect catalog saturation. |
| `auto_*_error_rate` | service error ratios | checkout/payment/cart/product-catalog | config-backed | Expand error detection while keeping bounded query scope. |
| `ops07_checkout_fast_burn` | `checkout_burn_rate_fast` | checkout | `14.4` | Fast 5m/1h error-budget burn. |
| `ops08_checkout_slow_burn` | `checkout_burn_rate_slow` | checkout | `6.0` | Slow 30m/6h error-budget burn. |


These thresholds are prototype/evaluation thresholds. They should be reviewed after real incident replay or reviewer feedback.

### 5. RCA Integration

After anomaly scoring, RCA ranking combines:

- Graph/topology evidence from runtime config.
- Metric deviation evidence from scored metric series.
- Service dependency information, for example checkout depending on payment.
- Confirmed SLO/dependency rule evidence when adaptive scoring correctly finds no current deviation; this seeds RCA without creating a second adaptive incident.

The expected output shape follows `src/aio/evaluate/e2e_pipeline.py`:


| Output                    | Meaning                                                         |
| ------------------------- | --------------------------------------------------------------- |
| `predicted_incident`      | Whether detector believes an incident exists.                   |
| `predicted_root_services` | Ranked top-k suspected root-cause services.                     |
| `predicted_root_causes`   | Service plus metric evidence.                                   |
| `rca_top_k_hit`           | Whether expected root cause appears in top-k during evaluation. |


## Options Considered

### Option A: Grafana Machine Learning or managed anomaly detection

Not selected for Mandate 7a.

Pros:

- Less custom detector code.
- Native dashboard integration.

Cons:

- Adds provisioning/access questions.
- May introduce additional cost.
- Harder to keep the first proof fully repo-reviewable.

### Option B: Prometheus-only static alert rules

Not selected as the primary detector architecture.

Pros:

- Simple and familiar.
- Good for fixed SLO thresholds.

Cons:

- Weak for RCA ranking.
- Harder to compare metric deviations across services.
- Does not fully satisfy the need for detector/RCA evidence.

### Option C: In-repository Python AIOps detector

Selected.

Pros:

- Already exists in the prototype.
- Lightweight and reviewable.
- Runs offline on datasets.
- Does not require new infra.
- Can output RCA evidence, not only alert/no-alert.

Cons:

- Thresholds need tuning.
- Production use still needs a separate live-readiness decision.
- Reviewer sign-off is required before the ADR becomes accepted.

## Safety And Non-Goals

This ADR explicitly does not approve:

- Production auto-remediation.
- Mutation of Kubernetes resources.
- Mutation of `flagd` configuration or fault-injection state.
- Inline execution on the application request path.
- Adding a new telemetry or ML cluster.

Required safety behavior:

- Detector runs as AIOps-side logic.
- Detector output is recommendation/evidence until sign-off.
- Any future automatic action must go through remediation safety policy and a separate approval path.

## Verification Plan

Before this ADR is marked accepted, attach or reference:

1. Metrics analysis doc with at least three user-impact metrics.
2. Code/PR/commit link showing baseline and detector logic.
3. Evaluation command and output from the current detector/RCA path.
4. Reviewer comment approving this architecture.

Suggested local evaluation command, when dependencies are available:

```bash
cd src/aio
python -B evaluate/e2e_pipeline.py --labels path/to/reviewer-labels.json --out evaluate/report.json
```

If the team uses the `capstone` conda environment, run the same command through `conda run -n capstone`.

## Rollout Plan

Phase 1: Documentation and review

- Complete metrics analysis.
- Review this ADR.
- Capture reviewer sign-off.

Phase 2: Offline evaluation

- Run detector/RCA against available datasets.
- Save output as evidence.
- Tune prototype thresholds only if reviewer requests it.

Phase 3: Future production readiness

- Create separate live-readiness ADR.
- Define alert ownership and rollback.
- Confirm SLI approval.
- Confirm remediation safety gates.

## Reviewer Checklist

- The selected detector path is clear.
- The detector does not depend on `flagd`.
- The detector does not mutate production state.
- Baseline calculation is documented.
- RCA integration is documented.
- Thresholds are identified as prototype/evaluation thresholds.
- Required evidence is attached or linked.

## Reviewer Sign-Off


| Reviewer      | Area                        | Decision       | Evidence link/comment  | Date    |
| ------------- | --------------------------- | -------------- | ---------------------- | ------- |
| team reviewer | AIOps detector architecture | Pending review | Pending review comment | Pending |


## Consequences

Positive outcomes:

- Mandate 7a has a reviewable detector architecture.
- The approach reuses current AIOps prototype code.
- The detector remains lightweight and observe-only for this phase.
- RCA output can explain which service/metric looks suspicious.

Tradeoffs:

- Prototype thresholds may need tuning after incident replay.
- This does not replace official SLO alerting.
- Production deployment and auto-remediation still need separate approval.

