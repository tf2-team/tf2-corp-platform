# Live Detector Evaluation Evidence - local-paymentFailure

## Summary

This run validates detector evaluation against live product telemetry collected from Prometheus during a controlled `local-paymentFailure` fault injection.

## Scenario

| Field | Value |
| --- | --- |
| Environment | techx-corp-prod |
| Fault flag | local-paymentFailure |
| Fault percentage | 50% |
| Expected affected flow | checkout |
| Expected affected dependency | payment |
| Evidence report | `src/aio/evidence/e2e/aio-e2e-20260722T090200Z-3c4d7fba.json` |

## Timeline

| Event | Timestamp |
| --- | --- |
| Before flag baseline captured | 2026-07-22T15:54:14.1788235+07:00 |
| Flag enabled | 2026-07-22T15:56:31.7860728+07:00 |
| Pipeline detector run | 2026-07-22T16:02:12+07:00 |
| Flag disabled | 2026-07-22T16:03:18.5995190+07:00 |

Approximate detector lead time:

```text
16:02:12 - 15:56:31 = ~5m40s
```

## Command

```powershell
cd C:\Users\AdminPC\Downloads\projectx-brain\Aio_v2\tf2-corp-platform\src\aio
.\.venv\Scripts\python.exe -B scripts\run_prometheus_e2e.py --env-file .env.live
```

## Pipeline Result

| Field | Value |
| --- | --- |
| Run ID | aio-e2e-20260722T090200Z-3c4d7fba |
| Status | passed |
| Incident ID | inc-5f29f7eb7852 |
| Detector | ops01_checkout_slo |
| Service | checkout |
| Severity | SEV1 |
| Signal | checkout_bad_ratio_24h |
| Value | 0.04876776979910119 |
| Threshold | 0.01 |
| Reason | threshold_breached |

## RCA Result

| Field | Value |
| --- | --- |
| Root cause service | checkout |
| Score | 0.75 |
| Root cause metric | trace_failure |

Note: the injected flag targets payment behavior, but this live run fired the checkout SLO detector (`checkout_bad_ratio_24h`). RCA ranked checkout from trace evidence for this run. The detector evaluation still passes because the acceptance goal is incident detection from real metrics.

## Acceptance Criteria

| Criterion | Result | Details |
| --- | --- | --- |
| Incident from real metrics | passed | Incident `inc-5f29f7eb7852`; verified signals `checkout_bad_ratio_24h`, `checkout_payment_error_rate_5m` |
| RCA returns root cause candidates | passed | Candidate service `checkout`; 9 metric series; 32409 range samples |
| Remediation is dry-run or page-oncall | passed | Selected `page_oncall`; result `fallback-page-oncall`; policy `dry-run-recorded` |
| Report exists for run | passed | JSON report contains run ID, timestamps, and pipeline result |

## Screenshot Checklist

Attach the following screenshots with this evidence:

| Screenshot | Purpose |
| --- | --- |
| Grafana before flag, 15:40-15:56 | Shows payment/checkout baseline before injection |
| Flag UI off before/after run | Shows `local-paymentFailure` disabled after the test |
| Grafana during incident, 15:56-16:03 | Shows payment error ratio / checkout SLO breach during injection |
| Terminal output | Shows `status=passed` and `run_id=aio-e2e-20260722T090200Z-3c4d7fba` |
| Grafana after recovery, 16:03-16:15 | Shows metrics recovering after flag was disabled |
