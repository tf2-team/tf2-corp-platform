# ADR-DETECT-002 - Mandate #15 Trustworthy Incident Detection

Status: Accepted
Owner: Phan Duc Huy
Reviewers: Ngô Nguyên Phúc, Nguyễn Qúy Hưng
Last updated: 2026-07-27
Supersedes/extends: `docs/decisions/adr/ADR-DETECT-001.md` (Mandate #7a)
Related: `docs/mandates/15/MANDATE-15-checkout-submission.md`

## 1. Summary

This ADR approves the Mandate #15 evidence approach for the `checkout` service. The detector must distinguish busy-but-healthy traffic from a real incident, avoid masking a subtle incident with unrelated noise, run continuously, and send an incident summary to a real channel.

The core detector remains the existing service-specific baseline model from ADR-DETECT-001. Mandate #15 adds a replay gate and evidence policy:

- replay must run on labeled live Prometheus captures;
- load-only deviations are context, not incidents;
- a case fires only when baseline deviation crosses a health signal such as error-rate, user-visible latency, or readiness;
- incident summaries are delivered through the existing notification adapter.

## 2. Decision

Use `checkout` as the monitored service for Mandate #15.

Telemetry:

- checkout latency: `checkout_p95_latency_5m`, `checkout_p99_latency_5m`;
- checkout/dependency error rate: `checkout_error_rate_5m`, `payment_error_rate_5m`, `cart_error_rate_5m`;
- load context: `checkout_request_rate_5m` and related request-rate signals.

Detection method:

- robust baseline deviation per signal;
- health gate in replay so request-rate/socket/cpu increases alone do not fire an incident;
- incident windows can be replayed from `incident_start_ts`, so the detector is not dependent on the final sample only.

Incident-summary destination:

- Discord webhook / TF2 AIOps real team channel.

External replay entry point:

```powershell
.\.venv\Scripts\python.exe -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json
```

## 3. Evidence Results

Live dataset:

```text
evaluate/dataset/mandate15_live/
```

Replay report:

```text
evaluate/mandate15_live_report.json
```

Measured results:

| Metric | Value |
|---|---:|
| Labeled cases | 4 |
| Precision | 1.0 |
| Recall | 1.0 |
| False positives | 0 |
| False negatives | 0 |
| Replay average lead time | 29.5 seconds (includes masking replay floor `0s`) |

Case results:

| Case | Expected | Actual |
|---|---|---|
| checkout_normal_baseline | no incident | no-fire |
| checkout_high_load_healthy | no incident | no-fire |
| checkout_real_incident | incident | fired |
| checkout_masking | incident | fired |

MTTD / lead-time contract:

| Measurement | Value | Source / interpretation |
|---|---:|---|
| Before baseline | 300 seconds | Previous static/manual 5-minute SLO/dashboard detection window. |
| Detection floor | 0–5 seconds | Runtime cadence is 5s; this is the theoretical scheduling bound, not observed MTTD. |
| Masking replay floor | 0 seconds | Replay clamp artifact; not accepted as live lead-time. |
| Masking observed live lead-time | 1.985 seconds (~2.0s) | Fault start epoch `1785095183` to first runtime incident record `2026-07-26T19:46:24.985035Z`. |
| Observed live MTTD | ~30.5 seconds | `(real incident 59.0s + masking 1.985s) / 2`. |

Observed MTTD reduction: `300s -> ~30.5s`, about `89.8%` faster. The raw replay report remains reproducible and may show `29.5s`; submission claims use the reconciled live timestamps above.

## 4. Consequences

Positive:

- high-load healthy traffic no longer causes a replay false positive;
- masking case still fires on checkout/cart health signals;
- evidence is reproducible through one replay command;
- Discord summary evidence satisfies the real-channel requirement.

Tradeoffs:

- replay now treats pure resource/load deviations as context unless paired with a health signal;
- CPU/memory-only incidents should be added as a separate saturation policy if Mandate scope expands beyond checkout latency/error health.

## 5. Safety / Out Of Scope

- No production auto-remediation is approved by this ADR.
- No mutation of `flagd` or Kubernetes state by the detector is required for the evidence run.
- Synthetic/demo datasets are out of scope for Jira evidence.

## 6. Sign-off

| Role | Name | Date | Status |
|---|---|---|---|
| Owner | Phan Đức Huy | 2026-07-30 | Done |
| Reviewer | Ngô Nguyên Phúc, Nguyễn Qúy Hưng | 2026-07-30 | Approved |
