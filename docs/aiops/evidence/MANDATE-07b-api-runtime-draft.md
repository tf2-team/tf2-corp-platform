# AI MANDATE #7b - API Runtime Live Detection Draft

## Summary

This is the draft evidence for `AI MANDATE #7b` using the long-running AIOps API runtime instead of only the one-shot Prometheus E2E runner.

The AIOps runtime is started through FastAPI/Uvicorn:

```powershell
cd C:\Users\AdminPC\Downloads\projectx-brain\Aio_v2\tf2-corp-platform\src\aio
.\.venv\Scripts\uvicorn.exe aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540
```

Runtime entrypoint:

```text
src/aio/aiops/api/app.py
```

When `AIOPS_AUTO_RUN_ENABLED=true`, the API runtime runs the live pipeline repeatedly. Each cycle reads live Prometheus telemetry, evaluates detectors, deduplicates incidents, runs RCA/enrichment when available, and records a safe remediation decision.

## Runtime Configuration

| Field | Value |
| --- | --- |
| Runtime command | `uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540` |
| Runtime entrypoint | `src/aio/aiops/api/app.py` |
| Environment file | `src/aio/.env` or `src/aio/.env.live` |
| Auto-run enabled | `TODO: true/false` |
| Auto-run interval | `TODO: e.g. 5 seconds` |
| Policy mode | `TODO: dry-run` |
| Prometheus source | `TODO: URL/port-forward, redacted if needed` |
| Trace source | `TODO: Jaeger enabled/disabled` |
| Log source | `TODO: OpenSearch enabled/disabled` |
| Kubernetes enrichment | `TODO: enabled/disabled` |

## Scenario

| Field | Value |
| --- | --- |
| Incident/fault name | `TODO: e.g. local-paymentFailure` |
| Fault injection method | `TODO: mentor enabled flag / approved local flag / replay` |
| Fault percentage | `TODO: e.g. 50%` |
| Expected affected service | `TODO: e.g. checkout` |
| Expected dependency | `TODO: e.g. payment` |
| Fault enabled at | `TODO: YYYY-MM-DD HH:mm:ss +07` |
| Fault disabled at | `TODO: YYYY-MM-DD HH:mm:ss +07` |
| Runtime started at | `TODO: YYYY-MM-DD HH:mm:ss +07` |
| First detector fire at | `TODO: YYYY-MM-DD HH:mm:ss +07` |
| Lead time | `TODO: first detector fire - fault enabled` |

## Live Detector Output

Paste the important terminal lines here:

```text
TODO: paste AIOPS_RUN_START
TODO: paste AIOPS_DETECT threshold_fire/anomaly line
TODO: paste AIOPS_INCIDENT_UPSERT line
TODO: paste AIOPS_DEDUP_RESULT line
TODO: paste AIOPS_CONCLUSION or AIOPS_ROOT_CAUSE line
TODO: paste AIOPS_NOTIFY_READY line
TODO: paste AIOPS_BLOCK remediation_decide line
TODO: paste AIOPS_RUN_END
```

Extracted detector result:

| Field | Value |
| --- | --- |
| Detector ID | `TODO: e.g. ops01_checkout_slo` |
| Signal | `TODO: e.g. checkout_bad_ratio_24h` |
| Service | `TODO: e.g. checkout` |
| Severity | `TODO: e.g. SEV1` |
| Observed value | `TODO` |
| Threshold | `TODO` |
| Reason | `TODO: threshold_breached / anomaly_score / no_data` |
| Incident ID | `TODO` |
| Occurrence count | `TODO` |
| Runbook | `TODO` |

## RCA And Enrichment

| Field | Value |
| --- | --- |
| RCA source | `TODO: rca / incident fallback` |
| Root cause service | `TODO` |
| RCA score | `TODO` |
| Root cause metrics | `TODO` |
| Trace evidence | `TODO: Jaeger trace link or N/A` |
| Log evidence | `TODO: OpenSearch count/excerpt or N/A` |
| Kubernetes evidence | `TODO: pod readiness/restarts/rollout or N/A` |

Paste RCA/enrichment proof:

```text
TODO: paste AIOPS_RCA_FINAL_ALGORITHM_SCORES / AIOPS_ROOT_CAUSE / evidence summary lines
```

## Alerting And Safety

| Field | Value |
| --- | --- |
| Notification status | `TODO: pending/sent/outbox` |
| Notification route | `TODO: outbox/webhook/Grafana/etc.` |
| Selected action | `TODO: page_oncall` |
| Decision | `TODO: fallback-page-oncall / dry-run-recorded` |
| Live mutation executed | `No` |
| Flagd mutation | `No` |

Safety proof:

```text
TODO: paste AIOPS_NOTIFY_READY line
TODO: paste AIOPS_BLOCK remediation_decide line
```

## Precision, Recall, And Lead Time

For the API runtime live run, report lead time from the actual injected fault window:

```text
lead_time = first_detector_fire_time - fault_enabled_time
```

| Metric | Value | Source |
| --- | --- | --- |
| Live lead time | `TODO` | Terminal timestamp + fault enable timestamp |
| Incident precision | `TODO` | Labeled eval report or measured normal+incident windows |
| Incident recall | `TODO` | Labeled incident set |
| False positives | `TODO` | Normal observation window |
| Duplicate/spam behavior | `TODO` | `AIOPS_DEDUP_RESULT` occurrence count/cooldown |
| RCA top-k hit | `TODO` | Labeled eval report or manual root-cause confirmation |

If using the existing labeled replay report, cite:

```text
src/aio/evaluate/current_pipeline_report.json
```

and fill:

```text
case_count=TODO
incident_precision=TODO
incident_recall=TODO
incident_f1=TODO
rca_top_k_hit=TODO
```

Note any caveat clearly, for example if the labeled dataset has no normal cases and therefore does not fully measure false positives.

## Screenshot Checklist

Capture these images before submitting Jira.

| Screenshot | When to capture | Must visibly show |
| --- | --- | --- |
| `01-runtime-started.png` | Immediately after starting Uvicorn | Command `uvicorn aiops.api.app:create_app`, port `8540`, `Application startup complete`, and `Uvicorn running` |
| `02-health-live.png` | After runtime starts | Browser/curl result for `http://localhost:8540/health/live` showing status ok |
| `03-health-ready.png` | After runtime starts | Browser/curl result for `http://localhost:8540/health/ready` showing ready, or show failure if dependency not ready |
| `04-before-fault-dashboard.png` | Before enabling fault | Grafana/Prometheus panel showing baseline checkout bad ratio/latency normal |
| `05-flag-enabled.png` | Right after enabling incident | Flag UI or mentor evidence showing fault name, value/percentage, and timestamp |
| `06-detector-fired-terminal.png` | First detector fire | Terminal lines showing `AIOPS_DETECT`, detector ID, signal, value, threshold, service, severity |
| `07-incident-created-terminal.png` | Same run as detector fire | `AIOPS_INCIDENT_UPSERT` with incident ID and detector ID |
| `08-rca-terminal.png` | Same run after RCA | `AIOPS_CONCLUSION` or `AIOPS_ROOT_CAUSE` with root service, score, metrics |
| `09-notify-remediation-terminal.png` | Same run after action decision | `AIOPS_NOTIFY_READY` and `AIOPS_BLOCK remediation_decide`, showing `page_oncall` / dry-run/fallback |
| `10-dedup-repeat-run.png` | A later auto-run cycle while fault remains active | `AIOPS_DEDUP_RESULT` showing occurrence count increasing instead of spammy new alerts |
| `11-during-fault-dashboard.png` | During active fault | Grafana/Prometheus panel showing checkout bad ratio/latency above threshold |
| `12-after-fault-recovery.png` | After disabling fault | Dashboard showing metric recovery or runtime no longer creating new severe incident |
| `13-report-or-state-artifact.png` | After run | File explorer/terminal showing state/evidence artifact path if used |

Optional but useful:

| Screenshot | Must visibly show |
| --- | --- |
| `14-jaeger-trace.png` | Trace evidence linked to checkout/payment failure, if available |
| `15-opensearch-log.png` | Relevant error log count/excerpt, if available |
| `16-kubernetes-evidence.png` | Pod readiness/restarts/rollout state, if used in RCA evidence |

## Jira Paste Block

```text
AI MANDATE #7b API runtime live proof:
- Runtime command: uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540
- Runtime entrypoint: src/aio/aiops/api/app.py
- Auto-run: TODO
- Scenario: TODO
- Fault enabled: TODO
- First detector fire: TODO
- Lead time: TODO
- Detector fired: TODO detector=..., signal=..., value=..., threshold=..., service=..., severity=...
- Incident: TODO
- RCA: TODO service=..., score=..., metrics=...
- Alert/action: TODO page_oncall / dry-run or fallback-page-oncall
- Safety: no production mutation, no flagd mutation
- Evidence screenshots: TODO attach 01-12 screenshots
- Precision/recall source: TODO
- Precision: TODO
- Recall: TODO
- False-positive/spam note: TODO
```
