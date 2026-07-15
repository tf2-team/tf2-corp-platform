# Change: PR-only local image bake gate (no ECR push)

## Summary

Pull request CI now builds changed release service images on the runner without logging into ECR or pushing tags. A stable aggregator job **`PR image build`** can be required in branch protection so Dockerfile and build-context failures (for example a missing `COPY` of a new package) fail before merge.

## Context

Publish workflow `build-and-push.yml` only runs on push to `main` / `techx-dev-corp`, tags, and `workflow_dispatch`. PR CI previously ran lint and unit tests only. Unit tests compile against the full workspace tree and do not exercise multi-stage Dockerfiles, so a broken image build could reach `main` and fail only after merge (seen with checkout durable outbox missing `outbox/` in the Dockerfile).

## Before

| Trigger | Image validation |
|---|---|
| Pull request | None (lint + unit tests only) |
| Push / tag / dispatch | Multi-arch bake with `--push` to ECR |

## After

| Trigger | Image validation |
|---|---|
| Pull request | Selective or full **local** bake (`linux/amd64`, `output=type=cacheonly`, no AWS, no `--push`) |
| Push / tag / dispatch | Unchanged: multi-arch bake + ECR push + verify + chart promote |
| `workflow_call` of `ci.yml` from Build & Push | Lint + unit tests only (PR image jobs skipped) |

## Technical Design Decisions

* **Keep local bake inside `ci.yml`** so one workflow covers PR quality gates; avoid a second PR workflow that operators must require separately beyond a single stable check name.
* **No AWS OIDC / ECR on PR** so the gate cannot publish accidental tags and needs no environment secrets.
* **Disable bake registry cache** (`cache-from` / `cache-to` cleared) because those refs point at ECR in `docker-bake.hcl`.
* **`output=type=cacheonly`** fully runs Dockerfile builds without loading multi-GB images into the runner daemon or pushing.
* **Single platform `linux/amd64`** for PR cost/latency; multi-arch remains a publish concern.
* **Stable job `pr-image-build`** named **PR image build** for branch protection; matrix jobs stay informative but optional as required checks.
* **Same path classification roots** as publish (`src/<service>`, `pb/**`, compose/bake/env/buildkitd) so selective vs full behavior matches operator mental model.
* Full shared-path PRs still bake all 21 services (heavier) rather than sampling—correctness over speed when global build inputs change.

## Implementation Details

1. Added `prepare-pr-images` (PR only): `git diff` base…head, classify build list, emit JSON matrix outputs.
2. Added `build-pr-images` matrix: free disk, setup Buildx, source committed `.env` for Dockerfile vars, override `IMAGE_NAME`/`DEMO_VERSION` to non-ECR placeholders, bake with local-only overrides.
3. Added `pr-image-build` aggregator: fails on prepare failure or matrix failure/cancel; succeeds when matrix is success or skipped (`build_count=0`).
4. Documented behavior and required-check name in `docs/CICD.md`.

## Files Changed

**CI:**

* `.github/workflows/ci.yml` — PR-only prepare / matrix bake / aggregator jobs.

**Documentation:**

* `docs/CICD.md` — PR job graph, classification table, required-check guidance.
* `docs/changes/2026-07-15-pr-local-image-build-gate.md` — This change record.

## Dependencies and Cross-Repository Impact

None for runtime. Operators should add GitHub branch protection required check **`PR image build`** on `main` / `techx-dev-corp` if they want the gate enforced (workflow addition alone does not mark checks required).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No ECR or IAM change |
| **Deployment** | No change to publish or chart promote |
| **Performance** | PR CI longer when image-affecting paths change (per-service bake up to 60m, max-parallel 8) |
| **Security** | PR path does not obtain AWS credentials or write to ECR |
| **Reliability** | Catches image compile failures before merge |
| **Cost** | Additional GitHub Actions minutes on image-touching PRs only |
| **Backward compatibility** | Fully backward-compatible; publish workflow unchanged |
| **Observability** | Job summaries for plan and per-service bake |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow YAML syntax | Manual review of job `if` / matrix / outputs | ✅ Structured consistently with existing workflows |
| Existing unit path | Not re-run (workflow-only change) | N/A |

### Manual Verification

* Confirmed publish workflow has no `pull_request` trigger and still uses `--push`.
* Confirmed PR jobs are gated with `github.event_name == 'pull_request'` so `workflow_call` skips them.

### Remaining Verification (Post-Merge)

1. Open a PR that touches `src/checkout/**` and confirm matrix bakes checkout only, with no ECR login steps.
2. Open a docs-only PR and confirm prepare reports `build_count=0` and **PR image build** still succeeds.
3. Optionally mark **PR image build** required in branch protection.

## Migration or Deployment Notes

1. Merge this workflow change to the default branch so PRs load the new jobs.
2. In GitHub → Settings → Branches → protection for `main` (and `techx-dev-corp` if used): require status check **`PR image build`**.
3. Do **not** require individual matrix names (`Build checkout (PR local)`); the aggregator is the intended gate.

```cmd
REM No deploy commands. After merge, configure branch protection in GitHub UI.
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Full 21-service PR on shared path change is slow | Medium | Low | Accept or later add path-based sampling; publish path unchanged |
| `cacheonly` output unsupported on older Buildx | Low | Medium | Actions pin current setup-buildx; fail visible on PR |
| Branch protection not updated | Medium | Low | Gate runs but is not merge-blocking until required |

**Rollback procedure:**

```cmd
cd /d techx-corp-platform
git revert <this-commit-sha>
```

Remove **PR image build** from branch protection if it was added.

<!-- Change trail: @hungxqt - 2026-07-15 - Document PR local image bake gate without ECR push -->
