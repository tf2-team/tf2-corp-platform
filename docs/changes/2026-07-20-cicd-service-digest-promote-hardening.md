# Change: CI/CD service-digest promote and pipeline hardening

## Summary

Hardened the platform publish pipeline: selective chart promotion now writes digests under chart `service-digest/`, security scan/sign focus on rebuilt images when selective, Cosign provenance accepts dispatch/tag without a merged PR, promote jobs require digest resolution, dead tag-update steps were removed, and PR/publish share `scripts/release_services.json`. Documentation in `docs/CICD.md` was aligned with the digest-based GitOps contract.

## Context

An evaluation of the platform CI/CD found doc/implementation drift (global tag promote vs selective digests), brittle sign/attest PR requirements, missing promote gates on `resolve-image-digests`, duplicated SAST on `workflow_call`, and a hardcoded 23-service catalog in multiple places. Chart-side consumption lives under folder name `service-digest` (companion chart change).

## Before

* Chart promote paths still contained large `if: false` blocks updating `default.image.tag`.
* Docs described tag promote as primary.
* `sign-and-attest` failed without a merged PR with APPROVED review (blocked dispatch/tags).
* Promote jobs did not require `resolve-image-digests` success.
* Trivy/sign always matrixed all 23 services.
* Semgrep/TruffleHog/Trivy IaC ran in reusable CI and again on publish.
* Release service list was hardcoded in workflow scripts.

## After

* Promote jobs write `service-digest/values-<service>.yaml` via `scripts/update_chart_service_digests.py`.
* Promote requires `release-ready` success, `resolve-image-digests` success, env match, and `build_count != 0`.
* Sign/attest records approved PR when present; otherwise allows `workflow_dispatch` / `v*` tag with actor in provenance.
* Trivy image scan and sign matrix use rebuild list when `build_count > 0`, else full catalog.
* PR CI skips SAST/secrets/IaC on `workflow_call`; publish still runs those jobs once.
* Shared catalog `scripts/release_services.json` + `scripts/check_release_catalog.py` in lint.
* `docs/CICD.md` documents service-digest promote and security behavior.

## Technical Design Decisions

* **Folder name `service-digest/`** — explicit operator request; keeps digest overlays out of chart root.
* **Skip chart promote when `build_count == 0`** — retag-only publishes produce no new digests.
* **Scan/sign rebuilt-only on selective** — retagged digests retain prior signatures/attestations; full catalog still scanned on full rebuild or empty-build fallback.
* **Dispatch/tag attest path** — Environment protection remains the human gate for manual republish; PR approval remains required for ordinary branch pushes.
* **Unit-test matrix** — no new service unit suites were invented; catalog consistency check added instead (most polyglot services still lack CI-ready unit tests).

## Implementation Details

1. Added `scripts/release_services.json` and `scripts/check_release_catalog.py`.
2. Updated `update_chart_service_digests.py` to default under `service-digest/`.
3. Expanded `scripts/test_secure_delivery_scripts.py` for path resolution and write tests.
4. Patched `.github/workflows/build-and-push.yml` (catalog load, scan/sign matrix, approval, promote, dead code removal).
5. Patched `.github/workflows/ci.yml` (catalog check, shared RELEASE_JSON, skip security on workflow_call).
6. Updated `docs/CICD.md`.

## Files Changed

**Workflows:**
* `.github/workflows/build-and-push.yml` — service-digest promote, selective scan/sign, flexible attest, promote gates.
* `.github/workflows/ci.yml` — shared catalog, catalog check, skip SAST on workflow_call.

**Scripts:**
* `scripts/release_services.json` — canonical 23-service list.
* `scripts/check_release_catalog.py` — bake vs JSON consistency.
* `scripts/update_chart_service_digests.py` — write under `service-digest/`.
* `scripts/test_secure_delivery_scripts.py` — unit coverage for promote script.

**Documentation:**
* `docs/CICD.md` — digest promote contract and security notes.
* `docs/changes/2026-07-20-cicd-service-digest-promote-hardening.md` — this record.

Change trail exception for `scripts/release_services.json`: JSON cannot contain comments.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-20-service-digest-helm-overlays.md`
* Chart must load `service-digest/values-*.yaml` in Argo Applications and render `image@digest` (companion change).
* Operators must merge chart support before expecting digest promote to change running pods.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No direct app code change; deploy pins move to digests when chart consumes overlays |
| **Infrastructure** | No Terraform change |
| **Deployment** | Dev/prod promote update `service-digest/` only for rebuilt services |
| **Performance** | Lower runner cost on selective rebuilds (fewer Trivy/sign jobs) |
| **Security** | Still blocking scans; attest path clearer for dispatch/tags |
| **Reliability** | Promote cannot run without successful digest map |
| **Backward compatibility** | Until digests exist, chart continues to use `default.image.tag` |
| **Observability** | Job summaries mention service-digest |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Catalog | `python scripts/check_release_catalog.py` | Pass |
| Script tests | `python scripts/test_secure_delivery_scripts.py` | Pass (7 tests) |

### Manual Verification

* Reviewed promote job paths and removed dead tag-update steps from workflow.

### Remaining Verification (Post-Merge)

* Run development `workflow_dispatch` selective rebuild; confirm chart branch gets `service-digest/` updates and Argo syncs digests.
* Confirm production PR body and branch naming for digest promote.

## Migration or Deployment Notes

1. Merge **chart** companion change first (or same day) so Argo loads `service-digest/` files.
2. Ensure `CHART_REPO_TOKEN` still has Contents + Pull requests write.
3. Optional: Environment protection on `production` for dispatch.
4. First promote after merge only updates rebuilt services; others keep tag-based images until rebuilt once.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Chart not consuming digests yet | Medium | Medium | Chart companion change; until then promote is Git-only |
| Dispatch without PR weakens audit | Low | Medium | Environment reviewers; provenance records actor |
| Selective scan misses retagged CVE | Low | Medium | Full rebuild / empty-build scans full catalog; periodic force full |

**Rollback procedure:**

1. Revert platform workflow/script/doc commit.
2. Optionally stop using `service-digest/` promote; operators can still set `default.image.tag` manually.

<!-- Change trail: @hungxqt - 2026-07-20 - Record platform CI/CD service-digest promote and hardening. -->
