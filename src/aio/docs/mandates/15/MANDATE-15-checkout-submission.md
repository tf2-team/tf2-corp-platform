# AI MANDATE #15 - Checkout Submission Pack

File chinh de nop Mandate #15. Folder nay chi giu file nop va ADR, khong dung cac draft demo/fake data lam Jira evidence.

## 1. Ket luan nhanh

Mandate #15 yeu cau chung minh AIOps detector tren service `checkout`:

- Bat duoc su co that.
- Khong bi noise/spike che mat su co nhe.
- Khong bao false incident khi checkout chi dang high load nhung van healthy.
- Chay lien tuc nhu workload, khong phai script mot lan.
- Sinh incident summary va gui ra kenh that.
- Co precision/recall/lead-time va MTTD before/after tren labeled dataset.

Evidence Jira phai lay tu live Prometheus captures trong `evaluate/dataset/mandate15_live/`, khong lay dataset fake/demo.

## 2. Scope da chot

Service monitored: `checkout`

Telemetry used:

- `checkout_p95_latency_5m` / `checkout_p99_latency_5m` - latency.
- `checkout_error_rate_5m` / dependency error signals such as `payment_error_rate_5m` and `cart_error_rate_5m` - error rate.
- `checkout_request_rate_5m` - load context to distinguish busy-but-healthy from broken.

Detection method: service-specific baseline using robust score, plus health gate so load-only deviations do not fire incidents.

Incident-summary destination: Discord webhook / TF2 AIOps real team channel.

Scope note: `checkout` is the monitored service. `payment` and `cart` are used as checkout dependencies for real-incident and masking proof.

## 3. Current evidence

Live dataset:

```text
evaluate/dataset/mandate15_live/
```

Cases captured:

| Case | Label | Result | Notes |
|---|---:|---:|---|
| `checkout_normal_baseline` | expected no incident | no-fire | Baseline with all fault flags off. |
| `checkout_high_load_healthy` | expected no incident | no-fire | Locust ramp 200 -> 400 users, no fault flag, service healthy. |
| `checkout_real_incident` | expected incident | fired | `local-paymentFailure=50%`; checkout/payment error-rate breach detected. |
| `checkout_masking` | expected incident | fired | `local-loadGeneratorFloodHomepage=on` noise plus `local-cartFailure=on`; subtle checkout/cart incident still detected. |

Replay command:

```powershell
.\.venv\Scripts\python.exe -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json
```

Authoritative cross-dataset notification check: `evaluate/live_notification_eval_report.json`.
For the Mandate 15 subset (4 cases), notification results are **TP=2, TN=2, FP=0, FN=0**, therefore **precision=100%**, **recall=100%**, and **F1=100%**. Across all 10 runnable Mandate 15 + 7b cases, notification results are **precision=83.3%**, **recall=100%**, and **F1=90.9%** (TP=5, TN=4, FP=1, FN=0); the single FP belongs to the 7b subset, while the Mandate 15 subset remains 100%. Two burn-rate cases are skipped because they lack `metric_series.json`. RCA root top-1 remains 0% and is not conflated with notification detection.
Replay result from `evaluate/mandate15_live_report.json`:

```json
{
  "case_count": 4,
  "labeled_case_count": 4,
  "precision": 1.0,
  "recall": 1.0,
  "false_positive_count": 0,
  "false_negative_count": 0,
  "avg_lead_time_seconds": 29.5,
  "lead_times_seconds": [0.0, 59.0]
}
```

### 3.1 Lead-time reconciliation: masking mốc thật

| Case | Fault start | First live incident record | Live lead-time |
|---|---|---|---:|
| `checkout_real_incident` | epoch `1785093534` | epoch `1785093593` | **59.0s** |
| `checkout_masking` | epoch `1785095183` (`2026-07-27 02:46:23 +07`) | runtime `recorded_at=2026-07-26T19:46:24.985035Z` (`02:46:24.985 +07`) | **1.985s (~2.0s)** |

`checkout_masking=0s` trong replay JSON không được dùng làm live lead-time. Replay chọn metric timestamp ngay tại đầu incident window rồi clamp về `incident_start_ts`, nên `0s` chỉ là **replay floor**, không phải thời gian phát hiện ngoài đời. Mốc live chính thức dùng hai timestamp độc lập: fault-start trong label và `recorded_at` của incident đầu tiên trong `state/15/checkout-masking/rca-history.jsonl`.

### 3.2 Floor và baseline

| Khái niệm | Giá trị | Ý nghĩa / nguồn |
|---|---:|---|
| **Detection floor** | **0–5s** | Runtime auto-run mỗi 5 giây; nếu fault xuất hiện ngay trước một cycle thì detector có thể fire gần 0s, nếu ngay sau cycle thì phải chờ tối đa khoảng 5s. |
| **Replay floor** | **0s** | Giới hạn tính toán do replay clamp finding timestamp về `incident_start_ts`; không dùng làm live MTTD. |
| **Before baseline** | **300s** | Cửa sổ SLO/dashboard tĩnh 5 phút trước đây; dùng làm baseline so sánh MTTD. |
| **Observed live MTTD** | **~30.5s** | Trung bình hai incident thật: `(59.0 + 1.985) / 2 = 30.4925s`. |

MTTD reduction theo mốc live: `300s -> ~30.5s`, nhanh hơn khoảng **89.8%**.

## 4. Evidence screenshots saved

| Evidence | File |
|---|---|
| AIOps normal run/no incidents | `docs/mandates/15/evidence/01-aiops-run-no-incidents.png` |
| Port-forward ready | `docs/mandates/15/evidence/02-port-forward-ready.png` |
| Checkout observability baseline | `docs/mandates/15/evidence/03-grafana-checkout-observability.png` |
| SLO/resources baseline | `docs/mandates/15/evidence/04-grafana-slo-resources.png` |
| Locust baseline load | `docs/mandates/15/evidence/05-locust-load-state.png` |
| Flagd all off | `docs/mandates/15/evidence/06-flagd-all-off.png` |
| Baseline pre-capture | `docs/mandates/15/evidence/07-baseline-checkout-observability-before-capture.png` |
| Baseline SLO | `docs/mandates/15/evidence/08-baseline-slo-before-capture.png` |
| High-load Locust 400 users | `docs/mandates/15/evidence/09-high-load-locust-400-users.png` |
| High-load checkout observability | `docs/mandates/15/evidence/10-high-load-checkout-observability.png` |
| High-load flagd all off | `docs/mandates/15/evidence/11-high-load-flagd-all-off.png` |
| High-load SLO healthy | `docs/mandates/15/evidence/12-high-load-slo-healthy.png` |
| High-load AIOps no incident | `docs/mandates/15/evidence/13-high-load-aiops-no-incidents.png` |
| Recovery after high-load | `docs/mandates/15/evidence/14-recovery-locust-back-to-200.png` |
| Recovery AIOps post high-load | `docs/mandates/15/evidence/15-recovery-aiops-post-high-load.png` |
| Real incident AIOps detected | `docs/mandates/15/evidence/16-real-incident-aiops-detected.png` |
| Real incident Discord summary | `docs/mandates/15/evidence/17-real-incident-discord-summary.png` |
| Real incident checkout observability | `docs/mandates/15/evidence/18-real-incident-checkout-observability.png` |
| Real incident SLO degraded | `docs/mandates/15/evidence/19-real-incident-slo-degraded.png` |
| Masking SLO degraded | `docs/mandates/15/evidence/20-masking-slo-degraded.png` |
| Masking AIOps RCA/dedup | `docs/mandates/15/evidence/21-masking-aiops-dedup-rca.png` |
| Masking threshold fires | `docs/mandates/15/evidence/22-masking-threshold-fires.png` |
| Masking cart observability | `docs/mandates/15/evidence/23-masking-cart-observability.png` |
| Masking checkout observability | `docs/mandates/15/evidence/24-masking-checkout-observability.png` |
| Masking Discord summary | `docs/mandates/15/evidence/25-masking-discord-summary.png` |

## 4.1 Embedded proof gallery with captions

### Baseline and runtime setup

**01 - AIOps normal run / no incidents.**  
Shows the continuous AIOps run with `candidates=0`, `incidents=0`, and `root_causes=0`, proving the detector starts clean during normal telemetry.

![AIOps normal run/no incidents](./evidence/01-aiops-run-no-incidents.png)

**02 - Port-forward ready.**  
Shows Prometheus, OpenSearch, Grafana, Kubernetes proxy, and AIOps endpoints prepared for the live evidence run.

![Port-forward ready](./evidence/02-port-forward-ready.png)

**03 - Checkout observability baseline.**  
Shows checkout latency, error ratio, request rate, CPU, memory, disk, network, and pod readiness in the baseline window.

![Checkout observability baseline](./evidence/03-grafana-checkout-observability.png)

**04 - Checkout SLO / resource baseline.**  
Shows service-level health and resource panels before incidents are injected, used as the normal reference.

![SLO/resources baseline](./evidence/04-grafana-slo-resources.png)

**05 - Locust baseline load.**  
Shows the traffic generator running at the baseline load level before the high-load and incident scenarios.

![Locust baseline load](./evidence/05-locust-load-state.png)

**06 - Flagd all faults off.**  
Shows incident flags are disabled before baseline capture, so the no-alert baseline is clean.

![Flagd all off](./evidence/06-flagd-all-off.png)

**07 - Baseline checkout pre-capture.**  
Shows checkout observability immediately before the labeled baseline capture is saved.

![Baseline checkout observability before capture](./evidence/07-baseline-checkout-observability-before-capture.png)

**08 - Baseline SLO pre-capture.**  
Shows checkout SLO remains healthy before baseline capture, supporting the expected no-incident label.

![Baseline SLO before capture](./evidence/08-baseline-slo-before-capture.png)

### High-load healthy no-alert proof

**09 - High-load Locust at 400 users.**  
Shows the load-only stress case where user count is increased, but no fault flag is enabled.

![High-load Locust 400 users](./evidence/09-high-load-locust-400-users.png)

**10 - High-load checkout observability.**  
Shows checkout under high traffic so the detector can distinguish busy-but-healthy from broken.

![High-load checkout observability](./evidence/10-high-load-checkout-observability.png)

**11 - High-load flagd all off.**  
Confirms the high-load case has all incident flags disabled, so any alert would be a false positive.

![High-load flagd all off](./evidence/11-high-load-flagd-all-off.png)

**12 - High-load SLO still healthy.**  
Shows checkout SLO remains healthy during high load, supporting the expected no-incident label.

![High-load SLO healthy](./evidence/12-high-load-slo-healthy.png)

**13 - AIOps no incident during high load.**  
Shows the detector does not fire on high-load-only telemetry, proving false-positive control for busy-but-healthy traffic.

![High-load AIOps no incidents](./evidence/13-high-load-aiops-no-incidents.png)

**14 - Recovery back to baseline load.**  
Shows Locust returns from high load to the normal traffic level.

![Recovery after high-load](./evidence/14-recovery-locust-back-to-200.png)

**15 - AIOps remains clean after high load.**  
Shows no stale incident/noise remains after the high-load scenario ends.

![Recovery AIOps post high-load](./evidence/15-recovery-aiops-post-high-load.png)

### Real incident fire proof

**16 - Real incident detected by AIOps.**  
Shows the detector firing during the `checkout_real_incident` case, satisfying the live end-to-end detection proof.

![Real incident AIOps detected](./evidence/16-real-incident-aiops-detected.png)

**17 - Real incident Discord summary.**  
Shows the generated incident summary delivered to the real Discord / TF2 AIOps channel.

![Real incident Discord summary](./evidence/17-real-incident-discord-summary.png)

**18 - Real incident checkout observability.**  
Shows checkout telemetry during the incident window, including health signals used by the detector.

![Real incident checkout observability](./evidence/18-real-incident-checkout-observability.png)

**19 - Real incident SLO degraded.**  
Shows user-visible/SLO degradation during the injected incident, proving this is not just telemetry noise.

![Real incident SLO degraded](./evidence/19-real-incident-slo-degraded.png)

### Masking / no-masking proof

**20 - Masking case SLO degraded.**  
Shows the masking scenario still has real SLO impact even with unrelated load/noise present.

![Masking SLO degraded](./evidence/20-masking-slo-degraded.png)

**21 - Masking AIOps RCA and dedup.**  
Shows AIOps keeps the incident grouped/deduped and still surfaces the relevant RCA during the noisy masking case.

![Masking AIOps RCA and dedup](./evidence/21-masking-aiops-dedup-rca.png)

**22 - Masking threshold fires.**  
Shows the detector threshold/health signal fires during the masking incident window.

![Masking threshold fires](./evidence/22-masking-threshold-fires.png)

**23 - Masking cart observability.**  
Shows cart-side telemetry for the masking case, supporting the checkout dependency/root-cause context.

![Masking cart observability](./evidence/23-masking-cart-observability.png)

**24 - Masking checkout observability.**  
Shows checkout-side telemetry during masking, proving the checkout incident remains visible despite unrelated noise.

![Masking checkout observability](./evidence/24-masking-checkout-observability.png)

**25 - Masking Discord summary.**  
Shows the masking incident summary delivered to the real Discord / TF2 AIOps channel.

![Masking Discord summary](./evidence/25-masking-discord-summary.png)

## 5. Reproduction steps

1. Start port-forward:

```powershell
powershell -File scripts/port_forward.ps1
```

2. Start continuous detector:

```powershell
.\.venv\Scripts\python.exe -m uvicorn aiops.api.app:create_app --factory --host 0.0.0.0 --port 8540
```

3. Capture/replay dataset:

```powershell
.\.venv\Scripts\python.exe -m aiops.cli capture --out evaluate/dataset/mandate15_live/<case> --scenario-type <type> --expected-incident <true|false> --incident-start-ts <unix_ts> --notes "<notes>"
.\.venv\Scripts\python.exe -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json
```

4. For hidden/external replay, pass the external dataset path:

```powershell
.\.venv\Scripts\python.exe -m aiops.cli replay --dataset <external_dataset_path> --out evaluate/mandate15_hidden_report.json
```

## 6. Jira paste-ready report

```text
AI MANDATE #15 - Trustworthy Incident Detection

Service monitored:
checkout

Telemetry used:
- checkout_p95_latency_5m / checkout_p99_latency_5m
- checkout_error_rate_5m and checkout dependency error signals
- checkout_request_rate_5m as load context

Detection method:
Service-specific baseline using robust score, with health gate so high-load-only/request-rate-only deviations do not fire incidents.

Incident-summary destination:
Discord webhook / TF2 AIOps real team channel.

Evidence policy:
All detection metrics are measured on live Prometheus captures under evaluate/dataset/mandate15_live/. Synthetic/demo data is not used as Jira evidence.

Replay entry point:
.\.venv\Scripts\python.exe -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json

Case results:
- checkout_normal_baseline: expected no incident, actual no-fire, correct=true
- checkout_high_load_healthy: expected no incident, actual no-fire, correct=true
- checkout_real_incident: expected incident, actual fired, lead_time=59s, correct=true
- checkout_masking: expected incident, actual fired, live_lead_time=1.985s (~2.0s), replay_floor=0s, correct=true

Metrics:
- precision: 1.0
- recall: 1.0
- false positives: 0
- false negatives: 0
- observed live average lead time: ~30.5 seconds

MTTD before/after:
300 seconds -> ~30.5 seconds, about 89.8% faster.

Evidence links/files:
- Labeled live dataset: evaluate/dataset/mandate15_live/
- Replay report: evaluate/mandate15_live_report.json
- Submission pack: docs/mandates/15/MANDATE-15-checkout-submission.md
- Signed ADR: docs/mandates/15/ADR-DETECT-002.md
- Screenshots: docs/mandates/15/evidence/01..25
```

## 7. Checklist

- [x] Detector catches genuine incidents.
- [x] Precision, recall and lead time are measured on a labeled incident set.
- [x] A noise spike does not mask a separate subtle incident.
- [x] High-load-but-healthy traffic does not trigger a false incident.
- [x] Detection is based on deviation from the service normal baseline.
- [x] Detector runs continuously during the evidence run.
- [x] Implementation and submitted evidence version merged into `main` via [PR #141](https://github.com/tf2-team/tf2-corp-platform/pull/141), merge commit [`3ac92dd`](https://github.com/tf2-team/tf2-corp-platform/commit/3ac92dd). Current audit corrections require a follow-up commit/PR.
- [x] Incident summary is generated and delivered to a real channel.
- [x] Live MTTD before/after, 0–5s detection floor, and 300s comparison baseline are documented.
- [x] External replay entry point is available.
- [x] Signed ADR is linked; reviewed by Ngô Nguyên Phúc and Nguyễn Qúy Hưng on 2026-07-30.




