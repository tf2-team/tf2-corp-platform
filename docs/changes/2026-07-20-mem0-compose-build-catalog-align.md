# Change: Align Mem0 Compose helpers with release image catalog

## Summary

Remove `build:` from the local Compose helpers `mem0-model-init` and `mem0-migrate` so they only reference the shared `mem0` image. This restores the prepare-step invariant that every Compose service with a `build:` block is exactly one of the 23 bake `release` images.

## Context

Platform CI (`build-and-push.yml` prepare → Validate release catalog) fails when Compose build service names do not match the hard-coded release catalog / `docker-bake.hcl` group `release`:

```text
Catalog size mismatch: release=23 compose-builds=25
```

The two extra Compose build keys were `mem0-model-init` and `mem0-migrate`. Both already used `${IMAGE_NAME}/mem0:${DEMO_VERSION}` and `./src/mem0/Dockerfile`; they are local stand-ins for production init/Job containers, not separate ECR release images.

* Why now: publish prepare was red after those helpers gained (or retained) independent `build:` blocks.
* Constraint: keep the simple 1:1 catalog gate rather than teaching CI about image aliases.

## Before

* Compose services with `build:`: **25** (23 release + `mem0-model-init` + `mem0-migrate`).
* Bake `release` / CI `RELEASE_JSON`: **23** services including a single `mem0`.
* Prepare catalog check compared sorted service **names** and exited 1 on size mismatch.

## After

* `mem0-model-init` and `mem0-migrate` declare only `image: ${IMAGE_NAME}/mem0:${DEMO_VERSION}` (no `build:`).
* Compose build targets: **23**, matching bake `release` and CI catalog.
* Local workflow: build/run via `mem0` (or full stack); helpers reuse the same tag, as in Kubernetes.

## Technical Design Decisions

* **Option A (chosen):** drop `build:` on helpers — mirrors production (one image, multiple runtime roles) and keeps the CI name-equality gate.
* **Option B (rejected):** special-case aliases in CI — more drift risk for little local benefit.
* Do **not** add the helpers to the release bake group; they must not become separate ECR images under the global tag.

## Implementation Details

1. Removed `build.context` / `build.dockerfile` from `mem0-model-init` and `mem0-migrate` in `docker-compose.yml`.
2. Documented in-service comments that helpers reuse the `mem0` image and that `docker compose build mem0` is the local rebuild path.
3. No workflow or bake catalog changes (counts remain 23).

## Files Changed

**Configuration:**
* `docker-compose.yml` — Removed `build:` from `mem0-model-init` and `mem0-migrate`; comments note shared-image invariant.

**Documentation:**
* `docs/changes/2026-07-20-mem0-compose-build-catalog-align.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Chart/infra still pull a single `mem0` image; no Helm or ECR catalog change.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change in Kubernetes. Local Compose helpers still run the same commands against the `mem0` image tag. |
| **Infrastructure** | No change |
| **Deployment** | Publish prepare catalog check can pass again (23 == 23). |
| **Performance** | No change |
| **Security** | No change |
| **Reliability** | Restores green gate that prevents untracked Compose build services from shipping without a release image. |
| **Cost** | No change |
| **Backward compatibility** | Local: `docker compose build mem0-migrate` / `mem0-model-init` no longer builds; use `docker compose build mem0`. |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Compose config (build keys) | After change: only release services should list `build` | Pending operator/local Docker |
| Catalog equality logic | Same as CI: release list length vs Compose `build != null` keys | Expected 23 == 23 |

### Manual Verification

* Diff: `mem0-model-init` and `mem0-migrate` no longer have `build:`.
* Compared error log: extras were exactly those two service names.

### Remaining Verification (Post-Merge)

* Re-run platform **Build and push** / prepare on a path that triggers the workflow (`docker-compose.yml` is in the path filter).
* Optional local: `docker compose config --format json` and confirm 23 services with `build`.

## Migration or Deployment Notes

1. No cluster deploy required for this fix alone.
2. Local operators: rebuild Mem0 with `docker compose build mem0` (or bake/release target `mem0`) before relying on `mem0-migrate` / `mem0-model-init`.

```cmd
cd /d techx-corp-platform
docker compose --env-file .env --env-file .env.override build mem0
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Local stack fails if `mem0` image tag missing when only helpers are started | Low | Low | Build `mem0` first; full `up` builds services that still have `build:`. |
| Script still calls `docker compose build mem0-migrate` | Low | Low | Point scripts at `mem0`; grep docs if issues reported. |

**Rollback procedure:**

Restore `build:` blocks on both helpers in `docker-compose.yml` (previous Dockerfile path `./src/mem0/Dockerfile`, context `./`). Prefer fixing CI instead only if a deliberate alias policy is adopted.

<!-- Change trail: @hungxqt - 2026-07-20 - Record mem0 Compose helper build removal for catalog align. -->
