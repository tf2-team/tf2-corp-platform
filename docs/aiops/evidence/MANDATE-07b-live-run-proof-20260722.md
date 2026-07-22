# AI MANDATE #7b - Detection Live Run Proof

## Summary

This file is the Jira-ready proof for `AI MANDATE #7b`: the AIOps detector was run against live Prometheus telemetry during a controlled `local-paymentFailure` fault window, produced a visible SEV1 detector event, opened an incident, ran RCA, and selected the safe `page_oncall` dry-run/fallback action.

## Live E2E Run

| Field | Value |
| --- | --- |
| Environment | `techx-corp-prod` |
| Scenario | `local-paymentFailure` |
| Fault percentage | `50%` |
| Expected affected flow | `checkout` |
| Expected affected dependency | `payment` |
| Detector run ID | `aio-e2e-20260722T090200Z-3c4d7fba` |
| Detector status | `passed` |
| Raw JSON artifact | `src/aio/evidence/e2e/aio-e2e-20260722T090200Z-3c4d7fba.json` |
| Existing evidence note | `docs/aiops/evidence/live-detector-evaluation-20260722.md` |

## Timeline

| Event | Timestamp |
| --- | --- |
| Baseline captured before flag | `2026-07-22T15:54:14+07:00` |
| Fault flag enabled | `2026-07-22T15:56:31+07:00` |
| Detector run started | `2026-07-22T16:02:00+07:00` |
| Detector event timestamp | `2026-07-22T16:02:00+07:00` |
| Detector run completed | `2026-07-22T16:02:27+07:00` |
| Fault flag disabled | `2026-07-22T16:03:18+07:00` |

Lead time:

```text
16:02:00 - 15:56:31 = approximately 5m29s
```

The earlier evidence note uses the rounded pipeline timestamp `16:02:12`, which gives approximately `5m40s`. Both refer to the same live detector run window.

## Detector Fired

| Field | Value |
| --- | --- |
| Incident ID | `inc-5f29f7eb7852` |
| Detector | `ops01_checkout_slo` |
| Service | `checkout` |
| Flow | `checkout` |
| Severity | `SEV1` |
| Signal | `checkout_bad_ratio_24h` |
| Value | `0.04876776979910119` |
| Threshold | `0.01` |
| Reason | `threshold_breached` |
| Quality | `verified` |
| Runbook | `RB-CHECKOUT-SLO` |

Terminal/log proof from the JSON report:

```text
status=passed
incident_id=inc-5f29f7eb7852
detector=ops01_checkout_slo
service=checkout
severity=SEV1
signal=checkout_bad_ratio_24h
value=0.04876776979910119
threshold=0.01
reason=threshold_breached
```

## RCA And Action

| Field | Value |
| --- | --- |
| RCA candidate service | `checkout` |
| RCA score | `0.75` |
| RCA metric | `trace_failure` |
| Notification summary | `threshold_breached on checkout_bad_ratio_24h; likely root cause: checkout (trace_failure)` |
| Selected action | `page_oncall` |
| Remediation result | `fallback-page-oncall` |
| Policy result | `dry-run-recorded` |
| Live mutation | None |

This satisfies the safety constraint: the detector observes telemetry and records the safe on-call action path; it does not mutate production state or `flagd`.

## Acceptance Criteria From Live Artifact

| Criterion | Result | Evidence |
| --- | --- | --- |
| Incident from real metrics | Passed | Incident `inc-5f29f7eb7852`; verified signals `checkout_bad_ratio_24h`, `checkout_payment_error_rate_5m` |
| RCA returns root cause candidates | Passed | Candidate service `checkout`; `9` metric series; `32409` range samples |
| Remediation is dry-run or page-oncall | Passed | Policy `dry-run-recorded`; selected action `page_oncall`; result `fallback-page-oncall` |
| Report exists for run | Passed | JSON has run ID, timestamps, and pipeline result |

## Precision, Recall, And Lead Time

Measurement source:

| Field | Value |
| --- | --- |
| Labeled dataset report | `src/aio/evaluate/current_pipeline_report.json` |
| Labeled cases | `120` |
| Incident precision | `1.0` (`120 TP`, `0 FP`) |
| Incident recall | `1.0` (`120 TP`, `0 FN`) |
| Incident F1 | `1.0` |
| RCA top-k hit rate | `0.85` (`102 TP`, `18 FN`) |
| RCA top-k precision | `0.1716666667` |
| RCA top-k recall | `0.8583333333` |
| Live lead time | approximately `5m29s` to `5m40s` for the `local-paymentFailure` run |

Important caveat: `dataset/label.json` reports `normal_case_count = 0`, so the labeled replay set is strong evidence for incident recall and RCA hit-rate, but it does not fully measure normal-period false positives. The live `#7b` ticket should keep this caveat visible instead of overstating precision.

## Reproduce

Run from `src/aio` after the approved fault window is active and Prometheus port-forwarding is available:

```powershell
cd C:\Users\AdminPC\Downloads\projectx-brain\Aio_v2\tf2-corp-platform\src\aio
.\.venv\Scripts\python.exe -B scripts\run_prometheus_e2e.py --env-file .env.live
```

Expected passing output when the incident window is present:

```json
{
  "run_id": "aio-e2e-20260722T090200Z-3c4d7fba",
  "status": "passed",
  "report": "evidence\\e2e\\aio-e2e-20260722T090200Z-3c4d7fba.json",
  "acceptance_criteria": {
    "incident_from_real_metrics": true,
    "rca_returns_root_cause_candidates": true,
    "remediation_is_dry_run_or_page_oncall": true,
    "report_exists_for_run": true
  }
}
```

## Fresh Rerun Note

I reran the same command on `2026-07-22T20:05:46+07:00` after the fault was no longer active:

```text
run_id=aio-e2e-20260722T130546Z-43bffd3a
status=failed
report=evidence\e2e\aio-e2e-20260722T130546Z-43bffd3a.json
incident_from_real_metrics=false
rca_returns_root_cause_candidates=false
remediation_is_dry_run_or_page_oncall=true
report_exists_for_run=true
```

The rerun still proves the detector command executes live and writes evidence, but it is not the `#7b` acceptance artifact because the telemetry window showed missing checkout/payment signals instead of the injected payment failure. Use `aio-e2e-20260722T090200Z-3c4d7fba` as the passing live-run proof.

## Jira Paste Block

```text
AI MANDATE #7b proof:
- Live detector run: src/aio/evidence/e2e/aio-e2e-20260722T090200Z-3c4d7fba.json
- Evidence markdown: docs/aiops/evidence/MANDATE-07b-live-run-proof-20260722.md
- Repro: cd src/aio; .\.venv\Scripts\python.exe -B scripts\run_prometheus_e2e.py --env-file .env.live
- Scenario: local-paymentFailure at 50%, checkout/payment flow
- Detector fired: ops01_checkout_slo, service=checkout, severity=SEV1, signal=checkout_bad_ratio_24h, value=0.04876776979910119, threshold=0.01
- Incident: inc-5f29f7eb7852
- RCA: checkout, score=0.75, metric=trace_failure
- Action: page_oncall, dry-run-recorded/fallback-page-oncall, no live mutation and no flagd mutation
- Live lead time: approximately 5m29s to 5m40s from flag enable to detector fire
- Measurement: current_pipeline_report.json, 120 labeled cases, incident precision=1.0, recall=1.0, F1=1.0; RCA top-k hit=0.85
- Caveat: replay dataset has no normal cases, so keep FP/normal-period precision caveat visible.
```
