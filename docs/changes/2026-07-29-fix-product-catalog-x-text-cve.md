# Change: Remediate Product Catalog CVE-2026-56852 by Upgrading x/text

## Summary

Upgrade `golang.org/x/text` in `product-catalog` from `v0.37.0` to the minimum fixed version `v0.39.0` to remediate CVE-2026-56852. Upstream `v0.39.0` addresses an infinite-loop vulnerability and requires Go 1.25.0, which is fully compatible with the service's Go 1.25.5 toolchain.

## Context

CVE-2026-56852 affects `golang.org/x/text` versions prior to `v0.39.0` due to an infinite loop condition in text processing. The security policy requires zero fixable HIGH or CRITICAL CVE findings in container images. This targeted upgrade fixes the vulnerability without introducing application logic or API changes.

* Why needed now: Remediate CVE-2026-56852 to maintain compliance with image vulnerability policy.
* Upstream fix: https://go.googlesource.com/text/+/5ae8e578e495731553eddba11b2d0e86c91a00ce
* Module tag: https://go.googlesource.com/text/+/refs/tags/v0.39.0/go.mod

## Before

`src/product-catalog/go.mod` depended on `golang.org/x/text v0.37.0` (indirectly via OpenTelemetry and gRPC dependencies), which contains CVE-2026-56852.

## After

`src/product-catalog/go.mod` depends on `golang.org/x/text v0.39.0` (and `golang.org/x/mod v0.37.0` updated as required by Go module resolution). CVE-2026-56852 is remediated.

## Technical Design Decisions

* **Pin v0.39.0**: Upgraded strictly to `v0.39.0` rather than newer `v0.40.0` to minimize dependency drift.
* **No code/Dockerfile/chart changes**: The vulnerability fix is isolated within `golang.org/x/text`; no application code, protobuf, Dockerfile, Helm chart, or Terraform changes were necessary.
* **Fail-closed security gate**: Did not modify `.trivyignore.yaml` or Trivy severity thresholds.

## Implementation Details

1. Navigated to `src/product-catalog`.
2. Ran `go get golang.org/x/text@v0.39.0` followed by `go mod tidy`.
3. Verified `go.mod` updated `golang.org/x/text` to `v0.39.0` and `golang.org/x/mod` to `v0.37.0`.
4. Appended final-line `@hungxqt` change-trail comment to `src/product-catalog/go.mod`.
5. Created this change record in `docs/changes/2026-07-29-fix-product-catalog-x-text-cve.md` documenting the upgrade and `go.sum` exception.

## Files Changed

**Dependencies:**

* `src/product-catalog/go.mod` — Upgraded `golang.org/x/text` to `v0.39.0` and added `@hungxqt` change trail comment.
* `src/product-catalog/go.sum` — Updated checksums for `golang.org/x/text v0.39.0` and `golang.org/x/mod v0.37.0`.

**Documentation:**

* `docs/changes/2026-07-29-fix-product-catalog-x-text-cve.md` — This change record.

## Dependencies and Cross-Repository Impact

None. The change is fully contained within `techx-corp-platform`. `techx-corp-chart` and `techx-corp-infra` are untouched.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime behavior change |
| **Infrastructure** | No infrastructure or cloud resource change |
| **Deployment** | Requires normal image rebuild and chart digest promotion post-merge |
| **Performance** | No measurable performance change |
| **Security** | Remediates HIGH/CRITICAL CVE-2026-56852 in `product-catalog` |
| **Reliability** | Eliminates infinite-loop risk in text processing |
| **Cost** | No cost impact |
| **Backward compatibility** | Fully backward-compatible |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Module version | `go list -m golang.org/x/text` | ✅ `golang.org/x/text v0.39.0` |
| Module checksum verification | `go mod verify` | ✅ `all modules verified` |
| Go unit tests | `go test ./...` | ✅ Pass |
| Docker image build | `docker compose build product-catalog` | ✅ Success |
| Trivy security scan | `trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --skip-version-check local.invalid/pr-check/product-catalog:pr-local` | ✅ Pass (0 vulnerabilities) |
| Workflow path classifier | `python scripts/test_selective_publish_workflow.py` | ✅ Pass (`product-catalog` selected) |

### Manual Verification

* Verified `git status` diff contains only `src/product-catalog/go.mod`, `src/product-catalog/go.sum`, and `docs/changes/2026-07-29-fix-product-catalog-x-text-cve.md`.
* Confirmed final line of `go.mod` has `@hungxqt` change-trail comment.

### Remaining Verification (Post-Merge)

* Publish rebuilt `product-catalog` image through the CI security gate and promote chart digest to dev/prod environments.

## Migration or Deployment Notes

None. Standard CI/CD image build and Argo CD reconciliation path applies.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Dependency incompatibility | Low | Low | Validated with `go mod verify` and `go test ./...`. Revert commit if needed. |

**Rollback procedure:**

Revert git commit in `techx-corp-platform` back to `golang.org/x/text v0.37.0` and regenerate `go.sum`. Note that rollback reintroduces CVE-2026-56852 and will fail the Trivy security gate.

<!-- Change trail: @hungxqt - 2026-07-29 - Upgrade golang.org/x/text to fix CVE-2026-56852. Change trail exception for src/product-catalog/go.sum: generated checksum file does not support comments. -->
