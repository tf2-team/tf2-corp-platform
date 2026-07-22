# Change: CI/CD local build and Trivy gate before ECR push

## Summary

The platform **Build and push images** workflow now builds each release service image locally on the runner, scans it with Trivy, and only then authenticates to AWS and pushes a multi-arch image to ECR. Vulnerable images no longer land in the private registry before the CVE gate.

## Context

Previously the publish path baked multi-arch images with `--push` first, then ran a separate `trivy-image-scan` job against tags already in ECR. That left a window where HIGH/CRITICAL findings could exist in ECR until (or if) the scan job failed and blocked `release-ready`. Operators asked for a fail-closed order: **local build → Trivy → push only on pass**.

* Security goal: never write a failed-scan image to ECR for a matrix leg.
* Multi-arch remains the deployable contract (`linux/amd64` + `linux/arm64` from `docker-bake.hcl`).
* Scan target is the local `linux/amd64` image (runner architecture); multi-arch push reuses GHA BuildKit layer cache after a clean scan.

## Before

1. `build` matrix: OIDC + ECR login → `docker buildx bake … --push` (multi-arch).
2. `verify-ecr`: `describe-images` for `BUILD_SET` under the new tag.
3. `trivy-image-scan` matrix: pull/scan images **from ECR**; fail on fixable HIGH/CRITICAL.
4. Sign/attest and chart promotion only after scan success (but the image was already in ECR).

## After

1. `build` matrix (per service in `BUILD_SET`):
   * Local `linux/amd64` bake with `output=type=docker` (no AWS credentials, no push).
   * Trivy on the local tag `${IMAGE_NAME}/<service>:${VERSION}` (same severity/ignore-unfixed rules; temporary `shopping-copilot` exit-code exception retained).
   * Only after Trivy passes: OIDC + ECR login → multi-arch `docker buildx bake … --push`.
2. `verify-ecr` unchanged semantically (confirms pushed tags).
3. Separate `trivy-image-scan` job **removed**; image CVE gate is part of `build`.
4. `sign-and-attest` / `release-ready` depend on `build` + `verify-ecr` (and remaining security jobs), not a standalone Trivy image job.

## Technical Design Decisions

* **Scan embedded in `build` (not a later job):** Multi-GB images cannot cheaply move between jobs as artifacts. Same-job local load + scan is the practical gate before push.
* **Scan amd64 only, push multi-arch:** Multi-platform images cannot be `--load`ed into a single docker daemon. Scanning the primary runner architecture is industry-standard; arm64 layers still publish via the second bake with GHA cache reuse for amd64.
* **AWS login after Trivy:** Preflight still uses OIDC to assert ECR repos exist, but the matrix leg does not call ECR until the scan step succeeds, so a failed scan never `PutImage`s for that service.
* **Removed separate Trivy job** rather than leaving a no-op, to avoid double-scanning and misleading job names in branch protection / release-ready.

Known limitations:

* Trivy does not independently re-scan the arm64 image after push.
* A failed multi-arch push after a clean Trivy pass can leave no (or partial) ECR tag for that attempt; re-run the job. Immutable tags mean a successful partial multi-arch push is rare; Buildx typically publishes the multi-arch manifest as a unit.

## Implementation Details

1. Reordered steps in `.github/workflows/build-and-push.yml` job `build`.
2. Local bake: `--set "*.platform=linux/amd64" --set "*.output=type=docker"`; `docker image inspect` confirms the tag exists before Trivy.
3. Trivy via `aquasecurity/trivy-action` (same pin/version/options as the former post-ECR job).
4. Multi-arch push step only runs if prior steps succeed (default Actions step dependency).
5. Deleted job `trivy-image-scan`; updated `sign-and-attest` and `release-ready` `needs` / gate evaluation.
6. Documented the new order in `docs/CICD.md` and the DEPLOYMENT CI tip.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — Local bake → Trivy → ECR push; remove post-ECR Trivy job; update release-ready / sign needs.

**Documentation:**

* `docs/CICD.md` — Job graph, per-service publish table, recovery row, security notes.
* `docs/DEPLOYMENT.md` — CI job graph tip.
* `docs/changes/2026-07-22-cicd-trivy-before-ecr-push.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Chart promotion, ECR repository layout, image tag contract, and Cosign still apply after a successful gated push. No infra module changes required.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change to services |
| **Infrastructure** | No Terraform/ECR layout change |
| **Deployment** | Same promote path after `release-ready`; images that fail Trivy never reach ECR on that matrix leg |
| **Performance** | Slightly longer build jobs (local amd64 bake + scan + multi-arch push); amd64 layers reuse GHA cache on second bake |
| **Security** | Stronger: CVE gate before registry write |
| **Reliability** | Fail-closed earlier for vulnerable images; no ECR pollution on scan failure |
| **Cost** | Extra runner minutes for dual bake; lower risk of orphan vulnerable tags |
| **Backward compatibility** | Job name `trivy-image-scan` no longer exists; do not require it in branch protection. Gate is `Build <service>` success |
| **Observability** | Job summary notes `local amd64 bake → Trivy → multi-arch ECR push` |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow structure | Reviewed `build` step order and `needs` for `verify-ecr`, `sign-and-attest`, `release-ready` | ✅ Local-only Trivy precedes ECR login/push; no remaining `trivy-image-scan` job references |
| Docs consistency | Reviewed `docs/CICD.md` / `docs/DEPLOYMENT.md` against workflow | ✅ Pass |

### Manual Verification

* Confirmed YAML job graph: build no longer logs into ECR before Trivy; multi-arch push is a later step.
* Confirmed shopping-copilot temporary `exit-code: 0` exception retained on the in-build Trivy step.

### Remaining Verification (Post-Merge)

1. Run **Build and push images** on a single-service change (or `workflow_dispatch` with `requested_services`).
2. Confirm matrix log order: local bake → Trivy table → ECR login → multi-arch push.
3. Optionally re-run with a known HIGH finding (or temporarily lower a test image) and confirm the job fails **before** ECR login and that `verify-ecr` does not see a new tag for that service.

## Migration or Deployment Notes

1. Merge this change to the platform default branches used by CI.
2. If branch protection or dashboards required check name **Trivy image scan**, remove that requirement; success of **Build \<service\>** now includes the image CVE gate.
3. No chart or infra deploy sequence change.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Local `type=docker` load OOMs large images (e.g. OpenSearch) | Medium | Medium | Existing free-disk step; re-run or larger runner; consider tar/OCI export if needed |
| Dual bake increases wall time | Medium | Low | GHA cache reuse on amd64; accept trade-off for security |
| Arm64-only vulnerability not seen by amd64 scan | Low | Medium | Accept residual multi-arch gap; optional follow-up multi-arch scan |
| Operators still expect job `trivy-image-scan` | Low | Low | Document removal; release-ready summary labels build as including Trivy |

**Rollback procedure:**

1. Revert `.github/workflows/build-and-push.yml`, `docs/CICD.md`, and `docs/DEPLOYMENT.md` to the pre-change revision.
2. Restore the post-ECR `trivy-image-scan` job and prior `needs` if rolling back the workflow alone.

<!-- Change trail: @hungxqt - 2026-07-22 - Record CI/CD local Trivy gate before ECR push. -->
