# Change: Auto-create production chart values PR after image publish

## Summary

After a successful production image publish (`release-ready` green), platform CI now opens a pull request on the chart repository updating `default.image.tag` in `values-prod.yaml` (base branch `main`). Production deploy still requires a human merge; the workflow does not auto-merge or call Argo CD.

## Context

* REL-09 GitOps uses a **global** `default.image.tag` for all nested services.
* Development already auto-promotes via job **update-chart-dev** (direct push to `values-dev.yaml` on `techx-dev-corp`).
* Production previously required a fully manual chart values PR after every successful publish.
* Operators want automation that still preserves production review: open the PR automatically, keep merge as the deploy gate.
* Related backlog: `docs/backlogs/2026-07-09-rel-09-gitops-argocd.md` (prod chart PR follow-up).

## Before

* Production path after `release-ready`: documentation told operators to open a **manual** PR on the chart repo for `values-prod.yaml`.
* Secret `CHART_REPO_TOKEN` was documented as **dev-only** (Contents write).
* Job graph ended with **update-chart-dev** for development; no production chart job.

## After

* New job **create-chart-prod-pr** runs only when:
  * `release-ready` succeeds, and
  * `target_environment == production`.
* The job checks out the chart repo (`vars.CHART_REPO`, base `vars.CHART_PROD_BRANCH` default `main`), updates only `default.image.tag` in `values-prod.yaml`, pushes branch `promote/prod-image-<tag>`, and opens (or updates) a PR with `gh`.
* If the tag on `main` already matches the built version, the job no-ops (no branch/PR).
* Re-runs of the same tag force-push the promote branch and update an existing open PR when present.
* Docs (`CICD.md`, `DEPLOYMENT.md`, `README.md`, REL-09 backlog) describe prod PR automation and the extra PAT permission (**Pull requests: Read and write**).

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Open PR, do not merge | Keeps human review / branch protection as the production deploy gate. |
| Reuse `CHART_REPO_TOKEN` | Same cross-repo secret as dev; avoid a second long-lived PAT. |
| Require Pull requests write | Fine-grained PATs need explicit PR permission for `gh pr create`. |
| Separate job from `update-chart-dev` | Clear env gates; no risk of writing `values-prod` from a development run. |
| Branch name `promote/prod-image-<tag>` | One branch per image tag; idempotent re-runs; easy to find/close. |
| Force-push promote branches | Disposable bot branches; re-runs must refresh tip without manual cleanup. |
| Same Python regex as dev | Preserves comments/layout; no yq dependency; matches existing `values-prod.yaml` shape. |
| No auto-merge / no Argo API | Out of scope; deploy remains GitOps merge → Argo sync. |

**Alternatives rejected:**

* Direct-push `values-prod.yaml` on `main` — bypasses required review and is unsafe for production.
* GitHub App installation — better long-term, larger operator setup; PAT matches existing dev pattern.
* Auto-merge after checks — not requested; keeps deploy intentional.

## Implementation Details

1. Extended `.github/workflows/build-and-push.yml`:
   * Header and `release-ready` summary messaging for env-specific promote paths.
   * New job `create-chart-prod-pr` after `update-chart-dev`.
2. Job steps:
   * Fail fast if `CHART_REPO_TOKEN` is missing.
   * Checkout chart at `CHART_PROD_BRANCH` with the PAT.
   * In-place update of `default.image.tag` under `default.image` in `values-prod.yaml`.
   * Commit as `github-actions[bot]`, push `promote/prod-image-<sanitized-tag>`.
   * Create or update PR via `gh` (`GH_TOKEN` = PAT); write PR URL to the job summary.
3. Optional repository variable `CHART_PROD_BRANCH` (default `main`) for Argo prod `targetRevision` mismatches.
4. Documentation and backlog acceptance updated for the automated prod PR path.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — Added `create-chart-prod-pr`; updated release-ready promotion messaging.

**Documentation:**

* `docs/CICD.md` — Job graph, secrets/vars, operator PAT steps (Contents + Pull requests), promotion flow, troubleshooting, out-of-scope (auto-merge still out).
* `docs/DEPLOYMENT.md` — Phase 0 CI/CD steps for prod PR automation.
* `README.md` — CI/CD summary for prod chart PR.
* `docs/backlogs/2026-07-09-rel-09-gitops-argocd.md` — Marked automated prod chart PR acceptance done.
* `docs/changes/2026-07-13-auto-create-prod-chart-pr.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Runtime write target:** chart repository (`tf2-corp-chart` / `vars.CHART_REPO`) `values-prod.yaml` via PR only — no change committed inside the local chart checkout of this workspace.
* **Requires** platform secret `CHART_REPO_TOKEN` with chart-repo **Contents** and **Pull requests** write (upgrade existing fine-grained PAT if it only had Contents).
* **No** Terraform / infra change.
* **No** chart template change; operators merge the generated PR when ready for Argo Application `techx-corp` to sync.

Related: prior dev automation `docs/changes/2026-07-11-auto-promote-dev-chart-image-tag.md`.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change until a human merges the chart PR |
| **Infrastructure** | No Terraform / cluster resource change |
| **Deployment** | Prod image promote PR is opened automatically after `release-ready`; merge still manual |
| **Performance** | Negligible (short checkout + git/gh steps after build) |
| **Security** | Same PAT surface as dev; adds Pull requests write on chart repo only |
| **Reliability** | Fewer missed manual PRs; re-runs update the same promote branch/PR |
| **Cost** | No material cloud cost change |
| **Backward compatibility** | Without secret or PR permission, `create-chart-prod-pr` fails (images still pushed); operators can still open a manual values PR |
| **Observability** | Job step summary includes chart repo, branch, tag, and PR URL |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow job structure review | Manual inspection of `create-chart-prod-pr` `if` / `needs` / steps | ✅ Matches production-only gate after `release-ready` |
| Tag update regex vs `values-prod.yaml` shape | Compared to chart `default.image.repository` + `tag:` layout | ✅ Same pattern as proven `update-chart-dev` |

### Manual Verification

* Confirmed Argo prod Application tracks `main` and layers `values-prod.yaml`.
* Confirmed production environment mapping (`main` / `v*` → `production`) in prepare job.
* Full end-to-end verification requires a live production publish with `CHART_REPO_TOKEN` configured (post-merge operator step).

### Remaining Verification (Post-Merge)

1. Ensure fine-grained PAT includes **Pull requests: Read and write** on the chart repo; update `CHART_REPO_TOKEN` if needed.  
   Observed failure without this permission: `GraphQL: Resource not accessible by personal access token (createPullRequest)` while git push still succeeds.
2. Run production publish (`main` / `v*` / dispatch `production`) after images are green.
3. Confirm job **Create chart values-prod PR** is green and links a chart PR.
4. Confirm PR updates only `values-prod.yaml` `default.image.tag`.
5. Merge PR when ready; optional: `argocd app wait techx-corp --sync --health --timeout 600`.

## Migration or Deployment Notes

1. **Pre-requisite:** Upgrade `CHART_REPO_TOKEN` PAT permissions if currently Contents-only:
   * **Contents:** Read and write
   * **Pull requests:** Read and write
2. Optional repo variable `CHART_PROD_BRANCH` if prod base is not `main`.
3. No change to AWS Environment variables (`AWS_ROLE_ARN`, `IMAGE_NAME`).
4. After first production publish, review the bot PR and merge when deploy is intended.
5. Branch protection on chart `main` should still require review; bot only needs permission to create branches + open PRs.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| PAT missing Pull requests write | Medium (existing PAT) | Medium | Job fails with clear error; images still published; fix PAT and re-run job |
| Unwanted prod PR opened | Low | Low | Do not merge; close PR / delete promote branch |
| Wrong tag written | Low | High | Regex targets only `default.image.tag`; verify ECR gate before job runs |
| Concurrent prod publishes create multiple PRs | Medium | Low | One PR per tag branch; review/merge intended tag only |

**Rollback procedure:**

1. Revert this workflow change on the platform repo (or disable/skip the job by temporarily removing the secret so the job fails closed without merging anything).
2. Close any open bot PRs on the chart repo and delete `promote/prod-image-*` branches if unwanted.
3. If a bad PR was already merged: on the chart repo, revert the values commit or set `default.image.tag` back to the previous known-good value and merge that fix to `main`.
