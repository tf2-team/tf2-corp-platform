# Change: PR local image bake includes Trivy CVE scan

## Summary

Pull request CI now loads each changed release service image into the runner Docker daemon and runs the same Trivy HIGH/CRITICAL (fixable) gate used on the publish path, still without AWS credentials or ECR push. The stable **`PR image build`** check fails when either bake or Trivy fails.

## Context

Publish workflow already enforces **local amd64 bake → Trivy → multi-arch ECR push**. PR CI previously baked images only to catch Dockerfile/context compile failures (`output=type=cacheonly` for most services) and never scanned the resulting artifact. CVE regressions could still merge and only fail after push-time Trivy on `main` / `techx-dev-corp`.

* Security goal: surface the same fixable image CVE policy before merge.
* Keep PR path free of OIDC/ECR so the gate cannot publish tags.
* Align Trivy action pin, severity, `ignore-unfixed`, and temporary `shopping-copilot` exception with `build-and-push.yml`.

## Before

| Trigger | Image validation |
|---|---|
| Pull request | Local bake (`linux/amd64`, mostly `output=type=cacheonly`); no Trivy image scan |
| Push / tag / dispatch | Local bake → Trivy → multi-arch ECR push |

## After

| Trigger | Image validation |
|---|---|
| Pull request | Local bake (`linux/amd64`, `output=type=docker`) → **Trivy** on `local.invalid/pr-check/<service>:pr-local`; no AWS, no `--push` |
| Push / tag / dispatch | Unchanged |

## Technical Design Decisions

* **Reuse publish Trivy policy** (`aquasecurity/trivy-action` commit `a9c7b0f…` / Trivy `v0.69.3`, HIGH/CRITICAL, `ignore-unfixed: true`, shopping-copilot exit-code exception) so PR and publish disagree only on push, not on CVE rules.
* **Switch PR bake to `output=type=docker` for all services** because Trivy needs a local daemon image; `cacheonly` cannot be scanned. Disk cost is accepted; free-disk step remains first.
* **Placeholder IMAGE_NAME** `local.invalid/pr-check` + tag `pr-local` (unchanged identity) so no real registry is implied; preserve job env across `source .env` the same way publish preserves prepare-resolved tags.
* **Keep Trivy inside the matrix job** (not a separate PR job) so multi-GB images are not re-exported between jobs.
* **Do not add a new required-check name**; aggregator **`PR image build`** already covers matrix success/failure including the new scan step.

Known limitations:

* PR still scans **amd64 only** (same as publish pre-push scan).
* Full shared-path PRs still bake/scan all release services (heavier than selective).

## Implementation Details

1. Job `build-pr-images` sets `IMAGE_NAME`, `DEMO_VERSION`, and `IMAGE_REF` at job scope.
2. Bake step saves PR placeholders, sources committed `.env` for Dockerfile args, restores placeholders, bakes with `output=type=docker`, and `docker image inspect`s the tag.
3. Existing runtime smoke for `email` / `llm` / `opensearch` runs after load, before Trivy.
4. New step **Trivy scan local image** mirrors publish options and exit-code policy.
5. Job and aggregator summaries mention bake + Trivy; prepare plan text updated.
6. `docs/CICD.md` PR job graph, per-step table, security notes, and failure recovery updated.

## Files Changed

**CI:**

* `.github/workflows/ci.yml` — PR matrix: docker load for all services + Trivy; summary/aggregator wording.

**Documentation:**

* `docs/CICD.md` — PR graph, Trivy table, security note, recovery rows.
* `docs/changes/2026-07-23-pr-local-image-trivy-scan.md` — This change record.

## Dependencies and Cross-Repository Impact

None for runtime or infrastructure. Operators who already require **`PR image build`** automatically get the Trivy gate without a new branch-protection check name.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No ECR or IAM change |
| **Deployment** | No change to publish or chart promote |
| **Performance** | PR image jobs load full layers (heavier than `cacheonly`) and run Trivy; more disk/time on image-touching PRs |
| **Security** | PR path blocks fixable HIGH/CRITICAL image CVEs before merge (same policy as publish) |
| **Reliability** | Earlier failure signal; less likely to merge then fail publish Trivy |
| **Cost** | Additional Actions minutes/disk on image-affecting PRs |
| **Backward compatibility** | Required check name unchanged; fail-closed for new CVE findings on PRs |
| **Observability** | Step logs + job summary include Trivy and image ref |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow structure | Manual review of bake → inspect → optional smoke → Trivy order | ✅ Mirrors publish fail-closed order without AWS |
| Trivy options parity | Compared to `build-and-push.yml` build job Trivy step | ✅ Same action pin, version, severity, ignore-unfixed, shopping-copilot exception |
| IMAGE_NAME override | Job env saved before `source .env` | ✅ Same pattern as publish prepare-resolved tags |

### Manual Verification

* Reviewed `ci.yml` bake step cannot keep `.env` `DEMO_VERSION=latest` after override restore.
* Confirmed aggregator still treats matrix `skipped` as success when `build_count=0`.

### Remaining Verification (Post-Merge)

1. Open or update a PR that touches `src/<service>/**` and confirm matrix job runs **Bake** then **Trivy scan local image**.
2. Confirm a clean service passes and that a known fixable HIGH finding would fail the job (or rely on publish path history).
3. Confirm non-image PRs still skip matrix and green **`PR image build`**.

## Migration or Deployment Notes

1. No new secrets or environment variables.
2. Optional: remind reviewers that **`PR image build`** failure may now be CVE-related, not only Dockerfile compile.
3. When shopping-copilot is remediated, remove the temporary `exit-code: 0` exception in **both** `ci.yml` and `build-and-push.yml`.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Disk pressure from `type=docker` loads | Medium | Medium | Free-disk step retained; fail-fast false; re-run single service |
| Existing unfixed HIGH/CRITICAL block PRs | Medium | High | Same as publish; remediate image/deps; temporary shopping-copilot exception already present |
| Trivy DB download flakiness | Low | Medium | Re-run job; pin matches publish path |

**Rollback procedure:**

1. Revert `.github/workflows/ci.yml` Trivy step and restore prior bake `output` logic if needed.
2. Revert related `docs/CICD.md` sections.
3. No ECR or cluster cleanup (PR path never pushed).

<!-- Change trail: @hungxqt - 2026-07-23 - PR CI local image Trivy HIGH/CRITICAL gate. -->
