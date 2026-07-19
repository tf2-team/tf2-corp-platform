# Secure delivery pipeline — Person 1 scope

This change implements the CI Pipeline & Security Gates portion of Directive 10 in
`tf2-corp-platform`. It intentionally does not change the infrastructure or chart
repositories.

## Blocking release chain

`release-ready` now requires all of the following before either chart promotion job
can run:

- Trivy scans every release image and exits non-zero on HIGH or CRITICAL CVEs.
- Semgrep scans `src/` with `p/ci` and `p/owasp-top-ten` rules. It uses the PR
  base/push-before commit as a baseline so new findings block delivery while the
  pre-existing findings are remediated through a separate security backlog.
- TruffleHog scans Git history and fails on verified secrets.
- Every immutable image digest is signed with the configured AWS KMS Cosign key.
- A CycloneDX SBOM is generated and attached to each digest.
- A custom provenance attestation records the commit, merged PR number, latest
  approving reviewer, the three passing scan gates, and workflow run URL.

The workflow resolves the merged PR for the release commit and explicitly runs
`gh pr view --json reviews`. A release without an approved PR fails closed.

## Selective deploy contract

The platform workflow exports the ECR digest map, then calls
`scripts/update_chart_service_digests.py` with the final `build_services` list. The
script creates or updates only `values-<service>.yaml`; services copied from the
previous release by the retag path are not touched. `load-generator` also updates
its worker workload, because both workloads consume the same release image.

The chart-side integration must load these files and support
`imageOverride.digest` (plus `mem0.image.digest`). Until that companion change is
merged, chart promotion will create the files but the chart will not consume them.

## Controlled full rebuild

Manual full rebuild now defaults to `false`. Selecting it requires a non-empty
`full_rebuild_reason`; the reason is included in the prepare job's auditable release
summary.

## Repository settings

Protect `main` and `techx-dev-corp` and require at least the stable CI check plus the
security checks shown by the workflow. Require CODEOWNER review for workflow and
source changes. Repository/environment configuration must provide:

- `AWS_ROLE_ARN` and `IMAGE_NAME` as before.
- `COSIGN_KMS_KEY` (optional only when the default
  `awskms:///alias/tf2-cosign-signing-key` is correct).
- `CHART_REPO_TOKEN` for chart commit/PR automation.

GitHub branch protection is an external repository setting and cannot be enforced by
this repository's files alone.
