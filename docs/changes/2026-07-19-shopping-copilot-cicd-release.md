# Change: Add shopping-copilot to CI/CD release catalog

## Summary

Promote `shopping-copilot` into the platform **release** bake/CI catalog (22 → **23** services) so Compose build targets, PR local bake, multi-arch publish, and ECR verify all include the new service. Add a dedicated GitHub Actions job for Shopping Copilot unit tests.

## Context

Platform PR work added `src/shopping-copilot` and a Compose build service, but `docker-bake.hcl` group `release` and the canonical `RELEASE_JSON` lists in CI/publish workflows still had 22 entries without `shopping-copilot`. Publish `prepare` requires release == all Compose build targets, so the catalog was already inconsistent once shopping-copilot landed in Compose. Infra now provisions `…/shopping-copilot` ECR; platform CI must push that image.

* Related: infra change for ECR/ASM/IRSA shopping-copilot support.
* Related: platform PR #36 feature branch (`aie`).

## Before

* Compose had `shopping-copilot` build target; bake `release` did not.
* CI PR classifier treated `src/shopping-copilot/**` as non-release (no PR image bake).
* No CI job ran `src/shopping-copilot/tests`.
* Docs and catalog asserts expected **22** release images.

## After

* `docker-bake.hcl` includes target `shopping-copilot` and lists it in group `release` (**23**).
* `ci.yml` and `build-and-push.yml` `RELEASE_JSON` + count asserts use **23**.
* New job **Shopping copilot tests** runs pytest with `PYTHONPATH` covering shopping-copilot + product-reviews shared modules.
* Docs/Makefile/README describe the 23-image catalog including shopping-copilot.

## Technical Design Decisions

* **Normal matrix service** (same as mem0): selective build vs retag; no special full-rebuild trigger for compose-only edits.
* **Dedicated pytest job** rather than overloading the mem0-hardcoded Python matrix steps: shopping-copilot needs `pytest` + dual PYTHONPATH trees; keeps mem0 unittest path unchanged.
* **Guardrail model optional in CI** (`AI_GUARDRAIL_REQUIRE_MODEL=false`): graph tests exercise keyword fallback and mocks; full ProtectAI download stays on product-reviews job.

## Implementation Details

1. Added bake target + release group entry for `shopping-copilot`.
2. Updated canonical RELEASE_JSON and 23-count checks in both workflows; max-parallel 23 for build/retag matrices.
3. Added `shopping-copilot-tests` job to `ci.yml`.
4. Updated operator docs and Makefile comment for the 23-service set.

## Files Changed

**CI / bake:**
* `docker-bake.hcl` — Release target + group membership (23).
* `.github/workflows/ci.yml` — RELEASE_JSON; shopping-copilot-tests job.
* `.github/workflows/build-and-push.yml` — RELEASE_JSON, count asserts, max-parallel, chart PR note.

**Tooling / docs:**
* `Makefile` — Multiplatform push comment (23 services).
* `docs/CICD.md` — Catalog table and counts.
* `docs/DEPLOYMENT.md` — Job graph / catalog counts.
* `docs/LOCAL_BUILD_AND_RUN.md` — Catalog count + AI services list.
* `README.md` — Release image count.
* `docs/changes/2026-07-19-shopping-copilot-cicd-release.md` — This record.

## Dependencies and Cross-Repository Impact

* **techx-corp-infra:** ECR repository `shopping-copilot` must exist before first publish (see infra change `2026-07-19-shopping-copilot-infra-support.md`). First selective publish after this change will **bake** shopping-copilot (no PREV_TAG) and **retag** the other 22 if prior tags exist.
* **techx-corp-chart:** Still required to deploy the service (values, ExternalSecret, IRSA); global image tag promote is unchanged.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change until chart deploys shopping-copilot |
| **CI/CD** | +1 bake/retag/verify service; +1 pytest job on PR/CI |
| **Deployment** | Global tag now requires shopping-copilot ECR image under the same tag |
| **Performance** | Slightly longer full rebuilds; selective path bakes only when `src/shopping-copilot/**` changes |
| **Security** | No secret changes in workflows |
| **Backward compatibility** | Catalog size assert breaks if workflows and bake diverge; intentional |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Catalog lists | Manual parity of RELEASE_JSON vs bake group vs compose | Aligned |
| Bake print | `docker buildx bake … release --print` | Pass (23 targets, includes shopping-copilot) |
| Shopping copilot pytest | `pytest src/shopping-copilot/tests` with dual PYTHONPATH | Pass (32) |

### Manual Verification

* Local bake print confirmed `shopping-copilot` in release group.
* Local pytest 32 passed after installing `src/shopping-copilot/requirements.txt` + pytest.

### Remaining Verification (Post-Merge)

1. Open/update PR so CI runs **Shopping copilot tests** and PR image bake includes shopping-copilot when `src/shopping-copilot/**` or shared paths change.
2. After merge to `main` / `techx-dev-corp`, confirm prepare catalog OK (23) and verify-ecr finds `shopping-copilot` tag.
3. Confirm infra ECR repo exists before first push.

## Migration or Deployment Notes

1. Apply infra ECR (if not already) for both projects (`techx-dev-corp`, `techx-corp` / prod naming).
2. Merge this CI/CD change with the shopping-copilot application code on the same branch/PR set so Compose and bake stay equal.
3. First production promote after this lands may force-build shopping-copilot when PREV_TAG lacks that repository/tag (preflight moves missing PREV_TAG services to build).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| First publish fails verify-ecr if ECR repo missing | Medium | High | Create ECR via infra apply first |
| Shopping copilot tests fail on missing shared imports | Low | Medium | PYTHONPATH includes product-reviews; demo_pb2 co-located there |
| Full rebuild wall time +1 service | Low | Low | Accept; selective bake for single-service changes |

**Rollback procedure:**

Revert this change (workflows + bake + docs). Catalog assert will fail again if Compose still has shopping-copilot without bake membership — either keep service out of Compose or keep bake in sync.

<!-- Change trail: @hungxqt - 2026-07-19 - CI/CD release catalog includes shopping-copilot (23 services). -->
