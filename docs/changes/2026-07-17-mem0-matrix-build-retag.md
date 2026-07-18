# Change: Move mem0 to matrix build and retag

## Summary

Mem0 now participates in the selective image matrix like every other release service: bake from source when it changes, retag from `PREV_TAG` when it does not. Compose/bake catalog edits alone no longer force a full 22-service multi-arch rebuild. The Mem0 FastEmbed S3 artifact follows the same build-vs-retag classification.

## Context

PR #30 added `mem0` to the 22-image release catalog and introduced a FastEmbed S3 publish job. Because that PR also touched `docker-compose.yml` and `docker-bake.hcl`, classification treated the change as a **full** rebuild of all services (`build_count=22`, `retag_count=0`). That is expensive and unnecessary when only mem0 (or catalog wiring for mem0) changed.

Operators need the existing matrix contract:

* **Build** changed services from source
* **Retag** unchanged services `PREV_TAG` → `NEW_TAG`
* Preflight still moves any service missing `PREV_TAG` into the build list (covers first-time mem0 publish)

## Before

* `docker-compose.yml` and `docker-bake.hcl` were **full-bake triggers** alongside `pb/**`, `.env`, `buildkitd.toml`, and `.gitmodules`.
* Adding or wiring mem0 in compose/bake forced multi-arch bake of all 22 services.
* FastEmbed always rebuilt from Hugging Face and uploaded under `NEW_TAG`, even when mem0 was unchanged.
* Missing `MEM0_FASTEMBED_ARTIFACT_S3_URI` hard-failed the FastEmbed job and blocked `release-ready` for every publish.

## After

* Full-bake triggers: `pb/**`, `buildkitd.toml`, `.env`, `.gitmodules` only.
* Compose/bake catalog edits are **selective** (logged, not full). Path-based `src/mem0/**` and `third-party/mem0` still put mem0 on the build matrix; other services retag.
* Preflight continues to move services without `PREV_TAG` (including first mem0 tag) into the build list.
* FastEmbed:
  * **Build** when mem0 is in the refined build list
  * **Retag** (S3 recursive copy) when mem0 is only retagged
  * **Skip with warning** when `MEM0_FASTEMBED_ARTIFACT_S3_URI` is unset (image promote continues)
* PR local image classification in `ci.yml` matches the same rules.
* Docs updated to 22 services and the new classification table.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Drop compose/bake from full triggers | Catalog wiring for a new service should not rebuild 21 unchanged images; force_full remains for platform-wide bake changes |
| Keep preflight PREV_TAG check | First-time services and incomplete prior publishes still bake instead of failing retag |
| FastEmbed follows mem0 image side | Avoid multi-minute model rebuilds on unrelated service publishes |
| Soft-skip when S3 URI unset | ECR matrix and chart promote must not hard-block while model-cache env wiring is incomplete |
| Keep `pb/**` / `.env` / `buildkitd.toml` / `.gitmodules` as full | These can affect many or all images |

Alternatives rejected:

* Always full bake when compose/bake change — correct for safety, too expensive for service onboarding
* Per-service Helm tags — out of scope; global tag contract remains
* Require FastEmbed URI before any publish — blocks all image promotion until CloudOps sets the var

## Implementation Details

1. `build-and-push.yml` classify: remove `docker-compose.yml` / `docker-bake.hcl` from `FULL_TRIGGER`; log as selective catalog changes.
2. Expand mem0 path match to `third-party/mem0|third-party/mem0/*`.
3. FastEmbed job: resolve `action=build|retag` from refined `build_services` containing `mem0`.
4. Build path: existing Python build + validate + S3 upload under `…/${NEW_TAG}/`.
5. Retag path: `aws s3 cp` previous prefix to new prefix; fail if previous objects missing.
6. Skip path: unset URI → warning + success summary (does not fail release-ready).
7. Mirror classification changes in `ci.yml` PR image prepare.
8. Update `docs/CICD.md` catalog counts (22), path rules, FastEmbed table.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — Selective classification for compose/bake; FastEmbed build/retag/skip; job graph comments.
* `.github/workflows/ci.yml` — Same selective classification for PR local bake.

**Documentation:**

* `docs/CICD.md` — 22-service catalog, path filter, selective rules, FastEmbed matrix alignment.
* `docs/changes/2026-07-17-mem0-matrix-build-retag.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Infra / chart:** none required for this CI change.
* **Operator:** set GitHub Environment variable `MEM0_FASTEMBED_ARTIFACT_S3_URI` on `development` and `production` when FastEmbed publish should run (e.g. `s3://<ai-models-bucket>/mem0/fastembed`). GHA OIDC role needs `s3:PutObject` (and list/get) on that prefix for build and retag.
* First selective run after this change: expect **Build mem0** + **Retag** of the other 21 if only mem0/catalog paths changed and prior tags exist.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime code change |
| **Infrastructure** | No Terraform change; optional S3 URI env var for artifact publish |
| **Deployment** | Faster selective publishes when onboarding/changing mem0; chart promote still waits for release-ready |
| **Performance** | Avoids full 22-service multi-arch bake on catalog-only mem0 wiring; avoids FastEmbed rebuild on retag |
| **Security** | Same OIDC roles; soft-skip does not upload models without configured URI |
| **Reliability** | Missing PREV_TAG still falls back to bake via preflight |
| **Cost** | Lower Actions minutes on selective mem0 changes |
| **Backward compatibility** | Tags and `force_full_rebuild: true` still full-bake all 22 |
| **Observability** | Job summaries show FastEmbed build vs retag vs skip |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow structure | Manual review of classify cases and FastEmbed `if` conditions | Implemented |
| YAML edit scope | Diff of workflows only for classification + FastEmbed | Implemented |

### Manual Verification

* Classification reviewed for: `src/mem0/**` → build mem0 + retag others; compose/bake only → selective retag-all with preflight bake of missing PREV_TAG; `pb/**` → full.
* FastEmbed plan: mem0 in build list → build; else → S3 retag; URI empty → skip warning.

### Remaining Verification (Post-Merge)

* Cancel or let finish the full rebuild run triggered by PR #30 merge if still wasteful; re-run with this change on a mem0 or catalog commit.
* Confirm prepare summary: `mode=selective`, build includes `mem0` only when sources/catalog require it, retag covers the rest.
* After setting `MEM0_FASTEMBED_ARTIFACT_S3_URI`, verify one FastEmbed build and one FastEmbed retag path.

## Migration or Deployment Notes

1. No new secrets required for image matrix path.
2. Optional: set `MEM0_FASTEMBED_ARTIFACT_S3_URI` on GitHub Environments `development` and `production`.
3. Ensure GHA ECR publish role (or a dedicated model-publish role) can write the FastEmbed prefix if enabling artifact publish.
4. To force all services from source after bake platform changes: `workflow_dispatch` with `force_full_rebuild: true` (default).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Shared compose/bake change that should have rebuilt all images only retags | Low | Medium | Use `force_full_rebuild`; keep pb/env/buildkitd/gitmodules as full triggers |
| FastEmbed soft-skip hides missing model cache until deploy | Medium | Medium | Wire URI before Mem0 chart cutover; job summary shows skip |
| S3 retag when PREV prefix empty | Low | Medium | Job fails with clear error; force mem0 rebuild |

**Rollback procedure:**

1. Revert this commit (or restore compose/bake as full triggers and always-build FastEmbed).
2. Re-run publish with `force_full_rebuild: true` if a partial selective set is untrusted.

<!-- Change trail: @hungxqt - 2026-07-17 - Mem0 selective matrix build/retag and FastEmbed alignment. -->
