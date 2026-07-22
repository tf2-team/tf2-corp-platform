# Mandate 10 selective operator rebuild

## Problem

Production digest migration can discover an existing image that is missing a
trusted signature, SBOM, or provenance. The workflow previously offered no
auditable way to rebuild only that service unless its source changed; the only
manual override was a full-catalog rebuild.

## Change

`workflow_dispatch` now accepts `requested_services` and a mandatory
`requested_services_reason`. Every requested name is validated against the
23-service release catalog and becomes the exact `BUILD_SET` used by build,
scan, signing, attestations, and chart promotion.

The selective input cannot be combined with `force_full_rebuild=true`.
Path-based classification remains the default when no service is requested.

## Mandate 10 use

Rebuild only `ad`, whose current production digest is missing its KMS
signature, CycloneDX SBOM, and provenance:

```text
target_environment: production
requested_services: ad
requested_services_reason: Mandate 10 P3 artifact remediation for unsigned ad digest
force_full_rebuild: false
```

The run must pass `Release ready` and create a chart PR containing only
`service-digest/values-ad.yaml`.
