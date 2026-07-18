# Change: Fix chart promote tag regex for values-prod layout

## Summary

Production chart promotion failed after `release-ready` because the in-place updater for `default.image.tag` required `default:` to be immediately followed by `image:`. Chart `values-prod.yaml` now places lifecycle keys under `default:` before `image:`, so the rigid regex never matched. The promote scripts for both prod and dev now allow indented comments and sibling keys before `image:` / `tag:`.

## Context

Job **Create chart values-prod PR** on platform run after checkout image fix:

```text
Error: Could not locate default.image.tag under default.image in values-prod.yaml
exit code: 1
```

Images had already published successfully; only the chart PR step failed. Directive #3 maintenance resilience added `terminationGracePeriodSeconds` / `preStopSleepSeconds` (and comments) under `default:` above `image:` in `values-prod.yaml`.

## Before

Updater regex (prod and dev):

```text
^default:
  image:
    repository: ...
    # optional comments only
    tag: "..."
```

Current chart `values-prod.yaml` shape:

```yaml
default:
  # DIRECTIVE #3 ...
  terminationGracePeriodSeconds: 30
  preStopSleepSeconds: 10
  image:
    repository: ...
    tag: "sha-..."
```

## After

Flexible regex (prod and dev):

```text
^default:
  <any indented lines, non-greedy>
  image:
  <any indented lines, non-greedy>
    tag: "..."
```

Still rewrites only the quoted `default.image.tag` scalar and preserves surrounding layout.

## Technical Design Decisions

* Keep regex-based in-place edit (no yq) to preserve comments and avoid dependency changes.
* Share the same pattern for `values-dev.yaml` and `values-prod.yaml` so future sibling keys under `default:` do not break either path.
* Non-greedy indented skips stop at the first `image:` / `tag:` under `default`, avoiding later nested `image:` keys under `components`.

## Implementation Details

1. Updated Python snippets in `update-chart-dev` and `create-chart-prod-pr`.
2. Validated new pattern against local chart `values-prod.yaml` (old: no match; new: match + single replacement) and `values-dev.yaml` (still matches).
3. Documented failure symptom in `docs/CICD.md` recovery/troubleshooting tables.

## Files Changed

**CI:**

* `.github/workflows/build-and-push.yml` — Flexible `default.image.tag` locate/replace for dev and prod promote jobs.

**Documentation:**

* `docs/CICD.md` — Failure recovery and troubleshooting rows for this error.
* `docs/changes/2026-07-15-fix-chart-promote-tag-regex.md` — This change record.

## Dependencies and Cross-Repository Impact

* Depends on chart repo layout of `values-prod.yaml` / `values-dev.yaml` continuing to keep a quoted `default.image.tag` under `default.image`.
* No chart commit required for the fix; re-run the failed promote job (or full production publish) after this platform fix is on `main`.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No change |
| **Deployment** | Restores automated prod chart PR / dev tag push after image publish |
| **Performance** | None |
| **Security** | None (still PAT-gated cross-repo write; still no auto-merge on prod) |
| **Reliability** | Unblocks GitOps promote after release-ready |
| **Cost** | None |
| **Backward compatibility** | Still works with the older `default:` → `image:` layout |
| **Observability** | Same job summaries |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Regex vs local `values-prod.yaml` | Python one-off: old match False, new match True, `n==1` | ✅ Pass |
| Regex vs local `values-dev.yaml` | Python one-off match | ✅ Pass |

### Manual Verification

* Confirmed CI log error matches rigid regex vs current prod overlay layout.

### Remaining Verification (Post-Merge)

1. Re-run **Create chart values-prod PR** (or full Build and push on production) after merge.
2. Confirm chart PR updates only `values-prod.yaml` `default.image.tag`.

## Migration or Deployment Notes

1. Merge this platform workflow fix to `main`.
2. Re-run the failed promote job from the green `release-ready` run, or re-run **Build and push images** for production (retag/build may re-run; ECR tags may already exist).

```cmd
REM After merge: re-run failed job in GitHub Actions UI, or:
REM workflow_dispatch Build and push images → production
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Non-greedy match hits wrong `tag:` | Low | Medium | Pattern anchors on top-level `default:` then first `  image:`; verify PR diff |
| Unquoted tag scalar in chart | Low | Medium | Chart contract keeps quoted tags; error remains explicit if shape changes again |

**Rollback procedure:**

```cmd
cd /d techx-corp-platform
git revert <this-commit-sha>
```

<!-- Change trail: @hungxqt - 2026-07-15 - Document flexible chart promote tag regex for values-prod layout -->
