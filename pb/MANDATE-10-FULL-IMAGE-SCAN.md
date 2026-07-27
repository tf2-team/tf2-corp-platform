# Mandate 10 full image-scan acceptance

This documentation-only marker intentionally lives under `pb/`, a shared image
input path. The pull-request classifier therefore selects the complete
`scripts/release_services.json` catalog for local Linux/AMD64 builds and
fail-closed Trivy scanning.

Acceptance constraints:

- run the normal test and security jobs;
- build all release images locally;
- block on fixable `HIGH` or `CRITICAL` findings;
- do not configure AWS credentials;
- do not log in to ECR;
- do not push or deploy any image.
