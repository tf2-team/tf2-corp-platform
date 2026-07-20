# Change: Move BuildKit Cache from ECR `:buildcache` to GitHub Actions

## Summary

BuildKit layer cache for release image bakes no longer uses the movable ECR tag `${IMAGE_NAME}/<service>:buildcache`. Cache now uses GitHub Actions `type=gha` with per-service `scope` and `mode=max`. This is required after ECR service repositories were set to `image_tag_mutability=IMMUTABLE`, which rejects overwriting an existing `buildcache` tag.

## Context

* Production (and development) ECR repos were configured with **IMMUTABLE** image tags (infra change `2026-07-19-ecr-immutable-image-tags.md`).
* Platform CI still exported registry cache to `:buildcache` on each bake.
* Second and later builds failed with:

  ```text
  error writing manifest blob: unknown: The image tag 'buildcache' already exists
  in the 'techx-prod-corp/currency' repository and cannot be overwritten because
  the tag is immutable.
  ```

* Related plan: workspace `docs/plan/2026-07-17-mandate-10-secure-delivery-pipeline.md` Task 4 / Step 4.3 (move cache off retaggable ECR tags before/with IMMUTABLE).

## Before

* `docker-bake.hcl` set `cache-from` / `cache-to` to `type=registry,ref=${IMAGE_NAME}/<service>:buildcache`.
* `prepare` required every release target to declare that ECR cache ref with `mode=max`.
* Build matrix jobs logged and summarized `${IMAGE_NAME}/${SERVICE}:buildcache`.
* Local `make build-multiplatform-and-push` also pushed `:buildcache` when baking with the release HCL.

## After

* `docker-bake.hcl` uses `type=gha,scope=<service>` (import) and `type=gha,mode=max,scope=<service>` (export).
* `prepare` validates GHA cache type/scope/mode instead of ECR `:buildcache` refs.
* Build matrix jobs request `actions: write` so cache export can write to the GHA cache service.
* Local multiplatform push clears `cache-from` / `cache-to` (GHA cache is not available outside Actions).
* Docs (CICD, DEPLOYMENT, README) describe GHA cache and the IMMUTABLE + `:buildcache` failure mode.

## Technical Design Decisions

* **GHA cache over unique ECR cache tags:** matches mandate plan; avoids ECR storage growth for cache digests and keeps runtime repos free of non-deploy tags.
* **Per-service `scope`:** isolates cache namespaces across the 22-matrix service builds so one service does not thrash another’s cache.
* **Clear cache on local Makefile push:** `type=gha` export fails or is meaningless without Actions cache credentials; clearing is safer than leaving GHA defaults for operator laptops.
* **Do not require deleting old `:buildcache` images:** optional cleanup only; deploy and new CI ignore those tags.

## Implementation Details

1. Rewrote all release targets in `docker-bake.hcl` to use GHA cache instead of registry cache.
2. Updated catalog validation in `.github/workflows/build-and-push.yml` to assert `type=gha` + service `scope` + `mode=max` on cache-to.
3. Added `actions: write` to the build job; updated bake logs and job summary cache fields.
4. Makefile multiplatform push: `--set "*.cache-from=" --set "*.cache-to="`.
5. PR local bake (`ci.yml`) still clears cache (unchanged behavior; comment updated).
6. Documented the change and troubleshooting entry for the immutable `buildcache` error.

## Files Changed

**Build definition:**
* `docker-bake.hcl` — GHA `type=gha` cache per service; no ECR `:buildcache`.

**CI:**
* `.github/workflows/build-and-push.yml` — prepare cache asserts; build job `actions: write`; bake log/summary.
* `.github/workflows/ci.yml` — PR bake comment (still clears cache).

**Tooling:**
* `Makefile` — clear GHA cache flags on local multiplatform ECR push.

**Documentation:**
* `docs/CICD.md` — cache contract, local bake, troubleshooting.
* `docs/DEPLOYMENT.md` — catalog/cache notes and manual bake flags.
* `README.md` — cache bullet.
* `docs/changes/2026-07-19-gha-buildkit-cache-immutable-ecr.md` — this change record.

## Dependencies and Cross-Repository Impact

* **Depends on** `techx-corp-infra` ECR IMMUTABLE configuration (already applied or pending apply). This platform change unblocks image publish under that setting.
* Related: `techx-corp-infra/docs/changes/2026-07-19-ecr-immutable-image-tags.md`.
* No chart changes. Helm continues to deploy only `sha-*` / `v*` runtime tags.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No Terraform change; optional cleanup of orphan ECR `:buildcache` tags |
| **Deployment** | Image publish succeeds again under IMMUTABLE ECR; chart promote path unchanged |
| **Performance** | First post-cutover bake may be cold (no GHA cache yet); subsequent CI builds reuse GHA cache. Cache is per GitHub Actions cache service (not shared with local operators). |
| **Security** | Aligns with immutable runtime tags; cache is not a deployable artifact |
| **Reliability** | Removes class of “immutable buildcache” publish failures |
| **Cost** | Less ECR storage for cache manifests; GHA cache storage applies instead |
| **Backward compatibility** | CI after this change no longer writes `:buildcache`. Old tags can remain unused. |
| **Observability** | Job summary shows `type=gha,scope=<service>` instead of ECR cache ref |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Bake print structure | Review of `docker-bake.hcl` targets | ✅ All 22 use `type=gha` + scope |
| Workflow catalog assert | jq logic updated in prepare | ✅ Asserts GHA type/scope/mode |
| Local Makefile flags | Review of `build-multiplatform-and-push` | ✅ Clears cache-from/to |

### Manual Verification

* Root cause matched infra IMMUTABLE + platform registry cache (documented error on `techx-prod-corp/currency:buildcache`).
* Full CI bake was not re-run in this workspace session (requires GitHub Actions + OIDC).

### Remaining Verification (Post-Merge)

1. Merge to `techx-dev-corp` (or re-run **Build and push images** for development).
2. Confirm prepare passes catalog validation and matrix builds complete without `buildcache` / immutable tag errors.
3. Confirm `verify-ecr` finds all 22 runtime tags under the new `sha-*` / `v*` tag.
4. Optionally delete leftover `:buildcache` images in ECR to free storage (not required for correctness).

## Migration or Deployment Notes

1. Merge this platform change **before or with** the next image publish after ECR IMMUTABLE is live.
2. No Helm/Argo steps. Re-run the failed workflow (or push a path that triggers publish).
3. Local multiplatform push must clear GHA cache (Makefile already does). Example:

```cmd
cd /d techx-corp-platform
make build-multiplatform-and-push
```

```sh
# equivalent explicit flags
docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push \
  --set "*.cache-from=" --set "*.cache-to="
```

4. Optional ECR cleanup of orphan cache tags (operator-approved; mutates registry state):

```cmd
REM Example: list digests tagged buildcache for one service, then batch-delete
aws ecr describe-images --repository-name techx-prod-corp/currency --region us-east-1 --query "imageDetails[?contains(imageTags, 'buildcache')]"
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Cold GHA cache slows first few builds | Medium | Low | Accept; subsequent runs warm the cache |
| Org restricts `actions: write` on GITHUB_TOKEN | Low | Medium | Allow cache write for the workflow, or use a PAT/cache workaround |
| Local bake forgets to clear GHA cache | Low | Low | Makefile clears flags; docs show `--set` |

**Rollback procedure:**

1. Revert `docker-bake.hcl`, both workflows, Makefile, and docs in this change.
2. If ECR remains IMMUTABLE, registry `:buildcache` will fail again — either keep GHA cache or temporarily set `ecr_image_tag_mutability = "MUTABLE"` in infra (not recommended for prod).

<!-- Change trail: @hungxqt - 2026-07-19 - Record move from ECR :buildcache to GHA BuildKit cache under IMMUTABLE ECR. -->
