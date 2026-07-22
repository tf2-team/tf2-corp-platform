# Change: BUILD_SET-only image promotion

## Summary

The secure delivery workflow now treats `BUILD_SET` as the only publish unit. A
service that did not change is not rebuilt, retagged, scanned as a new release,
signed again, or written into a chart promotion PR.

## Behavior

- `src/<service>/**` selects only that release service.
- Shared image inputs (`pb/**`, `buildkitd.toml`, `.env`, `.gitmodules`) select
  the full release catalog.
- `force_full_rebuild=true` remains a break-glass path and requires
  `full_rebuild_reason`.
- `previous_tag` and both the ECR and FastEmbed retag paths are removed.
- An empty `BUILD_SET` publishes and promotes nothing.
- Verify ECR, Trivy image scan, digest resolution, Cosign signing, SBOM,
  provenance, and chart digest promotion all consume the same `BUILD_SET`.
- Production promotion only opens a chart PR; it does not deploy or auto-merge.

## Required evidence

- One-service change: one build and one digest overlay update.
- Three-service change: exactly three builds and three digest overlay updates.
- No release-service change: no image publish and no chart promotion.
- A failed scan/sign/attestation prevents `Release ready` and chart mutation.
- An unchanged service retains its prior digest and pod-template hash.

## Rollback

Revert this workflow commit. Do not restore global retag promotion during an
active incident; use `force_full_rebuild=true` with a reviewed reason if the
entire catalog genuinely needs rebuilding.

<!-- Change trail: @MinhKhoa2209 - 2026-07-22 - Mandate 10 P2 BUILD_SET-only promotion. -->
