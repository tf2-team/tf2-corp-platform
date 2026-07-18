# Change: Publish customized OpenSearch image to ECR

## Context

Helm/Argo deployed the public `opensearchproject/opensearch` image via the OpenSearch subchart. That image includes Performance Analyzer and other plugins not needed for the demo, which produced noisy `plugin-stats-metadata` `FileNotFoundException` logs. Platform already built a customized OpenSearch image for Compose (`src/opensearch/Dockerfile`) but classified it as bake `local-only`, so CI never pushed it to ECR.

## Before

* `docker-bake.hcl` group `release` had 20 services; `opensearch` was in `local-only`.
* CI catalog asserts forbade `opensearch` in the release set.
* Helm used the upstream OpenSearch chart default image (Docker Hub), not the customized build.

## After

* `opensearch` is part of the **21-service** `release` group with the same multi-arch and registry `buildcache` contract as other services.
* CI prepare/preflight/build/verify treat OpenSearch like any other release image.
* Chart (separate change) points the OpenSearch subchart at `${ECR}/…/opensearch:<tag>`.

## Implementation

1. Moved `opensearch` into group `release` and removed group `local-only`.
2. Gave the `opensearch` bake target dual platforms (`linux/amd64`, `linux/arm64`) and registry cache import/export (`mode=max`).
3. Updated `build-and-push.yml` catalog validation: release count 21; release must equal all Compose build targets; assert `opensearch` **is** in release.
4. Updated Makefile and CICD/DEPLOYMENT/README docs for the 21-image catalog.

## Files Changed

* `docker-bake.hcl`
  * Release catalog includes `opensearch`; full cache/platforms contract.
* `.github/workflows/build-and-push.yml`
  * Catalog asserts and comments updated for 21 release services.
* `Makefile`
  * Comment for release group size.
* `docs/CICD.md`, `docs/DEPLOYMENT.md`, `README.md`
  * Document customized OpenSearch as a release image.

## Impact

* **Application behavior:** Cluster OpenSearch runs the same stripped-plugin image as local Compose (no Performance Analyzer noise).
* **CI/CD:** Full publish is 21 matrix jobs; slightly longer wall time.
* **ECR:** Uses existing `…/opensearch` repository (already in infra ECR module defaults).
* **Backward compatibility:** Compose local path unchanged; chart must promote tags that include an OpenSearch image.

## Validation

* `docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --print` → 21 targets including `opensearch` with platforms `linux/amd64,linux/arm64` and `buildcache` cache-from/cache-to.

## Migration or Deployment Notes

1. Run platform **Build and push** (workflow_dispatch or `src/**` push) so ECR has `…/opensearch:<tag>` for the target environment.
2. Confirm `release-ready` (includes OpenSearch in verify-ecr).
3. Merge the matching chart change that sets `opensearch.image.repository` / `tag` before Argo sync, or Argo will ImagePullBackOff on the new tag.

## Risks and Rollback

* Risk: chart promotes a tag before OpenSearch is pushed → ImagePullBackOff on `opensearch` pods.
* Rollback: restore `local-only` classification and point Helm back at `opensearchproject/opensearch` (reverts this change + chart image override).
