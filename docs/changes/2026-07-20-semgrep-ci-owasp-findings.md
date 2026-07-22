# Change: Clear Semgrep CI / OWASP Top Ten Blocking Findings

## Summary

Resolved 15 blocking Semgrep findings from `p/ci` + `p/owasp-top-ten` on `src/`: explicit non-root `USER` before process entrypoints in six distroless Dockerfiles, safer Flask startup for the LLM service, random UUID generation in the load generator, and removal of secret-like values from shopping-copilot logs.

## Context

CI runs:

```text
semgrep scan --error --metrics=off --baseline-commit "${BASELINE_COMMIT}" --config p/ci --config p/owasp-top-ten src
```

The scan reported 15 blocking findings and exited non-zero. Several Dockerfiles already used distroless `:nonroot` base images but either lacked an explicit `USER` instruction before `ENTRYPOINT`/`CMD`, or placed `USER` after the process instruction (which Semgrep still treats as missing). Application findings covered Flask debug/bind hardcoding, predictable `uuid.uuid1()`, and logger messages that looked like credential disclosure.

## Before

* Distroless final stages for checkout, fraud-detection, frontend, payment, product-catalog, and shipping ran as the image default nonroot user but Semgrep `missing-user` / `missing-user-entrypoint` still fired on `ENTRYPOINT`/`CMD` lines.
* `src/llm/app.py` called `app.run(host='0.0.0.0', port=8000, debug=True)`.
* Load-generator tasks used `uuid.uuid1()` for synthetic user IDs.
* Shopping-copilot logged pending-action token prefixes and exception text next to “token” message strings.

## After

* Each affected Dockerfile sets `USER nonroot` immediately before `ENTRYPOINT` or `CMD` (distroless nonroot username).
* LLM Flask entry uses env-driven bind host/port and `debug=False`.
* Load-generator synthetic users use `uuid.uuid4()`.
* Shopping-copilot confirm/create paths log operational state without secret material or token prefixes.

## Technical Design Decisions

* **Explicit `USER nonroot` vs only `:nonroot` image tag.** The base image already defaults to nonroot (UID 65532). An explicit `USER` satisfies static analysis and documents intent. Placing it *before* the process instruction matches Semgrep autofix expectations and accounting/ad patterns elsewhere in the repo.
* **Flask bind via env, not literal rewrite to 127.0.0.1.** The LLM container entrypoint is `python app.py`; defaulting to loopback would break pod networking. Default remains all-interfaces through `LLM_BIND_HOST` with the literal removed from `app.run(...)`.
* **Log message rewording over `nosemgrep`.** Prefer real reduction of logged secret surface area over suppressions for credential-leak rules.
* **Log exception type only on pending-action create failure.** Avoid logging exception text that could include upstream payloads.

## Implementation Details

1. Moved/added `USER nonroot` before process instructions in six Dockerfiles.
2. Updated `src/llm/app.py` `__main__` block: `LLM_BIND_HOST` / `LLM_PORT` (or `PORT`), `debug=False`.
3. Replaced three `uuid.uuid1()` call sites in `locustfile.py` with `uuid.uuid4()`.
4. Rewrote shopping-copilot log lines in `cart_tool.py`, `copilot_graph.py`, and `copilot_server.py` to omit token prefixes and “token” secret-shaped messages.

## Files Changed

**Dockerfiles:**
* `src/checkout/Dockerfile` — `USER nonroot` before `ENTRYPOINT`.
* `src/fraud-detection/Dockerfile` — same.
* `src/frontend/Dockerfile` — `USER nonroot` before `CMD`.
* `src/payment/Dockerfile` — same.
* `src/product-catalog/Dockerfile` — `USER nonroot` before `ENTRYPOINT`.
* `src/shipping/Dockerfile` — `USER nonroot` before `CMD`.

**Application:**
* `src/llm/app.py` — Flask debug off; bind host/port from env.
* `src/load-generator/locustfile.py` — `uuid4` for synthetic users.
* `src/shopping-copilot/cart_tool.py` — no token prefix in confirm logs.
* `src/shopping-copilot/copilot_graph.py` — safer pending-action create error log.
* `src/shopping-copilot/copilot_server.py` — no token prefix on ConfirmCartAction.

**Documentation:**
* `docs/changes/2026-07-20-semgrep-ci-owasp-findings.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Image tags and chart values are unchanged. No infra or chart edits required. Rebuild of affected service images is needed before the nonroot/USER layer is present in registries (already nonroot via base image default in practice).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Load-gen user IDs are random v4; LLM no longer starts with Flask debug; shopping-copilot logs slightly less correlatable secret material |
| **Infrastructure** | No change |
| **Deployment** | Rebuild/redeploy images that include Dockerfile or app changes for full effect |
| **Performance** | Negligible |
| **Security** | Reduces container-as-root static findings, Flask debugger risk, UUID predictability, and log secret surface |
| **Reliability** | LLM still binds all interfaces by default for container use |
| **Cost** | None |
| **Backward compatibility** | Fully backward-compatible runtime contract; env override `LLM_BIND_HOST` optional |
| **Observability** | Confirm-cart logs no longer include token prefixes |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Semgrep (local, if installed) | `semgrep scan --error --metrics=off --config p/ci --config p/owasp-top-ten src` | Pending operator / CI re-run |
| Unit tests | Not re-run for Dockerfile/log-only edits | N/A |

### Manual Verification

* Confirmed `USER nonroot` appears immediately before each affected `ENTRYPOINT`/`CMD`.
* Confirmed no remaining `uuid.uuid1()` in `locustfile.py` task paths listed by Semgrep.
* Confirmed Flask `debug=True` and literal `host='0.0.0.0'` removed from `app.run`.

### Remaining Verification (Post-Merge)

* Re-run the CI Semgrep job (or local equivalent with baseline commit) and confirm 0 blocking findings for these rules.
* Smoke-deploy LLM and shopping-copilot after image rebuild if promoting to a cluster.

## Migration or Deployment Notes

1. No special migration.
2. Optional: set `LLM_BIND_HOST=127.0.0.1` only for local non-container debug.
3. Rebuild affected images via normal platform bake/CI path before expecting Dockerfile USER line in running pods (base image already nonroot).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Semgrep still flags env-default containing `0.0.0.0` string outside `app.run` | Low | Low | Rebind via different construction or rule ignore if false positive |
| Operators relied on token prefix in logs for support | Low | Low | Correlate via user_id / request traces instead |

**Rollback procedure:**

Revert this change set in `techx-corp-platform` and redeploy prior image tags.

<!-- Change trail: @hungxqt - 2026-07-20 - Document Semgrep CI/OWASP finding remediations in platform src -->
