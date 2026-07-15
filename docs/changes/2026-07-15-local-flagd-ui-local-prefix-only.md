# Change: Local flagd File/UI — `local-*` Keys Only

## Summary

Removed all non-`local-*` feature flag definitions from `src/flagd/demo.flagd.json` so local flagd and flagd-ui (`/feature`) expose only team self-test twins. Application dual-read of BTC original + `local-*` is unchanged.

## Context

* `local-*` twins and dual-consume were added so team UI toggles work under dual-source flagd (BTC HTTP wins on original keys).
* The local file still listed both original and `local-*` names, so the UI showed non-authoritative BTC-named toggles.

## Before

* `demo.flagd.json` had 30 flags: 15 original + 15 `local-*`.

## After

* File has **15** flags, all `local-*` (same variants, default OFF, `(team local)` descriptions).
* Compose/local flagd-ui shows only team keys.
* Apps still dual-read original keys (from BTC HTTP in cluster, or OpenFeature defaults offline).

## Technical Design Decisions

* **File-level filter** — remove originals from the shared JSON rather than filter in flagd-ui code.
* **Keep dual-read in services** — BTC originals remain first-class when present from central source.
* **Sync chart ConfigMap** — chart `flagd/demo.flagd.json` updated in matching chart change.

## Implementation Details

1. Rewrote `src/flagd/demo.flagd.json` to only `local-*` entries.

## Files Changed

**Flags:**
* `src/flagd/demo.flagd.json` — Non-`local-*` flags removed (JSON; no comment trail).

**Documentation:**
* `docs/changes/2026-07-15-local-flagd-ui-local-prefix-only.md` — This change record.

Change trail exception for `src/flagd/demo.flagd.json`: JSON does not support comments. Attribution @hungxqt.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-15-local-flagd-ui-local-prefix-only.md` (ConfigMap + chart version).
* No image rebuild required for flag JSON alone (file mount / ConfigMap). Dual-read app images already required for `local-*` effect.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Local Compose: inject only via `local-*`; original keys default OFF unless another source provides them |
| **Deployment** | Restart local flagd/flagd-ui or remount volume after file change |
| **Security** | UI no longer presents BTC original key names |
| **Backward compatibility** | Toggle `local-*` only (previous original-name UI path removed from local file) |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Flag keys | Parse JSON | ✅ 15 keys, all start with `local-` |

### Manual Verification

* `make start` / existing stack: open `/feature` — only `local-*` listed.
* Toggle `local-paymentFailure` → payment injects (with dual-read images).

### Remaining Verification (Post-Merge)

* Cluster: chart ConfigMap sync + flagd restart (chart change).

## Migration or Deployment Notes

1. Update file under `src/flagd/demo.flagd.json` (Compose bind-mount refreshes automatically for flagd-ui write path; restart flagd if needed).
2. Chart deploy for cluster ConfigMap (see related chart change).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Scripts assume original keys in local file | Low | Low | Update monitors to BTC URL or `local-*` |

**Rollback procedure:** Restore full original+local twin JSON from git history.

<!-- Change trail: @hungxqt - 2026-07-15 - Local flagd file/UI exposes local-* keys only. -->
