# Change: Pin Jackson Cores/Databind and Scrub OpenSAML Metadata (OpenSearch Trivy HIGH)

## Summary

Clear the five Trivy HIGH findings on the customized OpenSearch image by pinning freestanding Jackson 2.x/3.x jars to fixed releases and removing stale Jackson Maven metadata from `opensaml-*-all.jar` inside the retained security plugin.

## Context

After retaining `opensearch-security` for SEC-06, image CI Trivy reported:

| Library | Location | Severity | Fix |
|---|---|---|---|
| `jackson-core` 2.21.3 | `jackson-core-2.21.3.jar` | HIGH GHSA-r7wm-3cxj-wff9 | 2.21.4 |
| `jackson-core` 2.21.3 | nested in `opensaml-3.7.0.0-all.jar` | HIGH GHSA-r7wm-3cxj-wff9 | scrub / 2.21.4 |
| `jackson-databind` 2.21.3 | nested in `opensaml-3.7.0.0-all.jar` | HIGH CVE-2026-54512/54513 | scrub / 2.21.4 |
| `jackson-core` 3.1.3 | `jackson-core-3.1.3.jar` | HIGH GHSA-r7wm-3cxj-wff9 | 3.1.4 |

Pipeline policy fails `release-ready` on HIGH/CRITICAL image findings.

## Before

* Dockerfile pinned only module/plugin `jackson-databind` 2.x copies.
* Global `lib/jackson-core-2.21.3.jar` and `lib/jackson-core-3.1.3.jar` remained vulnerable.
* Security plugin `opensaml-3.7.0.0-all.jar` still contained `META-INF/maven/com.fasterxml.jackson.*` metadata at 2.21.3 (no shaded Jackson classes).
* Security plugin freestanding `jackson-databind-3.1.3.jar` was not upgraded to 3.1.4.

## After

* Download and install pins: Jackson 2.21.4 (`jackson-core`, `jackson-databind`) and Jackson 3.1.4 (`tools.jackson` core/databind).
* Replace `lib/jackson-core-2.*` → `jackson-core-2.21.4.jar` and `lib/jackson-core-3.*` → `jackson-core-3.1.4.jar`.
* Replace all remaining module/plugin `jackson-databind-2.*` / `3.*` jars with the pins (including security + sql + ingest-geoip).
* Rewrite `opensaml-*-all.jar` without Jackson Maven metadata or Jackson `META-INF/services` entries that Trivy attributes to 2.21.3.
* Build asserts absence of 2.21.3/3.1.3 cores and unpinned databind paths.

## Technical Design Decisions

* **Pin in-image vs wait for upstream OpenSearch 3.7.x bump:** CI is blocked now; pin is the same pattern already used for databind.
* **Scrub opensaml metadata instead of rebuilding OpenSAML:** Inspection showed the fat jar has Maven metadata + service names for Jackson but **zero** `com/fasterxml/jackson` class entries. Scrubbing removes the false Trivy surface without changing runtime SAML classes under `org/opensaml`.
* **JDK `jar` rewrite (not Python zipfile):** The vendor opensaml fat jar has overlapped zip entries; Python 3.11+ `zipfile` raises `BadZipFile`. The image’s bundled `${OPENSEARCH_HOME}/jdk/bin/jar` extracts and repacks cleanly.
* **Keep databind out of `lib/`:** Preserve OpenSearch classpath rules; only `jackson-core` is global.
* **Also pin databind 3.1.4:** Proactively clear security’s freestanding 3.1.3 databind (fixed line for the same CVE family).

## Implementation Details

1. Bump `SECURITY_UPDATE_EPOCH` so BuildKit does not reuse a stale layer.
2. `ADD` four pinned jars from Maven Central into `/tmp/pins/`.
3. After plugin slim, run a Python pin/scrub script with hard asserts.
4. Delete `/tmp/pins` after install.

## Files Changed

**Image:**
* `src/opensearch/Dockerfile` — Jackson 2.21.4 / 3.1.4 pins; opensaml metadata scrub; build asserts.

**Documentation:**
* `docs/changes/2026-07-22-opensearch-trivy-jackson-pins.md` — This change record.

## Dependencies and Cross-Repository Impact

* No chart change required. SEC-06 HTTPS clients unchanged.
* Related earlier change: `docs/changes/2026-07-22-opensearch-retain-security-plugin.md` (security plugin retention).
* Requires image rebuild/push and chart image tag promote for prod.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | None expected for basic-auth log store |
| **Security** | Clears reported Trivy HIGH Jackson findings on the OpenSearch image |
| **Deployment** | New image digest/tag; OpenSearch rollout |
| **Observability** | Unblocks CI `release-ready` for opensearch when combined with security retention |
| **Backward compatibility** | Compatible; jar minor/patch only |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Maven pin URLs | HEAD 2.21.4 / 3.1.4 artifacts | ✅ 200 |
| opensaml structure | Inspect plugin zip: metadata-only Jackson entries | ✅ No jackson classes |
| Image build asserts | Dockerfile `python3` pin/scrub asserts | Pending CI bake |
| Trivy re-scan | CI image security job on rebuilt `opensearch` | Pending CI |

### Manual Verification

* Base image inventory (public `opensearchproject/opensearch:3.7.0`): confirmed `lib/jackson-core-2.21.3.jar`, `lib/jackson-core-3.1.3.jar`, security `opensaml-3.7.0.0-all.jar`.
* OpenSAML jar: Jackson present only under `META-INF/maven/com.fasterxml.jackson.*` and three service files.

### Remaining Verification (Post-Merge)

1. Bake/push `opensearch` (or full release set).
2. Confirm Trivy image job: 0 HIGH/CRITICAL for jackson-core/databind/opensaml findings above.
3. Smoke OpenSearch Ready + HTTPS basic auth + log export.

## Migration or Deployment Notes

```cmd
cd /d techx-corp-platform
REM With registry/env loaded:
docker buildx bake -f docker-compose.yml -f docker-bake.hcl opensearch --push
```

Then promote the global image tag via the normal chart path.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| OpenSAML/SAML features break after metadata scrub | Low | Medium | Metadata-only removal; SAML classes untouched; basic auth unaffected |
| Classpath misses renamed core jars | Low | High | Asserts require new filenames present and old versions gone |
| Trivy still finds nested signature | Low | Medium | Re-inspect jar contents; extend scrub list if needed |

**Rollback procedure:** Revert Dockerfile to previous pin layer and redeploy prior image tag.

<!-- Change trail: @hungxqt - 2026-07-22 - Pin Jackson cores/databind and scrub opensaml for Trivy HIGH. -->
