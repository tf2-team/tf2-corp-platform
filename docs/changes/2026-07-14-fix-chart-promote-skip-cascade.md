# Change: Fix chart promote jobs skipped after selective publish

## Summary

`create-chart-prod-pr` and `update-chart-dev` were cascade-skipped by GitHub Actions whenever the selective build/retag plan left one matrix side empty (job **skipped**), even when `release-ready` succeeded. Both promote jobs now use `always()` plus an explicit `needs.release-ready.result == 'success'` and environment gate so production still opens the chart values PR after a green release.

## Context

* Selective image publish (`2026-07-14-selective-image-build-retag.md`) added optional **build** and **retag** matrix jobs that are **skipped** when that side has zero services.
* `verify-ecr` and `release-ready` already used `always()` / allow-skip logic and correctly went green.
* Observed on production run [29335234337](https://github.com/tf2-team/tf2-corp-platform/actions/runs/29335234337) (`main`, `target_environment=production`, `release-ready` success for `sha-fe39d3f`): **Create chart values-prod PR** was **skipped** with empty steps (job-level `if` never allowed the job to start).
* Without the fix, full rebuilds (all 21 build, retag skipped) and pure-retag publishes also skip chart promotion.

## Before

* Chart promote job conditions:

  ```yaml
  if: >
    needs.release-ready.result == 'success' &&
    needs.prepare.outputs.target_environment == 'production'  # or development
  ```

* GitHub Actions cascade-skips jobs that sit after a path containing a **skipped** needed ancestor unless the dependent job’s `if` includes `always()` (or similar). `release-ready` ran because it had `if: always()`, but promote jobs did not, so they were skipped despite a successful gate and correct environment.

## After

* Both promote jobs use:

  ```yaml
  if: >
    always() &&
    needs.release-ready.result == 'success' &&
    needs.prepare.outputs.target_environment == '<env>'
  ```

* Production still only runs `create-chart-prod-pr`; development still only runs `update-chart-dev`.
* Failed or non-success `release-ready` still blocks promote (`result == 'success'` required).
* `docs/CICD.md` job graph and troubleshooting describe the cascade-skip failure mode and the `always()` guard.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Add `always()` on promote jobs | Required so GHA evaluates the job after skipped build/retag ancestors |
| Keep `needs.release-ready.result == 'success'` | Prevents promote when the gate failed or was cancelled |
| Keep separate env equality checks | No risk of writing prod values from a dev run (or the reverse) |
| Do not change promote step logic | Only the job-level `if` was wrong; PR/push steps remain correct |

**Alternatives rejected:**

* Making build/retag always run a no-op matrix — wastes runners and confuses logs.
* Replacing promote `needs` with only `release-ready` — still needs `always()` when `release-ready` itself has skipped needs; prepare outputs are still required for env/tag.

## Implementation Details

1. Updated `.github/workflows/build-and-push.yml`:
   * `update-chart-dev` `if` prepends `always() &&`.
   * `create-chart-prod-pr` `if` prepends `always() &&`.
   * Inline comments explain the cascade-skip reason.
2. Updated `docs/CICD.md` job graph notes and failure/recovery tables for this symptom.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — `always()` on both chart promote job conditions.

**Documentation:**

* `docs/CICD.md` — Job graph, setup failure modes, failure recovery for cascade-skip.
* `docs/changes/2026-07-14-fix-chart-promote-skip-cascade.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Runtime write target:** unchanged — chart repo via existing `CHART_REPO_TOKEN` (dev direct push / prod PR).
* No infra or chart template changes.
* After merge to `main`, the next successful production publish should open (or update) the `values-prod.yaml` promote PR.

Related: `docs/changes/2026-07-13-auto-create-prod-chart-pr.md`, `docs/changes/2026-07-14-selective-image-build-retag.md`.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change until a human merges a chart PR (prod) or Argo syncs after dev push |
| **Infrastructure** | None |
| **Deployment** | Restores automated prod chart PR / dev values push after selective or one-sided publish |
| **Performance** | None (condition-only change) |
| **Security** | Unchanged PAT and env gates |
| **Reliability** | Fixes missed promotes after green `release-ready` |
| **Cost** | None |
| **Backward compatibility** | Fully compatible; only re-enables intended jobs |
| **Observability** | Promote job summaries / PR links appear again when expected |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow condition review | Manual inspection of both promote `if` blocks | ✅ `always()` + success + env |
| Incident correlation | Run 29335234337: prepare `production`, release-ready green, create-chart-prod-pr skipped | ✅ Matches cascade-skip root cause |

### Manual Verification

* Confirmed prepare log: `target_environment=production`, `version=sha-fe39d3f`.
* Confirmed release-ready log: `Release is ready (tag=sha-fe39d3f, env=production, mode=selective)`.
* Confirmed create-chart-prod-pr job had empty steps (skipped at job `if`, not a step failure).

### Remaining Verification (Post-Merge)

1. Merge this workflow fix to `main` (path filter: workflows alone do not trigger publish — use `workflow_dispatch` **production** or a `src/**` change).
2. Confirm **Create chart values-prod PR** is green after `release-ready`.
3. Confirm chart PR updates only `values-prod.yaml` `default.image.tag`.
4. Optionally re-run the failed promote path for `sha-fe39d3f` via dispatch if that tag should still be promoted.

## Migration or Deployment Notes

1. No secret or variable changes.
2. After merge, operators can re-run **Build and push images** with `target_environment=production` if the last green production images need a chart PR without rebuilding (or push any image-affecting path change).
3. If a promote branch for the same tag already exists from a partial earlier attempt, the job force-updates the branch and reuses the open PR.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Promote runs when it should not | Low | Medium | Still requires `release-ready` success and env match |
| `always()` runs promote after cancel | Low | Low | Cancelled `release-ready` is not `success` |

**Rollback procedure:**

1. Revert the `if:` changes on `update-chart-dev` and `create-chart-prod-pr` in `.github/workflows/build-and-push.yml`.
2. Close any unwanted chart PRs opened while the fix was live.

<!-- Change trail: @hungxqt - 2026-07-14 - Fix chart promote jobs cascade-skipped after selective build/retag. -->
