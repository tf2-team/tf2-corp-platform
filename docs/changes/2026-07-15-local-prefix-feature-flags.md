# Change: `local-*` feature flag twins + dual consumption

## Summary

Every demo chaos flag now has a `local-<name>` twin in `src/flagd/demo.flagd.json`. Application services evaluate **BTC original OR local twin** (booleans) or **max(original, local)** (numbers/ints) so team UI toggles under dual-source flagd inject faults without overriding BTC keys.

## Context

* Prod flagd dual-sources local file + BTC HTTP with HTTP last: shared original keys always follow BTC.
* Local `/feature` UI writes only the file source, so toggling `paymentFailure` etc. did not affect runtime while BTC held OFF.
* Team needs self-test injection while preserving BTC authority on original names.

## Before

* Flag document contained only original keys.
* Each service read a single flag key via OpenFeature.
* recommendation `check_feature_flag(flag_name)` ignored `flag_name` and always read `recommendationCacheFailure`.

## After

* Flag document includes 15 `local-*` twins (same variants, default OFF, description `(team local) …`).
* Consumers dual-read original + `local-` twin with OR / max semantics.
* recommendation helper fixed to use `flag_name` and dual-read.

## Technical Design Decisions

* **Prefix `local-`** + original key (e.g. `local-paymentFailure`) for clear UI labeling.
* **Application-layer OR/max** rather than reversing flagd merge (keeps BTC absolute on original keys).
* **Keep original keys** in the local file for Compose/offline; prod still overlays originals from BTC.
* Do not push `local-*` to BTC central document.

## Implementation Details

1. Extended `src/flagd/demo.flagd.json` with all `local-*` twins.
2. Updated dual-read in payment, checkout, product-catalog, cart, ad, recommendation, product-reviews, llm, email, load-generator, frontend.
3. Fixed recommendation `check_feature_flag` parameter usage.

## Files Changed

**Flags:**

* `src/flagd/demo.flagd.json` — Original + `local-*` definitions.

**Services:**

* `src/payment/charge.js` — max paymentFailure / local-paymentFailure
* `src/checkout/main.go` — helper OR / max
* `src/product-catalog/main.go` — OR productCatalogFailure
* `src/cart/src/services/CartService.cs` — OR cartFailure
* `src/cart/src/services/HealthCheckService.cs` — OR failedReadinessProbe
* `src/ad/.../AdService.java` — isFlagEnabled helper
* `src/recommendation/recommendation_server.py` — dual-bool + bugfix
* `src/product-reviews/product_reviews_server.py` — dual-bool
* `src/llm/app.py` — dual-bool
* `src/email/email_server.rb` — max emailMemoryLeak
* `src/load-generator/locustfile.py` — max flood flag
* `src/frontend/components/ProductCard/ProductCard.tsx` — max imageSlowLoad

**Documentation:**

* `docs/changes/2026-07-15-local-prefix-feature-flags.md` — this record.

Change trail exception for `src/flagd/demo.flagd.json`: JSON does not support comments. Attribution @hungxqt.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-15-local-prefix-feature-flags.md` (ConfigMap flag file + ops notes).
* Requires image bake for all modified services + chart image tag promote for cluster effect.
* Chart ConfigMap must include matching `local-*` keys (synced `flagd/demo.flagd.json`).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Team can inject via `local-*`; BTC originals still work; either ON activates |
| **Infrastructure** | No change |
| **Deployment** | Platform images + chart flag ConfigMap |
| **Security** | No new secrets; `/feature` still internal |
| **Reliability** | Extra OpenFeature reads (~2×) per check |
| **Backward compatibility** | Original keys unchanged; default local OFF |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout unit tests | `go test ./...` in `src/checkout` | Pass |
| Product-catalog unit tests | `go test ./...` in `src/product-catalog` | Pass (no test files) |
| Cart unit tests | `dotnet test` in `src/cart` | Skipped locally (SDK 9 cannot target net10) |
| Flag JSON | 30 flags, 15 `local-*`, platform==chart | Pass |

### Manual Verification

* Toggle `local-paymentFailure` to `100%` with BTC OFF → payment faults.
* BTC `paymentFailure` ON with local OFF → faults still appear.
* Both OFF → baseline healthy.

### Remaining Verification (Post-Merge)

* Full bake + promote; smoke checkout path with local-paymentFailure.

## Migration or Deployment Notes

1. Merge platform; bake/push images for changed services.
2. Promote chart tag; ensure chart flag JSON with `local-*` is deployed.
3. Restart flagd if ConfigMap emptyDir was copied only at init (flag schema add).
4. Self-test via `/feature` using **`local-*` names only**.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Operators toggle original key in UI | Medium | Low | Docs; use `local-*` |
| Both sources partially ON raises max severity | Low | Low | Acceptable for chaos |

**Rollback procedure:** Revert dual-read and optional `local-*` JSON; redeploy images.

<!-- Change trail: @hungxqt - 2026-07-15 - local-* flag twins and dual consumption across services. -->
