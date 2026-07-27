# Mandate 10 image-scan acceptance

This file intentionally lives in the `shopping-copilot` service context so the
development pull request exercises the selective PR image build for this
service.

Acceptance criteria:

- `BUILD_SET` contains only `shopping-copilot`.
- The image is built locally on the GitHub-hosted runner.
- Trivy scans the local image for fixable `HIGH` and `CRITICAL` findings.
- Any matching finding returns a non-zero exit code.
- The PR workflow does not authenticate to or push to ECR.

This is a safe positive-path trigger. Negative evidence must come from the
scanner result itself or a dedicated non-release fixture; no vulnerable package
is introduced by this file.

<!-- Trigger CI verification for ci-gate fix -->

