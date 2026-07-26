# AI MANDATE #7b - Live Detection + Measurement

## Context

Mandate #7b is the live-evidence stage. After #7a proves detector implementation and baseline analysis, #7b shows that the detector actually fires during injected / approved replayed incidents and reports detection quality over a labeled incident set.

## Planned Detection Flow

```text
Live telemetry or labeled replay
 -> metric collection
 -> baseline and anomaly scoring
 -> incident detection
 -> RCA ranking
 -> alert/log/dashboard evidence
 -> precision/recall/lead-time report
```

Use the #7a core metrics for the first reproducible #7b run:

- checkout p95 latency
- cart HTTP 5xx / error-rate
- saturation substitute: checkout memory RCA

Note: product-catalog/ad CPU saturation was attempted, but the CPU fault did not materialize clearly enough in the live run. The submitted saturation evidence is checkout memory RCA, and this caveat is documented in the report.

## Required Evidence

Evidence pack:

- `tf2-corp-platform/src/aio/docs/mandates/7b/`
- Main report: `tf2-corp-platform/src/aio/docs/mandates/7b/MANDATE-07b-api-runtime-draft.md`
- Dataset: `tf2-corp-platform/src/aio/evaluate/dataset/mandate7b_live/`
- State stores: `tf2-corp-platform/src/aio/state/7b/`

Visible proof:

| Scenario | Evidence |
| --- | --- |
| S2 cart error | `s2-rerun-04-detector-fired.png`, `s2-rerun-04b-dedup-rca.png`, `s2-rerun-08-fault-capture-cli.png` |
| S5 checkout p95 | `s5-08-detector-fired-log.png`, `s5-09-fault-checkout-p95-spike.png`, `s5-16-dump-final-cli.png` |
| S4 checkout memory | `s4-rerun-04-detector-rca-checkout-memory.png`, `s4-rerun-04c-discord-alert-checkout-memory.png` |
| S3 burn-rate / no-spam | `18g-burn-rate-detector-fired-incident-notification.png`, `18h-burn-rate-dedup-same-incident-occurrence2.png`, `18j-burn-rate-final-incident-api-occurrence3.png` |

## Evidence Must Include

| Required field | Submitted value |
| --- | --- |
| Incident scenario name | L1 Cart HTTP error-rate, L2 Checkout p95 latency, L3 Checkout memory saturation substitute |
| Incident start timestamp | Captured in scenario meta / screenshots: `s2-rerun-meta.txt`, `s5-checkout-p95-meta.txt`, `s4-rerun-meta.txt` |
| Detector fire timestamp | Captured in detector logs / incident screenshots listed above |
| Metrics that triggered detector | `cart_error_rate`, `checkout_latency_p95`, `checkout_memory_usage_bytes`, supplemental `checkout_error_budget_burn_rate_24h` |
| Severity | Captured in detector incident output; labeled incidents are submitted as active detector fires |
| Root-cause candidates | Cart, checkout latency, checkout memory RCA; burn-rate identifies checkout SLO impact |
| Reproduction command / runbook | See runbook section below |

## Measurement Plan

| Metric | Formula | Required source | Result |
| --- | --- | --- | --- |
| Precision | correct detector fires / total detector fires | Detector output + incident labels | 9/11 = 81.8% using mandate-style TP + same-fault related scoring |
| Recall | caught labeled incidents / total labeled incidents | Labeled incident set | 3/3 = 100% |
| Lead-time | detector fire timestamp - incident start timestamp | Injection timestamp or replay label | Mean ~287s |

## Labeled Set Results

| Scenario | Primary incident | Trigger | Lead-time | Result |
| --- | --- | --- | --- | --- |
| L1 Cart HTTP error-rate | `inc-533e7f658c8f` | `local-cartFailure` -> `auto_cart_error_rate` | 212s | Caught |
| L2 Checkout p95 latency | `inc-97d2a7043a2b` | `local-cartFailure` isolated run -> `auto_checkout_latency_p95` | 322s | Caught |
| L3 Checkout memory saturation substitute | `inc-788d322c0b2f` | attempted `local-adHighCpu`; final RCA is checkout memory | 328s | Caught |

## Also Report

| Item | Result |
| --- | --- |
| False positives | 2 residual FP in the labeled K=3 stores after pruning unrelated detector/RCA noise |
| False negatives | 0 in K=3 |
| Duplicate / spam behavior | Burn-rate produced one incident fingerprint with `occurrence_count` 1 -> 2 -> 3+, not new incident spam |
| RCA top-k result | Expected root / affected cause appears in labeled cases; S4 documented as checkout memory RCA substitute |

## Proposed Execution Steps

1. Confirmed live / replay source for checkout p95, cart HTTP error-rate, and saturation substitute.
2. Confirmed detector queries and units through captured runtime output and scenario evidence.
3. Captured normal baseline periods and no-alert / empty incident evidence.
4. Injected approved Flagd incidents.
5. Saved detector output, incident API dumps, screenshots, and timestamps.
6. Ran measurement over labeled incident set K=3.
7. Attached precision, recall, lead-time, false-positive notes, spam-control notes, and reproduction steps.

## Reproduction Command / Runbook

Working directory:

```text
tf2-corp-platform/src/aio
```

Runtime:

```text
python -m uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540
```

Per scenario:

1. Set per-scenario state paths with `AIOPS_STATE_STORE_PATH`, `AIOPS_RCA_HISTORY_PATH`, and `AIOPS_REMEDIATION_AUDIT_PATH`.
2. Capture normal / baseline period and confirm no incident.
3. Toggle approved Flagd incident:
   - S2/S5: `local-cartFailure`
   - S3: `local-paymentFailure` at 50% -> 75% -> 100%
   - S4: attempted `local-adHighCpu`; submitted result uses checkout memory RCA
4. Capture detector output, incident API dump, dashboard screenshots, and final incident JSON.
5. Use the report and dataset above for metric calculation.

## Evidence To Attach

| Item | Status |
| --- | --- |
| Alert screenshot or detector log | Done: see S2/S5/S4/S3 evidence files above |
| Reproduction command / runbook | Done: included above and in main report |
| Labeled incident set or replay source | Done: `evaluate/dataset/mandate7b_live/` |
| Normal-period no-alert evidence | Done: S2/S5/S3/S4 baseline screenshots and captures |
| Precision | Done: 9/11 = 81.8% |
| Recall | Done: 3/3 = 100% |
| Lead-time | Done: mean ~287s |
| False-positive / spam-control notes | Done: 2 FP in K=3; burn-rate dedup/no-spam shown |
| RCA top-k result | Done: expected root / affected cause appears in labeled cases |

## Scope Notes

This ticket proves live detection and measurement. It does not approve production auto-remediation or any mutating live executor action.

The detector runs in dry-run mode, does not add user-facing latency, does not require a heavy new cluster, and does not disable or mutate the Flagd incident mechanism.

## Status

PASS for #7b live evidence on the submitted scope: detector fired end-to-end, labeled-set metrics were measured, burn-rate/no-spam behavior was shown, and reproduction paths are documented.
