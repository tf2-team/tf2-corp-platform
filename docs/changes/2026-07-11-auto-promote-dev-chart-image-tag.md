# Change: Auto-promote dev chart image tag after release-ready

## Summary

After a successful development image publish (`release-ready` green), platform CI now direct-pushes `default.image.tag` in the chart repository’s `values-dev.yaml` on branch `techx-dev-corp`, so Argo CD can auto-sync the new global image tag without a manual values PR.

## Context

REL-09 GitOps uses a **global** `default.image.tag` for all nested services. Platform CI already rebuilt the full 21-image release set and verified every ECR tag before marking `release-ready`, but chart promotion was still manual (Phase 6 deferred). Operators wanted automated promotion for **development** only: when build/push succeeds, update the chart branch that Argo CD Application `techx-corp-dev` tracks.

Constraints:

* Production must remain manual review (`values-prod.yaml`).
* Cross-repo write requires a PAT/App token (`CHART_REPO_TOKEN`); platform `GITHUB_TOKEN` cannot push to the chart repo.
* Direct push (not PR) for dev, per operator request, to match Argo auto-sync on `techx-dev-corp`.

## Before

* Job graph ended at `release-ready`.
* Docs stated platform was read-only toward the chart repo; operators opened a manual values PR after every successful publish.
* No secret or job existed for writing `values-dev.yaml`.

## After

* New job **`update-chart-dev`** runs only when:
  * `release-ready` succeeds, and
  * `target_environment == development`.
* The job checks out chart repo (`vars.CHART_REPO` default `tmcmanhcuong/tf2-corp-chart`, branch `vars.CHART_BRANCH` default `techx-dev-corp`), updates only `default.image.tag` in `values-dev.yaml` to the built tag (e.g. `sha-a1b2c3d`), commits as `github-actions[bot]`, and pushes (with rebase retry on concurrent updates).
* If the tag is already current, the job no-ops successfully.
* Missing `CHART_REPO_TOKEN` fails the job with a clear setup error (images remain published).
* Production path unchanged: manual chart PR only.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Direct push vs PR (dev) | Operator requested push to `techx-dev-corp`; Argo already auto-syncs that branch. |
| Gate on `release-ready` | Ensures full catalog bake + ECR verify before any GitOps tag change. |
| Dev only | Prod path protection / required reviewers remain intentional. |
| PAT secret (`CHART_REPO_TOKEN`) | Cross-repo contents write; fine-grained PAT scoped to chart repo. |
| Python regex for YAML edit | Preserves comments/layout of `values-dev.yaml` without adding yq dependency. |
| Skip if tag unchanged | Avoids empty commits on re-runs. |
| Rebase retry on push | Concurrent human/bot commits to the same branch. |

Alternatives rejected:

* PR + auto-merge: extra latency and branch protection complexity for already-trusted post-verify dev promotes.
* Prod automation: out of scope; keep manual review.
* Helm/Argo API deploy from platform: violates GitOps ownership (chart Git is source of truth).

## Implementation Details

1. Extended `.github/workflows/build-and-push.yml` with job `update-chart-dev` after `release-ready`.
2. Job requires secret `CHART_REPO_TOKEN`; optional vars `CHART_REPO`, `CHART_BRANCH`.
3. Precise in-place update of the `default.image.tag` scalar under `default.image`.
4. Commit message references platform SHA and workflow run URL for audit.
5. Updated `docs/CICD.md`, `docs/DEPLOYMENT.md`, `README.md`, and REL-09 backlog to describe setup and flow.
6. Expanded **operator setup** in `docs/CICD.md` §4: auth model (PAT vs `GITHUB_TOKEN` vs commit author), fine-grained PAT steps, platform secret/vars, chart branch push rules, verify, failure modes, rotation. Cross-linked from `DEPLOYMENT.md` and `README.md`.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — Added `update-chart-dev`; updated release-ready summary for env-specific promotion messaging.

**Documentation:**

* `docs/CICD.md` — Job graph, full operator setup (PAT/secret/branch rules), promotion flow, troubleshooting.
* `docs/DEPLOYMENT.md` — Bước 0 table for chart promote operator setup + link to CICD §4.
* `README.md` — CI/CD summary + operator setup link.
* `docs/backlogs/2026-07-09-rel-09-gitops-argocd.md` — Phase 6 acceptance marked done for dev.
* `docs/changes/2026-07-11-auto-promote-dev-chart-image-tag.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-11-document-dev-auto-image-tag-promote.md` (runbook only).
* Requires chart branch `techx-dev-corp` to allow the PAT identity to push.
* Runtime chart file mutation happens on the **remote** chart repo after CI runs; this change does not edit local `values-dev.yaml` in the chart repo.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No direct code change; after setup, successful dev publishes roll out new image tags via Argo auto-sync. |
| **Infrastructure** | No Terraform/ECR change. |
| **Deployment** | Dev image promote becomes automatic post-`release-ready`; prod still manual. |
| **Performance** | One extra short Git job after publish (~1 min). |
| **Security** | New long-lived PAT secret; scope to chart repo contents:write only. Prefer fine-grained PAT + rotation. |
| **Reliability** | Rebase retries reduce failed promotes under concurrent chart commits. |
| **Cost** | Negligible Actions minutes. |
| **Backward compatibility** | Without secret, `update-chart-dev` fails (images still pushed); operators can still manual-edit values. |
| **Observability** | Job step summary lists chart repo/branch/tag. |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow YAML review | Manual structure review of new job `if`/needs/permissions | ✅ Structured as intended |
| Live Actions run | Pending operator merge + secret | ⏳ Remaining |

### Manual Verification

* Regex logic matches current `values-dev.yaml` shape (`default.image.repository` + optional comment + `tag: "..."`).
* Job conditions reviewed: development-only; skipped when `release-ready` fails.

### Remaining Verification (Post-Merge)

1. Add `CHART_REPO_TOKEN` on platform GitHub repo.
2. Run **Build and push images** (`workflow_dispatch` → `development`) or push `src/**` to `techx-dev-corp`.
3. Confirm `update-chart-dev` green and chart `values-dev.yaml` tag equals the built `sha-*`.
4. Confirm Argo CD `techx-corp-dev` becomes Synced/Healthy (or wait with `argocd app wait`).

## Migration or Deployment Notes

1. Create fine-grained PAT with **Contents: Read and write** on the chart repository.
2. Platform repo → Settings → Secrets → Actions: `CHART_REPO_TOKEN`.
3. Optional: set `CHART_REPO` / `CHART_BRANCH` variables if defaults differ.
4. Ensure chart branch `techx-dev-corp` allows the PAT to push (bypass or no blocking required-PR rule for that identity).
5. Merge this platform workflow change to `techx-dev-corp` (or the branch that runs the workflow).
6. No chart-side workflow change required for the first promote.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| PAT leaked or over-scoped | Low | High | Fine-grained PAT, chart repo only; rotate if exposed |
| Bad tag pushed after partial publish | Low | High | Gate on full `release-ready` + ECR verify |
| Branch protection blocks push | Medium | Medium | Document ruleset/PAT bypass; fallback to manual commit |
| Concurrent chart edits conflict | Low | Low | Rebase retry loop |

**Rollback procedure:**

1. Remove or empty secret `CHART_REPO_TOKEN` (job will fail closed on write; or delete the job by reverting the workflow commit).
2. Revert the workflow commit on the platform branch.
3. If a bad tag was pushed: on chart repo, revert the bot commit or set `default.image.tag` back to the previous known-good value and push/merge to `techx-dev-corp`.
