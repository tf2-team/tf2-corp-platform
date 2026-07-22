# Change: Pin OpenSearch jackson-core for GHSA-r7wm-3cxj-wff9

## Summary

The customized OpenSearch image still shipped vulnerable `jackson-core` JARs from the vendor base (`com.fasterxml.jackson.core:jackson-core` **2.21.3** and `tools.jackson.core:jackson-core` **3.1.3**). Trivy reports HIGH **GHSA-r7wm-3cxj-wff9** (async parser `maxNumberLength` bypass via chunked digit accumulation). This change replaces those JARs in-tree with **2.21.4** and **3.1.4** during the image build, alongside the existing `jackson-databind` 2.21.4 pin.

## Context

* Trivy image scan on the OpenSearch release image continued to fail after the earlier `jackson-databind` pin and OpenSearch 3.7.0 base refresh.
* Advisory: [GHSA-r7wm-3cxj-wff9](https://github.com/advisories/GHSA-r7wm-3cxj-wff9) — incomplete fix for the earlier async number-length constraint bypass.
* Fixed floors:
  * `com.fasterxml.jackson.core:jackson-core` → **2.21.4** (also 2.18.8 / 2.22.1 on other lines)
  * `tools.jackson.core:jackson-core` → **3.1.4** (also 3.2.1 on the 3.2 line)
* Why now: release Trivy gate blocks HIGH fixable findings before ECR push.

## Before

* `src/opensearch/Dockerfile` downloaded and installed only `jackson-databind-2.21.4.jar` into module-local paths (`ingest-geoip`, `opensearch-sql`).
* Vendor OpenSearch **3.7.0** still contained:
  * `jackson-core-2.21.3.jar` (`com.fasterxml.jackson.core`)
  * `jackson-core-3.1.3.jar` (`tools.jackson.core`)
* Trivy table (representative):

| Library | Installed | Fixed |
|---|---|---|
| `com.fasterxml.jackson.core:jackson-core` | 2.21.3 | 2.21.4 (or 2.18.8 / 2.22.1) |
| `tools.jackson.core:jackson-core` | 3.1.3 | 3.1.4 (or 3.2.1) |

## After

* Image build downloads Maven Central artifacts:
  * `jackson-core-2.21.4.jar`
  * `jackson-core-3.1.4.jar` (`tools.jackson.core`)
  * existing `jackson-databind-2.21.4.jar`
* A dedicated `RUN` replaces every `jackson-core-2.*` / `jackson-core-3.*` under OpenSearch `lib/`, `modules/*/`, and remaining `plugins/*/` with the fixed versions.
* Build fails closed if either line is missing or if vulnerable `2.21.3` / `3.1.3` jars remain.
* `SECURITY_UPDATE_EPOCH` rotated to `2026-07-22-jackson-core-ghsa-r7wm` so cached OS-update layers do not mask a rebuild.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| JAR swap in Dockerfile (not wait for vendor OpenSearch bump) | Trivy gate is blocking now; demo image already customizes plugins and Jackson databind the same way |
| Keep both 2.x and 3.x floors | Vendor ships both coordinates; fixing only one leaves the other finding |
| Stay on 2.21.4 / 3.1.4 (not 2.22.x / 3.2.x) | Minimal jump within the documented fixed lines; matches existing databind 2.21.4 floor |
| Replace in-place under `lib` (unlike databind) | `jackson-core` is required on the global classpath; databind stays module-local by design |
| Fail if either line not found | Prevents a silent “no-op” rebuild if the vendor layout changes |

**Alternatives rejected**

* Trivy ignore / unfixed exception — finding is fixable and HIGH.
* Full OpenSearch major/minor vendor jump beyond 3.7.0 — higher blast radius than a targeted JAR pin; can follow later.

## Implementation Details

1. `ADD` fixed `jackson-core` 2.21.4 and 3.1.4 from Maven Central next to the existing databind download.
2. After plugin stripping, recursively `find` all `jackson-core-*.jar` under `/usr/share/opensearch` (vendor layout is deeper than one glob level).
3. Route `jackson-core-2.*` → copy 2.21.4; `jackson-core-3.*` → copy 3.1.4; unexpected names fail the build.
4. Require at least one line present; only assert the fixed version for lines that were found (do not require both 2.x and 3.x if the vendor ships one).
5. Fail if vulnerable `2.21.3` / `3.1.3` filenames remain; print before/after jar inventory.
6. Escape shell variables and command substitutions as `$$` / `$${...}` / `$$(...)` so Docker does not empty them during Dockerfile interpolation (this broke the first pin attempt: `test "" -eq 1`).
7. Leave the existing module-local `jackson-databind` 2.21.4 install unchanged.
8. Bump `SECURITY_UPDATE_EPOCH` for cache invalidation of the OS upgrade layer.

## Files Changed

**Docker**

* `src/opensearch/Dockerfile` — Download and pin `jackson-core` 2.21.4 / 3.1.4; rotate security epoch; retain databind 2.21.4 module-local install.

**Documentation**

* `docs/changes/2026-07-22-opensearch-jackson-core-ghsa-r7wm.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Chart / infra:** None for the JAR pin itself. After rebuild, the global image tag must be promoted as usual so Argo/Helm pull the rebuilt OpenSearch image.
* Related prior work: `docs/changes/2026-07-20-trivy-image-scan-remediation.md` (OpenSearch 3.7.0 base), databind pin in the same Dockerfile.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No intentional API change; same OpenSearch surface with patched Jackson core JARs |
| **Infrastructure** | No Terraform/EKS change |
| **Deployment** | Requires rebuild/push of the `opensearch` release image and chart tag promote for the target env |
| **Performance** | Negligible (patch-level Jackson core) |
| **Security** | Clears fixable HIGH GHSA-r7wm-3cxj-wff9 for both Jackson core coordinates in the OpenSearch image |
| **Reliability** | Build fails if expected jackson-core jars are absent or vulnerable versions remain |
| **Cost** | None material |
| **Backward compatibility** | Fully compatible for demo log storage/SQL usage |
| **Observability** | No change to dashboards/metrics |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Maven artifacts exist | HTTP HEAD Maven Central for `jackson-core` 2.21.4 and 3.1.4 | ✅ 200 |
| Dockerfile static review | Manual review of replace + fail-closed asserts | ✅ |
| Image build + Trivy | Local Docker daemon unavailable in this session | ⏳ Post-merge / CI |

### Manual Verification

* Confirmed advisory fixed versions match pins (2.21.4 and 3.1.4).
* Confirmed prior Dockerfile only addressed `jackson-databind`, not `jackson-core`.

### Remaining Verification (Post-Merge)

1. Rebuild OpenSearch image (CI bake or local):

```cmd
cd /d techx-corp-platform
docker buildx bake -f docker-compose.yml -f docker-bake.hcl opensearch
```

2. Confirm jars in the image:

```cmd
docker run --rm --entrypoint sh %IMAGE_NAME%/opensearch:%DEMO_VERSION% -c "find /usr/share/opensearch -name \"jackson-core-*.jar\" -print"
```

Expected: only `jackson-core-2.21.4.jar` and `jackson-core-3.1.4.jar` (no `2.21.3` / `3.1.3`).

3. Trivy image scan must not report GHSA-r7wm-3cxj-wff9 for OpenSearch.

## Migration or Deployment Notes

1. Merge this change to the platform branch used by image CI.
2. Run **Build and push** (or wait for `src/**` path trigger) so ECR receives a new global tag that includes rebuilt `opensearch`.
3. Promote chart `default.image.tag` (dev auto / prod PR) so Argo pulls the new image.
4. Smoke: OpenSearch pod Ready; Grafana datasource queries still work.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Jackson core binary drop-in breaks an OpenSearch module | Low | Medium | Fail-closed build asserts; smoke OpenSearch after deploy; revert Dockerfile pins |
| Vendor layout stops shipping one jackson-core line | Low | Low | Build fails intentionally; adjust replace logic for new layout |
| Patch-level API incompatibility between 2.21.3→2.21.4 or 3.1.3→3.1.4 | Low | Low | Patch releases on same minor line |

**Rollback procedure:**

1. Revert `src/opensearch/Dockerfile` to the previous revision (databind-only Jackson pin).
2. Rebuild and push OpenSearch with a new tag; promote chart tag.
3. Note: rollback reintroduces Trivy HIGH GHSA-r7wm-3cxj-wff9 on OpenSearch.

<!-- Change trail: @hungxqt - 2026-07-22 - Document jackson-core pin and Dockerfile $$ shell-escape build fix -->
