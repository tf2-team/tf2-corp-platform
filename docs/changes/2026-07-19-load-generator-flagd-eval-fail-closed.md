# Change: Load-generator flagd evaluation fail-closed

## Summary

Hardened the Locust load-generator's OpenFeature integer flag reads so failures while evaluating `loadGeneratorFloodHomepage` / `local-loadGeneratorFloodHomepage` no longer crash `flood_home` tasks. Evaluation errors now log a warning and return the default `0` (no flood).

## Context

* Locust tasks were failing with:
  `UnboundLocalError: cannot access local variable 'flag_evaluation' where it is not associated with a value`
  inside `openfeature/client.py` `evaluate_flag_details` (finally → `after_all_hooks`).
* Stack path: `flood_home` → `get_flagd_value` → `client.get_integer_value` → SDK evaluate.
* Root cause is an openfeature-sdk edge case: if a `BaseException` (for example gevent `Timeout` / `GreenletExit` under Locust) escapes before `flag_evaluation` is assigned, the `finally` block still references that local and raises `UnboundLocalError`, masking the original error and failing the task.
* Ordinary provider/network errors usually return the default; this path surfaces under greenlet cancellation or other BaseException during OFREP evaluation.

## Before

* `get_flagd_value` called `client.get_integer_value` twice with no local guard.
* Any SDK evaluation crash (including the UnboundLocalError above) failed the entire `flood_home` task.

## After

* `_read_integer_flag` wraps each integer evaluation in `try/except Exception`, coerces the value to `int`, and returns the default on failure.
* `get_flagd_value` still dual-reads BTC + `local-` keys with `max(...)`.
* Flood behavior stays fail-closed: evaluation failure means flood count `0`, not task error spam.

## Technical Design Decisions

* **Application-layer fail-closed** rather than patching site-packages openfeature-sdk (upstream-owned; transitive dependency).
* **Catch `Exception` only** so true process/greenlet lifecycle signals that remain as BaseException are not swallowed when the SDK does not convert them.
* **Per-key isolation** so a failure on the BTC key still allows the local twin read (and vice versa).
* Alternatives rejected: removing TracingHook (loses flag eval spans); switching off OFREP (other services and env wiring expect FLAGD_OFREP_PORT).

## Implementation Details

1. Added `_read_integer_flag(client, flag_key, default=0)` with defensive evaluation + warning log.
2. Updated `get_flagd_value` to use that helper for both keys.
3. Documented the SDK `flag_evaluation` finally-block interaction in a short code comment.

## Files Changed

**Application:**

* `src/load-generator/locustfile.py` — Fail-closed integer flag reads for flood homepage dual-key evaluation.

**Documentation:**

* `docs/changes/2026-07-19-load-generator-flagd-eval-fail-closed.md` — This change record.

## Dependencies and Cross-Repository Impact

* None for chart/infra code.
* Runtime still requires reachable flagd OFREP (`FLAGD_HOST` + `FLAGD_OFREP_PORT`) for flood injection to work; this change only prevents evaluation failures from breaking Locust tasks.
* Rebuild/redeploy the `load-generator` image for the fix to take effect in cluster or Compose.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | `flood_home` no longer fails hard on flagd/OpenFeature evaluation errors; flood stays off until a successful positive integer read |
| **Infrastructure** | No change |
| **Deployment** | Requires load-generator image rebuild and roll |
| **Performance** | Negligible; same two OFREP reads when healthy |
| **Security** | No change |
| **Reliability** | Reduces Locust task error rate when flagd is slow, cancelled, or SDK hits the finally-block bug |
| **Backward compatibility** | Same dual-read max semantics when evaluation succeeds |
| **Observability** | Warning logs on failed key evaluation; TracingHook retained |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Syntax | Manual review of `locustfile.py` change | ✅ Reviewed |
| SDK repro | Local openfeature-sdk 0.10.0: `BaseException` during resolve → exact UnboundLocalError at `evaluate_flag_details` finally | ✅ Confirmed root cause |

### Manual Verification

* Confirmed connection-refused OFREP path returns default `0` without crashing when only Exception paths fire.
* Confirmed KeyboardInterrupt/BaseException path produces the reported UnboundLocalError at client.py line ~847.

### Remaining Verification (Post-Merge)

1. Rebuild and deploy `load-generator` image.
2. Run Locust; confirm `flood_home` tasks no longer report UnboundLocalError.
3. Toggle `local-loadGeneratorFloodHomepage` on and confirm flood still works when flagd OFREP is healthy.

## Migration or Deployment Notes

```cmd
cd /d techx-corp-platform
REM rebuild load-generator (or full release bake), then promote chart image tag per usual pipeline
```

No flagd ConfigMap or chart template changes required.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Masked flagd outages (flood stays off without task errors) | Medium | Low | Warning logs; operators still use flagd/OFREP health and flood metrics |
| Real flood injection missed while flagd is down | Low | Medium | Same as before for true flagd outage; only error surfacing changed |

**Rollback procedure:**

Revert `src/load-generator/locustfile.py` to the previous `get_flagd_value` implementation and redeploy the load-generator image.

<!-- Change trail: @hungxqt - 2026-07-19 - Fail-closed load-generator flagd integer evaluation under Locust. -->
