# Change: Force jackson-databind 2.21.4 on ad and fraud-detection

## Summary

Hard-force `jackson-databind` (and related Jackson modules) to **2.21.4** in the ad and fraud-detection Gradle builds so Trivy HIGH findings **CVE-2026-54512** and **CVE-2026-54513** cannot reappear when images are baked from source in CI. Flagd pulls `jackson-databind:2.21.2`; a soft `runtimeOnly` pin alone is insufficient as a durable floor.

## Context

* Trivy image scan on the ad image reported `com.fasterxml.jackson.core:jackson-databind` at installed version **2.21.2** (HIGH, fixable at 2.18.8 / 2.21.4 / 3.1.4).
* Ad is built **from source** in CI (`docker buildx bake` of `src/ad/Dockerfile`), not retagged. The vulnerable JAR is packaged by Gradle `downloadRepos` / `installDist` into the image.
* Root cause: `flagd:0.13.3` → `flagd-core:1.2.0` → `jackson-databind:2.21.2` (affected range includes 2.19.0–2.21.3).
* An earlier remediation used `resolutionStrategy.force`; reverts left only a soft version declaration. This change restores a hard floor.

## Before

* Ad declared `runtimeOnly` jackson 2.21.4 without `resolutionStrategy.force` or `jackson-bom` enforcement.
* Fraud-detection used a dependency constraint only.
* Transitive request from flagd-core remained `2.21.2`; without a forced floor, CI-built images can still ship `jackson-databind-2.21.2.jar` when resolution does not upgrade.

## After

* Ad and fraud-detection force Jackson core modules to **2.21.4** (annotations **2.21**).
* Both apply `enforcedPlatform(jackson-bom:2.21.4)` plus constraints.
* `dependencyInsight` reports selection reason **Forced** for `jackson-databind:2.21.4`; `2.21.2 -> 2.21.4`.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Keep 2.21.4 (not 2.22.x) | Documented fixed version for CVE-2026-54512/54513 on the 2.21 line; minimal jump |
| `resolutionStrategy.force` + `enforcedPlatform` + constraints | Defense in depth; force survives transitive BOMs and mixed Jackson lines from flagd / json-schema-validator |
| Align fraud-detection | Same flagd stack; prevent the same finding on the next from-source bake |
| No Dockerfile change | Packaging already copies resolved Gradle classpath; fix belongs in resolution |

**Alternatives rejected**

* Upgrading flagd only — does not guarantee a fixed Jackson until flagd-core bumps.
* Trivy ignore — hides a fixable HIGH with a published patch.

## Implementation Details

1. `src/ad/build.gradle`: add `jacksonAnnotationsVersion`, `configurations.configureEach { resolutionStrategy.force ... }`, `enforcedPlatform(jackson-bom)`, and databind constraints; retain direct `runtimeOnly` pins.
2. `src/fraud-detection/build.gradle.kts`: same force + jackson-bom; keep existing databind constraint.
3. Verified locally with `gradlew dependencyInsight --dependency jackson-databind --configuration runtimeClasspath` (ad): selected **2.21.4**, reason **Forced**.

## Files Changed

**Java / Kotlin build**

* `src/ad/build.gradle` — Force Jackson 2.21.4 / annotations 2.21; jackson-bom; constraints.
* `src/fraud-detection/build.gradle.kts` — Same force floor for flagd transitive Jackson.

**Documentation**

* `docs/changes/2026-07-21-force-jackson-databind-ad-fraud.md` — This change record.

## Dependencies and Cross-Repository Impact

* After merge, CI must **bake ad (and fraud-detection if classified changed) from source** so Trivy scans the rebuilt digests. Chart promote follows existing release-ready flow.
* Related chart/infra: None for this commit (image digests change only after a successful publish).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Same Jackson 2.x API line; patch-level security bump only |
| **Infrastructure** | No Terraform change |
| **Deployment** | Requires from-source bake of ad / fraud-detection before chart digest promote |
| **Performance** | Negligible |
| **Security** | Clears fixable HIGH CVE-2026-54512/54513 for jackson-databind 2.21.2 |
| **Reliability** | No expected runtime change |
| **Cost** | One multi-arch rebuild of affected services |
| **Backward compatibility** | Fully compatible on Jackson 2.21 line |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Dependency insight (ad) | `gradlew dependencyInsight --dependency jackson-databind --configuration runtimeClasspath` (from `src/ad`) | ✅ Selected 2.21.4, Forced; `2.21.2 -> 2.21.4` |

### Manual Verification

* Confirmed transitive path `flagd` → `flagd-core` → `jackson-databind:2.21.2` is upgraded by force.

### Remaining Verification (Post-Merge)

* CI: Build and push images (from-source bake for `ad`, and `fraud-detection` if in build matrix).
* CI: Trivy image scan on ad must not report CVE-2026-54512/54513 for jackson-databind 2.21.2.
* Optional local: after image build, confirm only `jackson-databind-2.21.4.jar` under `/usr/src/app/build/install/.../lib/`.

## Migration or Deployment Notes

1. Merge this change to the branch CI bakes from.
2. Run **Build and push images** so ad (and fraud-detection when changed) rebuild from source — do not rely on retag for these services after this fix.
3. Confirm Trivy matrix is green for ad before promoting chart digests.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Jackson force conflicts with a future flagd that needs a different line | Low | Low | Revisit force when upgrading flagd; keep floor ≥2.21.4 |
| GHA BuildKit cache serves old layer | Low | Medium | Content hash on `build.gradle` invalidates dep layer; force full rebuild if needed |

**Rollback procedure:**

1. Revert this commit in `techx-corp-platform`.
2. Rebuild ad / fraud-detection from source.
3. Note: rollback reintroduces the Trivy HIGH for jackson-databind 2.21.2.

<!-- Change trail: @hungxqt - 2026-07-21 - Force jackson-databind 2.21.4 for ad and fraud-detection Trivy HIGH -->
