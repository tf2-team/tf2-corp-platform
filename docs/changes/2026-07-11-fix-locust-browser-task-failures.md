# Change: Fix Locust WebsiteBrowserUser 100% TASK Failures

## Summary

Fixed Playwright browser load-gen tasks (`add_product_to_cart`, `open_cart_page_and_change_currency`) that were failing at 100% with near-zero response times. The root cause was setting `self.tracer` after `PlaywrightUser.__init__`, which shallow-copies the user into `sub_users` before that assignment, so every task ran on a copy without `tracer` and raised `AttributeError` outside the task `try/except`.

## Context

Locust stats for browser traffic showed:

* `WebsiteBrowserUser.add_product_to_cart` — all requests failed (e.g. 217/217)
* `WebsiteBrowserUser.open_cart_page_and_change_currency` — all requests failed (e.g. 183/183)
* Median response time ~0.01s, while a successful task must wait at least ~2s

This matches an immediate exception before meaningful browser work, not a slow selector timeout or backend 5xx.

`locust-plugins` `PlaywrightUser` records each `@pw` task as a Locust request of type `TASK`. Unhandled exceptions in the task body mark the TASK as failed.

## Before

`WebsiteBrowserUser` set tracing state in `__init__` after `super()`:

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)  # PlaywrightUser: sub_users = [copy.copy(self)]
    self.tracer = trace.get_tracer(__name__)  # only on parent, not on sub_users
```

Tasks then used `self.tracer` on the **sub_user** copy:

```python
with self.tracer.start_as_current_span(...):  # AttributeError — no tracer on copy
    try:
        ...
    except Exception as e:
        ...
```

The `AttributeError` happened **outside** the `try/except`, so `@pw` logged every TASK as failed.

Secondary issues:

* No user weights → ~50% of Locust users were Playwright browsers (heavy CPU/RAM)
* `add_product_to_cart` clicked product text immediately after `domcontentloaded`, racing client-side product list rendering

## After

* Tracer is obtained inside each browser task via `trace.get_tracer(__name__)` (no post-`super()` instance attrs needed on Playwright users)
* `WebsiteUser.weight` default `9`, `WebsiteBrowserUser.weight` default `1` (overridable via `LOCUST_HTTP_USER_WEIGHT` / `LOCUST_BROWSER_USER_WEIGHT`)
* `add_product_to_cart` waits for a successful `RoofBinoculars.jpg` response before clicking the product

## Technical Design Decisions

* **Get tracer per task instead of fixing `__init__` copy semantics** — matches upstream OpenTelemetry demo; avoids fighting `PlaywrightUser`’s `copy.copy` sub-user model.
* **Default 9:1 HTTP:browser weight** — Playwright Chromium is memory-heavy; equal weight with `LOCUST_USERS=10` can stress the load-generator pod (chart limit 1500Mi).
* **Wait on product image response** — product cards are React-rendered after catalog/image fetch; `domcontentloaded` alone is not enough.

Alternatives considered:

* Assign tracer before `super()` — not possible; `PlaywrightUser.__init__` requires full User init first, then copies.
* Monkey-patch `sub_users` after setting tracer — fragile vs library updates.

## Implementation Details

1. Removed `WebsiteBrowserUser.__init__` that set `self.tracer` after `super()`.
2. Both browser tasks now call `tracer = trace.get_tracer(__name__)` at the start of the method body.
3. Added env-configurable weights for HTTP vs browser user classes.
4. Added `page.wait_for_event` for `/images/products/RoofBinoculars.jpg` status 200 before clicking “Roof Binoculars”.

## Files Changed

**Load generator:**

* `src/load-generator/locustfile.py` — Fix Playwright sub-user tracer usage; add user weights; wait for product image before click.

**Documentation:**

* `docs/changes/2026-07-11-fix-locust-browser-task-failures.md` — This change record.

## Dependencies and Cross-Repository Impact

None for code correctness. Operators may still tune chart env if needed:

* `techx-corp-chart` `components.load-generator.env` already has `LOCUST_BROWSER_TRAFFIC_ENABLED`, `LOCUST_USERS`, etc.
* Optional follow-up: set `LOCUST_HTTP_USER_WEIGHT` / `LOCUST_BROWSER_USER_WEIGHT` in values if non-default ratios are desired.

No chart change is required for the bugfix itself (defaults are in the locustfile).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Browser Locust tasks no longer fail immediately with missing `tracer`; synthetic browser traffic can complete |
| **Infrastructure** | No infra change; browser weight default reduces Chromium concurrency vs equal-weight previous behavior |
| **Deployment** | Rebuild/redeploy `load-generator` image |
| **Performance** | Fewer accidental browser users under default weights; lower loadgen memory pressure |
| **Reliability** | TASK fail rate for browser flows should drop from ~100% for the AttributeError case |
| **Backward compatibility** | Fully compatible; env weights are optional |
| **Observability** | Browser spans still emitted via local `get_tracer` calls |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Syntax | Python parse of `locustfile.py` | Not run in CI here (no loadgen unit tests) |
| Unit tests | N/A for load-generator | N/A |

### Manual Verification

* Static analysis of `locust-plugins` `PlaywrightUser`: confirms `sub_users = [copy.copy(self)]` inside `__init__` and that `@pw` runs the task on each sub-user.
* Failure signature matched: type `TASK`, ~100% fails, median ~0.01s (exception before `wait_for_timeout(2000)`).
* Confirmed frontend selectors still valid (`p` product name, `button` Add To Cart, `[name="currency_code"]`, product “Roof Binoculars”).

### Remaining Verification (Post-Merge)

1. Rebuild and deploy `load-generator`.
2. Open Locust UI (`/loadgen/`) and confirm `WebsiteBrowserUser.*` TASK failure rate is near zero (or only reflects real UI/backend errors).
3. Check load-generator logs for absence of `AttributeError: ... no attribute 'tracer'`.
4. If stress testing with many users, consider `LOCUST_BROWSER_TRAFFIC_ENABLED=false` per REL-06 guidance.

## Migration or Deployment Notes

1. Build/push new `load-generator` image including this `locustfile.py`.
2. Roll out the load-generator deployment (Helm upgrade or compose recreate).
3. Optional env:
   * `LOCUST_HTTP_USER_WEIGHT` (default `9`)
   * `LOCUST_BROWSER_USER_WEIGHT` (default `1`)
4. For pure API stress tests, set `LOCUST_BROWSER_TRAFFIC_ENABLED=false`.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Remaining failures from real SPA/backend issues (empty catalog, currency API slow, OOM) | Medium | Low | Inspect Locust failures tab + loadgen logs; disable browser traffic if needed |
| Weight change reduces browser coverage vs previous 50/50 | Low | Low | Raise `LOCUST_BROWSER_USER_WEIGHT` if more browser traffic is desired |
| Image wait times out if image-provider down | Low | Medium | Failures are caught and logged; fix image-provider / catalog |

**Rollback procedure:**

Redeploy previous `load-generator` image tag, or revert `src/load-generator/locustfile.py` to the prior commit and rebuild.
