# Change: Remove flag soft-remediation; keep dual-read local-* inject

## Summary

Checkout no longer invents a successful payment (`deferred-payment-*`) or swallows cart EmptyCart failures after flag inject. Payment failure flags (BTC or `local-paymentFailure`) and cart failure flags now fail `PlaceOrder`. Fraud-detection dual-reads `local-*` integer twins. Local flag JSON remains `local-*` only, variants aligned to BTC.

## Context

* Team toggles `local-paymentFailure=100%` expected all charges/orders to fail; payment injected correctly but checkout containment soft-succeeded.
* Same class of issue: `PlaceOrder` ignored `emptyUserCart` errors so `cartFailure` / `local-cartFailure` did not fail the order.
* Fraud-detection only read BTC `kafkaQueueProblems`, so `local-kafkaQueueProblems` did not delay the consumer.
* Soft remediation conflicted with dual-source local self-test design.

## Before

* `chargeCard`: after 2× gold/`Invalid token` errors, returned synthetic `deferred-payment-*` TX with `nil` error.
* Payment inject errors were treated as retryable (up to 8 attempts) before degrade.
* `PlaceOrder`: `_ = emptyUserCart(...)` discarded cleanup failures.
* Fraud-detection: `getIntegerValue(ff)` only (no `local-` twin).

## After

* `chargeCard`: no deferred TX; charge errors always surface as `PlaceOrder` failure.
* Gold / Invalid-token inject is **non-retryable** (fail fast under 100% paymentFailure).
* `PlaceOrder`: EmptyCart failure after retries returns gRPC Internal error.
* Fraud-detection: `max(BTC, local-*)` for integer flags (covers `kafkaQueueProblems` and `fraud_threshold_score` if a local twin exists).
* `src/flagd/demo.flagd.json`: 15 `local-*` keys with variants/defaultVariant matching BTC originals.

## Technical Design Decisions

* **Option C (full remove containment)** chosen over contain-only-when-BTC: simpler; local and BTC paymentFailure both hard-fail checkout. Accepts SLO impact under mentor BTC `paymentFailure` windows.
* **Fail-fast on inject message** rather than 8 useless retries at 100% inject.
* **Keep EmptyCart retry loop** for transient blips; only stop ignoring the final error.
* Did **not** remove product-reviews grounding (security filter, not payment soft-success).
* Local file stays `local-*` only (UI contract); BTC originals remain HTTP-only in prod dual-source.

## Implementation Details

1. Removed `degradedPaymentTransactionID`, degrade counters, and end-of-loop soft success from `chargeCard`.
2. Extended `isRetryablePaymentChargeError` non-retryable list with inject markers.
3. `PlaceOrder` propagates `emptyUserCart` error.
4. Updated checkout unit tests; fraud-detection dual-read integers.
5. Regenerated platform `demo.flagd.json` from BTC twin definitions with `local-` prefix.

## Files Changed

**Application:**
* `src/checkout/main.go` — Remove deferred-payment containment; fail on cart cleanup.
* `src/checkout/main_test.go` — Retryability + cart cleanup expectations.
* `src/fraud-detection/src/main/kotlin/frauddetection/main.kt` — Dual-read local integer flags.

**Flags:**
* `src/flagd/demo.flagd.json` — local-* only, variants match BTC (JSON; no comment trail).

**Documentation:**
* `docs/changes/2026-07-17-remove-flag-soft-remediation.md` — This record.

Change trail exception for `src/flagd/demo.flagd.json`: JSON does not support comments. Attribution @hungxqt.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-17-local-flags-match-btc.md` (chart ConfigMap flagd file + chart version).
* Requires redeploy of **checkout** and **fraud-detection** images for code paths.
* Chart ConfigMap sync + flagd restart for updated `demo.flagd.json` (definitions only; defaults remain off).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | `paymentFailure` / `local-paymentFailure` fail PlaceOrder; `cartFailure` / `local-cartFailure` fail PlaceOrder after EmptyCart retries |
| **Infrastructure** | No change |
| **Deployment** | New checkout + fraud-detection images; chart flag ConfigMap |
| **Reliability / SLO** | BTC mentor `paymentFailure` windows will again drive checkout error rate up (by design) |
| **Backward compatibility** | Removes soft-success path; operators relying on deferred-payment must stop |
| **Observability** | No more `paymentFailure containment: deferred charge` / `app.payment.degraded` from that helper |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout unit tests | `go test ./...` in `src/checkout` | Pass |
| Local vs BTC variants | Python compare to historical BTC defs | Match (15 pairs) |
| Platform vs chart flag JSON | File equality | Match |

### Manual Verification

* With `local-paymentFailure=100%`, BTC off: payment throws; PlaceOrder returns failed to charge card (no `deferred-payment-*`).
* With `local-cartFailure=on`: EmptyCart fails → PlaceOrder Internal after retries.
* `local-kafkaQueueProblems=on`: fraud-detection logs sleep path (after image deploy).

### Remaining Verification (Post-Merge)

* Deploy checkout + fraud-detection images; promote chart; restart flagd if emptyDir stale.
* Smoke checkout with all local flags off (baseline success).

## Migration or Deployment Notes

1. Merge platform; bake/push images; promote chart image tags if required by process.
2. Merge chart flag ConfigMap (0.48.8); Argo sync; restart flagd pods so init re-copies JSON.
3. Turn off any leftover UI toggles on `local-paymentFailure` before expecting green checkout SLO.

```cmd
cd /d techx-corp-platform\src\checkout
go test ./... -count=1
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| BTC paymentFailure drops checkout SLO | High during mentor ON | Medium | Expected; roll back checkout image or re-add containment if mentor requires |
| Charge-then-EmptyCart fail leaves “paid” demo order incomplete | Low | Low | Demo payment is not real settlement; acceptable for flag fidelity |
| Stale flagd emptyDir | Medium | Low | Restart flagd after ConfigMap sync |

**Rollback procedure:**

1. Revert checkout/fraud-detection commits and redeploy previous images.
2. Revert chart flag JSON / Chart version if needed; Argo sync + flagd restart.

<!-- Change trail: @hungxqt - 2026-07-17 - Document removal of flag soft-remediation and local flag align. -->
