# AI MANDATE #7b - API Runtime Live Detection Evidence

## 1. Scope

This document records the clean local live run for `AI MANDATE #7b` using the AIOps API runtime against port-forwarded production-like telemetry.

Primary labeled scenario:

```text
Normal baseline under Locust load -> operator enables local-paymentFailure=50% -> AIOps detects checkout impact -> incident dedup/notification intent -> operator disables fault -> telemetry recovery
```

AIOps ran in `dry-run` mode. The operator manually changed the flag in Flagd Configurator. AIOps did not mutate Kubernetes resources or Flagd state.

## 2. Definition of Done Mapping

- [x] Normal baseline captured before fault with `candidates=0`, `incidents=0`.
- [x] Operator fault injection captured through Flagd UI.
- [x] Detector fired from live Prometheus telemetry.
- [x] First detector fire timestamp and lead-time calculated.
- [x] Incident ID captured through runtime API.
- [x] Dedup shown by stable incident ID with increasing `occurrence_count`.
- [x] Notification intent captured for the same checkout incident.
- [x] User-visible impact captured on SLO dashboard.
- [x] Recovery captured on SLO dashboard.
- [x] Expanded-service live proof captured for a labeled cart fault.
- [x] No-spam behavior demonstrated through stable incident IDs and notification dedup.
- [x] Burn-rate detector live proof on an isolated evaluation run.
- [x] Caveats documented for RCA, incident lifecycle, and rolling-24h burn-rate.

## 3. Runtime Configuration

| Field | Value |
| --- | --- |
| Working directory | `src/aio` |
| Runtime command | `python -m uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540` |
| API | `http://localhost:8540` |
| Policy mode | `dry-run` |
| Auto-run | `true`, every `5s` |
| Prometheus | `http://localhost:9090` through port-forward |
| Grafana | `http://localhost:3000` through port-forward |
| Jaeger | `http://localhost:16686` through port-forward |
| Kubernetes API | `http://localhost:8001`, read-only enrichment |
| OpenSearch | not used in this run |
| Traffic | Locust `50 users`, ramp/spawn rate `1 user/s`, `10 workers`, about `12.8 RPS` |
| Burn-rate detector in primary clean run | disabled to avoid polluted rolling-24h window from previous tests |

Local `.env` values used for this run:

```env
AIOPS_POLICY_MODE=dry-run
AIOPS_AUTO_RUN_ENABLED=true
AIOPS_AUTO_RUN_INTERVAL_SECONDS=5
AIOPS_PROMETHEUS_BASE_URL=http://localhost:9090
AIOPS_GRAFANA_WEBHOOK_SECRET=local-test-secret
AIOPS_JAEGER_BASE_URL=http://localhost:16686
AIOPS_KUBERNETES_API_URL=http://localhost:8001
AIOPS_OPENSEARCH_BASE_URL=
AIOPS_LIVE_EXECUTOR_URL=
```

The runtime config change for this clean run was limited to disabling `ops01_checkout_slo_burn_rate`. The reason is documented in [Section 10](#10-supplemental-burn-rate-and-no-spam-proof).

## 4. Baseline

Baseline was taken under steady Locust load before enabling the fault.

| Field | Evidence |
| --- | --- |
| Locust users | `50` users, `10` workers |
| Locust failures | `0%` |
| Checkout error ratio | `0%` on Grafana baseline |
| AIOps detector candidates | `0` |
| AIOps incidents | `0` |
| RCA root causes | `0` |

Runtime baseline proof:

```text
2026-07-24 01:00:54.255 +07
AIOPS_DEDUP_RESULT input_candidates=0 incidents=0 ids=[] services=[] occurrences=[]
AIOPS_BLOCK rca anomalies=0 root_causes=[]
AIOPS_RUN_END candidates=0 incidents=0 root_causes=0
```

![Baseline checkout Grafana at 50 users](./04c-baseline-checkout-grafana-50u.png)

![Baseline Locust 50 users, 0 percent failures](./04d-baseline-locust-50u.png)

![Baseline AIOps runtime clean](./05b-baseline-runtime-clean-50u.png)

### 4.1 Baseline and impact-gate interpretation

The live fires in this document use fixed SLO/impact thresholds as the final
alert gates. They are not presented as the complete adaptive-baseline
implementation.

Per-service statistical baseline and anomaly scoring are implemented and
documented in Mandate #7a and
[`ADR-DETECT-001`](../../../src/aio/docs/mandates/7a/ADR-DETECT-001.md).
In this #7b run:

- the normal windows establish that checkout and cart remain quiet under
  expected load;
- the 5m error-rate and p99 thresholds act as user-impact alert gates;
- dedup and notification cooldown prevent repeated evaluation cycles from
  producing duplicate alert incidents.

Dynamic-baseline quality is evaluated separately from the fixed SLO-impact
gates. This live run validates the runtime detection, incident, notification,
and recovery path; the two threshold fires alone are not claimed as proof of
adaptive-baseline quality.

## 5. Fault Injection

The operator enabled `local-paymentFailure` at `50%`.

| Field | Value |
| --- | --- |
| Fault | `local-paymentFailure` |
| Fault value | `50%` |
| Owner/method | Operator through Flagd Configurator UI |
| Fault start timestamp | `2026-07-24 01:03:03.077 +07` |
| Expected affected service | `checkout` |
| Expected dependency | `payment` |

![Fault start timestamp](./06a-fault-start-timestamp.png)

![Flagd before payment failure](./06b-flagd-before-payment-failure-off.png)

![Flagd local-paymentFailure at 50 percent](./06c-flagd-payment-failure-50.png)

## 6. Detector Fire and Lead-Time

First detector fire:

```text
2026-07-24 01:06:28.494 +07 WARNING aiops.detectors.threshold
AIOPS_DETECT threshold_fire
  detector  : auto_checkout_error_rate
  signal    : checkout_error_rate_5m
  value     : 0.07857711542847343
  threshold : 0.05
  service   : checkout
  severity  : SEV2
```

Lead-time:

```text
lead_time = 01:06:28.494 - 01:03:03.077
          = 205.417 seconds
          ~= 3 minutes 25 seconds
```

| Detector | Signal | Observed | Threshold | Severity | Incident |
| --- | --- | ---: | ---: | --- | --- |
| `auto_checkout_error_rate` | `checkout_error_rate_5m` | `7.86%` | `5%` | `SEV2` | `inc-b3d92ea50475` |

The same runtime cycle also enqueued notification intent for the same checkout incident:

```text
AIOPS_NOTIFY_ENQUEUED_READY
  incident : inc-b3d92ea50475
  service  : checkout
  severity : SEV2
  runbook  : RB-SERVICE-ERROR-RATE
  status   : pending
```

![Checkout error-rate detector fired](./07b-detector-fired-checkout-error-rate-clean.png)

## 7. Incident API and Dedup

First incident API snapshot:

| Field | Value |
| --- | --- |
| `incident_id` | `inc-b3d92ea50475` |
| `state` | `open` |
| `severity` | `SEV2` |
| `flow` | `checkout` |
| `service` | `checkout` |
| `detector` | `auto_checkout_error_rate` |
| `occurrence_count` | `4` |

Later snapshot:

| Field | Value |
| --- | --- |
| `incident_id` | `inc-b3d92ea50475` |
| `occurrence_count` | `9` |
| detector events | same `auto_checkout_error_rate` signal |

Dedup result: `PASS`. The detector fired across multiple cycles while the fault was active, but the runtime kept the same incident ID and increased `occurrence_count` instead of creating duplicate checkout incidents.

![Incident API occurrence count 4](./08b-incident-api-checkout-error-rate-occurrence4.png)

![Dedup repeat occurrence count 9](./11b-dedup-repeat-checkout-occurrence9-with-rca-caveat.png)

## 8. User-Visible Impact

During the fault, the Webstore SLO dashboard showed checkout success degraded below the official SLO.

| Metric | Value |
| --- | ---: |
| Checkout success rate | `63.9%` |
| Checkout SLO | `>= 99.0%` |
| Checkout p95 latency | `132 ms` |
| Checkout p99 latency | `368 ms` |

This is the user-visible impact evidence for the injected checkout/payment fault.

![Fault SLO dashboard checkout success 63.9 percent](./12c-fault-slo-dashboard-checkout-success-639.png)

## 9. Recovery

The operator disabled `local-paymentFailure`.

| Field | Value |
| --- | --- |
| Fault disabled timestamp | `2026-07-24 01:10:46.173 +07` |
| Recovery dashboard captured | approx. `2026-07-24 01:17:03 +07` |
| Recovery time from fault disabled | approx. `376.827 seconds` (`6m17s`) |
| Checkout success rate after recovery | `100%` |
| Checkout p95 after recovery | `350 ms` |
| Checkout p99 after recovery | `775 ms`, below `1s` |

Telemetry recovery result: `PASS`.

![Fault disabled timestamp](./13a-fault-disabled-timestamp.png)

![Flagd local-paymentFailure disabled](./13b-flagd-payment-failure-off-clean.png)

![Recovery SLO dashboard checkout 100 percent](./14d-recovery-slo-dashboard-checkout-100.png)

## 10. Supplemental Burn-Rate and No-Spam Proof

The primary labeled run used the live 5m checkout error-rate detector because
previous tests remained in the rolling-24h window. A separate supplemental run
was subsequently completed with only `ops01_checkout_slo_burn_rate` enabled.

The official signal is the checkout PlaceOrder 24h bad ratio divided by
`0.01`, the allowed error ratio for the checkout SLO of `99%`. The detector
fires when `checkout_error_budget_burn_rate_24h > 1.0x`.

### 10.1 Baseline and fault timeline

At `2026-07-24 11:23:32 +07`, AIOps reported zero candidates and zero
incidents. Grafana showed a latest burn rate of `0.790x`, mean `0.818x`,
and maximum `0.845x`. This establishes the below-threshold no-fire baseline.

![Burn-rate baseline runtime with no fire](./18a-burn-rate-baseline-runtime-no-fire.png)

![Burn-rate baseline below 1x](./18b-burn-rate-baseline-below-1x.png)

| Time (+07) | Operator change |
| --- | --- |
| `2026-07-24 11:26:13` | `local-paymentFailure=50%` |
| `2026-07-24 11:30:45` | escalated to `75%` |
| `2026-07-24 11:40:58` | escalated to `100%` |

![Burn-rate fault enabled at 50 percent](./18c-burn-rate-fault-enabled-50-percent.png)

![Burn-rate fault escalated to 75 percent](./18d-burn-rate-fault-escalated-75-percent.png)

![Burn-rate fault escalated to 100 percent](./18e-burn-rate-fault-escalated-100-percent.png)

Grafana captured the rolling-24h burn rate above threshold at `1.03x`.
An initial missing AIOps result was traced to an unset Prometheus URL
(`quality=missing`, `status=unknown`, `error=UnsupportedProtocol`). After
correcting that test setup, the collector returned a verified value and the
detector fired. This setup error is not counted as a detector false negative.

![Burn rate crossed 1x in Grafana](./18f-burn-rate-crossed-1x-grafana.png)

### 10.2 Detector fire, incident, dedup, and no-spam

`ops01_checkout_slo_burn_rate` first fired at
`2026-07-24 11:49:52.261 +07` with value `1.146865926137082x > 1.0x`,
service `checkout`, severity `SEV1`. The same cycle created incident
`inc-ca09d8e8a247`, selected `RB-CHECKOUT-SLO`, and emitted one
`AIOPS_NOTIFY_ENQUEUED_READY` intent.

Elapsed time from the initial 50% fault was approximately `23m39s`. Because
the fault intensity changed during that interval, this is supplemental
operational context and is not mixed into the primary labeled-set lead-time
statistics.

![Burn-rate detector fire, incident, and notification](./18g-burn-rate-detector-fired-incident-notification.png)

Repeated verified fires retained the same incident and increased
`occurrence_count` from `1` to `2` and then `3`. Only the first
occurrence emitted a notification-enqueue event; no additional enqueue event
appeared during the subsequent deduplicated cycles.

![Burn-rate dedup with same incident at occurrence 2](./18h-burn-rate-dedup-same-incident-occurrence2.png)

![Burn-rate final incident API at occurrence 3](./18j-burn-rate-final-incident-api-occurrence3.png)

The final API snapshot records three verified events at `1.2185x`,
`1.2379x`, and `1.2412x`, all above `1.0x`, on the same incident.

### 10.3 Fault removal and short-window recovery

The operator disabled `local-paymentFailure` at
`2026-07-24 11:55:59 +07`. Checkout 5m error ratio then fell from
approximately `66%` to `0%` while request traffic remained present. This
supports fault impact and short-window telemetry recovery. The rolling-24h
burn rate is not expected to recover immediately.

![Burn-rate fault disabled](./18i-burn-rate-fault-disabled.png)

![Checkout error-ratio impact and recovery](./18k-burn-rate-supporting-error-ratio-impact-recovery.png)

| Requirement | Status | Evidence |
| --- | --- | --- |
| Below-threshold no-fire | `PASS` | `0.790x < 1.0x`, zero candidates/incidents |
| Live burn-rate detector | `PASS` | `1.1469x > 1.0x`, incident `inc-ca09d8e8a247` |
| Dedup | `PASS` | Same incident, occurrence `1 -> 2 -> 3` |
| Notification no-spam | `PASS` | One initial enqueue; no later enqueue during cooldown |
| Short-window recovery | `PASS` | 5m checkout error ratio returned to `0%` |

## 11. RCA and Incident Lifecycle Caveats

RCA produced an unexpected `recommendation` root-cause candidate after the checkout incident. This is not counted as the true positive for the injected `local-paymentFailure` case.

Post-recovery API also showed incidents still in `state=open`. Therefore, telemetry recovery is proven, but automatic incident resolution is not claimed.

| Caveat | Evidence | Submission treatment |
| --- | --- | --- |
| RCA unexpected service | `recommendation` root cause | record as caveat; do not count as TP |
| Incident lifecycle | checkout incident still `open` after telemetry recovery | record as caveat; recovery claim is telemetry-only |
| Burn-rate recovery | rolling-24h value remains elevated after fault removal | claim short-window telemetry recovery, not immediate 24h recovery |

![Post-recovery incident API caveat](./14e-post-recovery-incident-api-open-caveat.png)

![Post-recovery RCA recommendation caveat](./14f-post-recovery-rca-recommendation-caveat.png)


## 12. Supplemental Expanded-Service Proof

This second labeled run proves detector coverage beyond the primary
checkout/payment scenario. It used a separate clean state store to prevent
incident-state contamination between scenarios. The cart fault is included as
the second labeled injected incident because it has explicit ground truth,
fault-start evidence, detector evidence, incident evidence, user-visible
impact, and recovery evidence.

| Field | Value |
| --- | --- |
| Supplemental fault | `local-cartFailure` |
| Fault start timestamp | `2026-07-24 01:38:51.933 +07` |
| First breached telemetry sample | `2026-07-24 01:41:47.314 +07` |
| Incident creation / alert time | `2026-07-24 01:41:59.880 +07` |
| Lead-time | `187.947s` (`~3m08s`) |
| Detector | `auto_cart_latency_p99` |
| Signal | `cart_p99_latency_5m` |
| Observed value | `3.0866666666666718s` |
| Threshold | `1s` |
| Service | `cart` |
| Severity | `SEV1` |
| Incident | `inc-c7f94b1810a6` |
| Incident occurrence count | `11` in the retained supplemental state store |

The Webstore SLO dashboard also showed `Cart Success Rate = 97.2%`, below its `>=99.5%` SLO. After disabling the flag, cart success returned to `100%`. This demonstrates a second live service path (`cart`) with detector fire, incident creation, and telemetry recovery.

![Expanded service flag baseline all off](./17a-expanded-cart-flag-before-off.png)

![Expanded service cart baseline healthy](./17b-expanded-cart-slo-baseline-healthy.png)

![Expanded service cart observability baseline](./17c-expanded-cart-observability-baseline.png)

![Expanded service cart fault timestamp](./17d-expanded-cart-fault-start-timestamp.png)

![Expanded service cart flag enabled](./17e-expanded-cart-flag-enabled.png)

![Expanded service cart fault SLO impact](./17f-expanded-cart-fault-slo-impact.png)

![Expanded service cart detector fired](./17g-expanded-cart-detector-fired.png)

![Expanded service cart incident API](./17h-expanded-cart-incident-api.png)

![Expanded service cart flag disabled](./17i-expanded-cart-flag-disabled.png)

![Expanded service cart recovery SLO dashboard](./17j-expanded-cart-recovery-slo-dashboard.png)

![Expanded service cart recovery observability](./17k-expanded-cart-recovery-observability.png)

## 13. Labeled Set and Metrics

Definitions from mandate:

```text
recall = caught injected incidents / K
precision = correct fires / total fires
lead-time = first detector fire time - fault start time
```

Counting rule for precision:

```text
One "fire" is one deduplicated alert incident, identified by its stable
incident ID. Repeated detector evaluation cycles that only increase
occurrence_count on the same incident are not counted as new alerts.
RCA candidates are evaluated separately and are not counted as detector fires.
```

Labeled cases across the two isolated clean runs:

| Case | Ground truth | Window | Expected | Result |
| --- | --- | --- | --- | --- |
| `01` | Normal checkout baseline | before `01:03:03.077 +07` | no alert incident | `TN` |
| `02` | `local-paymentFailure=50%` | `01:03:03.077` to `01:10:46.173 +07` | checkout/payment impact | `TP`, caught by checkout error-rate |
| `03` | Checkout recovery | after `01:10:46.173 +07` | telemetry returns normal | `PASS`, telemetry recovered |
| `04` | Normal cart baseline | before `01:38:51.933 +07` | no cart alert incident | `TN` |
| `05` | `local-cartFailure` | from `01:38:51.933 +07` until fault disabled | cart impact | `TP`, caught by cart p99 latency |
| `06` | Cart recovery | after fault disabled | telemetry returns normal | `PASS`, telemetry recovered |

Metric summary:

| Metric | Value | Formula / note |
| --- | ---: | --- |
| Injected incidents `K` | `2` | payment failure + cart failure |
| Caught incidents | `2` | both labeled incidents detected |
| False negatives | `0` | `K - caught` |
| Incident recall | `100%` | `2 / 2` |
| Alert-incident precision | `100%` | `2 correct deduplicated alert incidents / 2 total alert incidents` |
| Checkout lead-time | `205.417s` | checkout first fire - checkout fault start |
| Cart lead-time | `187.947s` | cart incident creation - cart fault start |
| Mean lead-time | `196.682s` | `(205.417 + 187.947) / 2` |
| Median lead-time | `196.682s` | median of the two labeled lead-times |
| Checkout recovery time | `~376.827s` | recovery dashboard capture - fault disabled |
| RCA checkout root-cause hit | `False` | RCA did not identify `payment`; reported separately from detection precision |

Because `K=2`, these metrics remain preliminary and are not statistically
broad. They demonstrate two working live service paths for #7b but should not
be presented as production-quality model evaluation. The `100%` precision
uses the two expected deduplicated labeled incidents as the counting unit.
State-store inspection confirmed the corrected cart incident ID
`inc-c7f94b1810a6`; RCA candidates remain excluded from detector precision.

## 14. Evidence Index

| File | Purpose |
| --- | --- |
| `04c-baseline-checkout-grafana-50u.png` | Baseline checkout Grafana at 50 users |
| `04d-baseline-locust-50u.png` | Locust 50 users, 0% failures |
| `05b-baseline-runtime-clean-50u.png` | Runtime baseline, `candidates=0`, `incidents=0` |
| `06a-fault-start-timestamp.png` | Fault start timestamp |
| `06b-flagd-before-payment-failure-off.png` | Flagd before fault |
| `06c-flagd-payment-failure-50.png` | Flagd fault enabled at 50% |
| `07b-detector-fired-checkout-error-rate-clean.png` | Checkout error-rate detector fire and notification intent |
| `08b-incident-api-checkout-error-rate-occurrence4.png` | Incident API first snapshot |
| `11b-dedup-repeat-checkout-occurrence9-with-rca-caveat.png` | Dedup repeat and RCA caveat |
| `12c-fault-slo-dashboard-checkout-success-639.png` | User-visible checkout SLO impact |
| `13a-fault-disabled-timestamp.png` | Fault disabled timestamp |
| `13b-flagd-payment-failure-off-clean.png` | Flagd fault disabled |
| `14d-recovery-slo-dashboard-checkout-100.png` | Recovery dashboard |
| `14e-post-recovery-incident-api-open-caveat.png` | Incident lifecycle caveat |
| `14f-post-recovery-rca-recommendation-caveat.png` | RCA caveat |
| `17a-expanded-cart-flag-before-off.png` | Supplemental cart flag baseline |
| `17b-expanded-cart-slo-baseline-healthy.png` | Supplemental healthy SLO baseline |
| `17c-expanded-cart-observability-baseline.png` | Supplemental cart observability baseline |
| `17d-expanded-cart-fault-start-timestamp.png` | Supplemental cart fault timestamp |
| `17e-expanded-cart-flag-enabled.png` | Supplemental cart flag enabled |
| `17f-expanded-cart-fault-slo-impact.png` | Supplemental cart SLO impact |
| `17g-expanded-cart-detector-fired.png` | Supplemental cart detector fire |
| `17h-expanded-cart-incident-api.png` | Supplemental cart incident API |
| `17i-expanded-cart-flag-disabled.png` | Supplemental cart flag disabled |
| `17j-expanded-cart-recovery-slo-dashboard.png` | Supplemental cart recovery SLO dashboard |
| `17k-expanded-cart-recovery-observability.png` | Supplemental cart recovery observability |
| `18a-burn-rate-baseline-runtime-no-fire.png` | Runtime baseline with zero candidates/incidents |
| `18b-burn-rate-baseline-below-1x.png` | Grafana baseline below `1x` |
| `18c-burn-rate-fault-enabled-50-percent.png` | Payment fault enabled at 50% |
| `18d-burn-rate-fault-escalated-75-percent.png` | Fault escalated to 75% |
| `18e-burn-rate-fault-escalated-100-percent.png` | Fault escalated to 100% |
| `18f-burn-rate-crossed-1x-grafana.png` | Rolling-24h burn rate crossed `1x` |
| `18g-burn-rate-detector-fired-incident-notification.png` | Detector fire, incident, and notification |
| `18h-burn-rate-dedup-same-incident-occurrence2.png` | Dedup to occurrence 2 |
| `18i-burn-rate-fault-disabled.png` | Supplemental fault disabled |
| `18j-burn-rate-final-incident-api-occurrence3.png` | Final incident snapshot at occurrence 3 |
| `18k-burn-rate-supporting-error-ratio-impact-recovery.png` | Error-ratio impact and recovery |

## 15. Reproduce

Terminal 1 - port-forward dependencies:

```powershell
# Run from the repository root
Set-Location .\src\aio
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
powershell -File scripts\port_forward.ps1
```

Before starting a scenario, verify that each detector being tested has
`enabled: true` in the selected runtime configuration. A signal may still be
collected when its detector is disabled, but it will not produce a detector
fire.

Terminal 2 - run AIOps API runtime:

```powershell
# Run from the repository root
Set-Location .\src\aio
.\.venv\Scripts\Activate.ps1
python -m uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540
```

Terminal 3 - verify runtime:

```powershell
Invoke-RestMethod http://localhost:8540/health/ready
Invoke-RestMethod http://localhost:8540/api/v1/incidents
```

Run flow:

1. Start Locust with `50` users and ramp/spawn rate `1 user/s`.
2. Wait for a normal baseline and confirm `AIOPS_DEDUP_RESULT input_candidates=0 incidents=0`.
3. In Flagd Configurator, set `local-paymentFailure=50%`.
4. Record the fault-start timestamp immediately after the UI confirms the new
   value with `Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff zzz"`. Prefer a Flagd
   audit/event timestamp when available.
5. Capture first `AIOPS_DETECT threshold_fire` for `auto_checkout_error_rate`.
6. Call `GET /api/v1/incidents` and capture incident ID and occurrence count.
7. Wait more cycles and capture dedup with the same incident ID and higher occurrence count.
8. Capture SLO impact dashboard.
9. Set `local-paymentFailure=off`, record timestamp, and capture recovery dashboard.

The measured checkout lead-time may include a short Flagd UI interaction delay
because the operator timestamp was captured manually.

## 16. Submission Traceability

| Item | Evidence |
| --- | --- |
| Branch tested | `feat/aio/v0.0.5` |
| Evidence commit | `c11e4bd` (`docs(aiops): refresh mandate 7b live evidence`) |
| Repository HEAD when this document was reviewed | `1206411` |
| Runtime implementation PR/commit | `TODO: add final runtime implementation PR or commit link` |
| ADR | [`ADR-DETECT-001`](../../../src/aio/docs/mandates/7a/ADR-DETECT-001.md) |
| ADR sign-off | `Pending reviewer sign-off` |
| Policy mode | `dry-run` |
| Burn-rate supplemental evidence | `PASS` - evidence `18a` through `18k` |

Before submission, replace all `TODO`/`Pending` traceability values with the
final reviewed links or explicit final status.

## 17. Jira Paste Block

```text
AI MANDATE #7b - API runtime live proof

- Runtime: local AIOps API on http://localhost:8540, Prometheus/Grafana/Jaeger/K8s through port-forward
- Mode: dry-run; no Kubernetes or Flagd mutation by AIOps
- Traffic: Locust 50 users, ramp 1 user/s, 10 workers, about 12.8 RPS, 0% failures during baseline
- Baseline: 2026-07-24 01:00:54 +07; AIOPS_DEDUP_RESULT input_candidates=0 incidents=0; root_causes=[]
- Fault: local-paymentFailure=50%, operator enabled through Flagd
- Fault start: 2026-07-24 01:03:03.077 +07
- First detector fire: 2026-07-24 01:06:28.494 +07
- Lead-time: 205.417s (~3m25s)
- Detector: auto_checkout_error_rate on checkout_error_rate_5m, value 0.078577 > threshold 0.05, SEV2
- Incident: inc-b3d92ea50475, service checkout, runbook RB-SERVICE-ERROR-RATE
- Notification intent: AIOPS_NOTIFY_ENQUEUED_READY for inc-b3d92ea50475, status pending
- Dedup/no duplicate ID: same incident inc-b3d92ea50475, occurrence_count 4 -> 9 -> 12
- Impact: checkout success dropped to 63.9% against SLO >=99.0%
- Fault disabled: 2026-07-24 01:10:46.173 +07
- Recovery: checkout success 100%, p95 350ms, p99 775ms (<1s), captured around 01:17 +07
- Labeled set: K=2 injected incidents - local-paymentFailure and local-cartFailure
- Recall: 100% (2 caught / 2 injected incidents)
- Alert-incident precision: 100% (2 correct deduplicated alert incidents / 2 total alert incidents)
- Counting unit: one stable deduplicated incident ID is one alert; occurrence_count increments are not new alerts
- Checkout lead-time: 205.417s
- Cart lead-time: 187.947s; mean/median labeled lead-time: 196.682s
- Expanded service: local-cartFailure produced auto_cart_latency_p99 on cart_p99_latency_5m, value 3.0867s > 1s, incident inc-c7f94b1810a6; cart SLO recovered to 100%
- RCA quality is reported separately: payment root-cause hit=false; RCA output is not counted as a detection false positive
- Burn-rate supplemental proof: PASS; baseline 0.790x with no fire, verified fire at 1.1469x, incident inc-ca09d8e8a247, occurrence_count 1 -> 3
- Burn-rate no-spam: one initial notification enqueue; subsequent deduplicated cycles did not enqueue again during cooldown
- Caveats: incidents remain open after short-window telemetry recovery; rolling-24h burn rate is not expected to recover immediately
- Evidence: docs/aiops/evidence/MANDATE-07b-api-runtime-draft.md and linked screenshots in docs/aiops/evidence
```

## 18. Conclusion

The two isolated labeled runs demonstrate that the AIOps runtime detected live
checkout and cart faults from Prometheus telemetry, created stable incidents,
deduped repeated detections, recorded notification intent for the primary
checkout case, and showed user-visible SLO degradation followed by telemetry
recovery. Detection recall and alert-incident precision are both `100%` on the
preliminary `K=2` labeled set. The supplemental burn-rate run additionally
proves official error-budget impact detection, stable incident deduplication,
and notification cooldown behavior. RCA quality and automatic incident
resolution remain explicit caveats rather than completed claims.
