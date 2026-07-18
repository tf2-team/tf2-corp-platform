# Change: Document GitHub Actions variables and secrets setup

## Summary

Expanded `docs/CICD.md` with a dedicated operator section for configuring GitHub Actions environment variables, repository variables, and repository secrets required by the platform build-and-push workflow.

## Context

Operators needed a single, step-by-step reference for platform CI configuration (OIDC role ARN, ECR `IMAGE_NAME`, optional chart promote settings, and `CHART_REPO_TOKEN`). The previous guide scattered this across a short Environments subsection and the chart-promote PAT procedure, which made first-time setup easy to miss.

## Before

* §3 listed only a compact Environments table for `AWS_ROLE_ARN` / `IMAGE_NAME`.
* Repository variables (`AWS_REGION`, `CHART_REPO`, `CHART_BRANCH`) and the `CHART_REPO_TOKEN` secret were described later or only in the PAT walkthrough.
* No checklist or workflow resolution diagram for vars/secrets.
* Chart repo defaults in the doc used an outdated owner path in places.

## After

* §3 creates GitHub Environments only (names, protection, when used).
* **§4 Configure GitHub Actions variables and secrets** covers:
  * Scope (environment variable vs repository variable vs repository secret)
  * Required vs optional quick-reference tables
  * Step-by-step UI setup for env vars, optional repo vars, and `CHART_REPO_TOKEN`
  * Operator checklist
  * How jobs resolve `vars.*` / `secrets.*`
* Chart promote procedure renumbered to §5 and cross-references §4 for secret/variable placement.
* First dry run renumbered to §6.
* Troubleshooting extended for missing `AWS_ROLE_ARN` / `IMAGE_NAME`.
* `CHART_REPO` default aligned with workflow (`tf2-team/tf2-corp-chart`).
* Production `IMAGE_NAME` uses prod ECR project (`…/techx-prod-corp`), matching bootstrap IAM and operator registry.

## Technical Design Decisions

* Keep PAT creation detail in §5 (security-sensitive, multi-step) rather than duplicating it inside §4; §4 owns *where* secrets/vars live, §5 owns *how* to mint the PAT.
* Prefer Environment **variables** (not secrets) for `AWS_ROLE_ARN` and `IMAGE_NAME` so operators can audit values while still scoping them per environment — matching how `build-and-push.yml` reads `vars.AWS_ROLE_ARN` / `vars.IMAGE_NAME`.
* No workflow YAML changes; documentation only.

## Implementation Details

1. Replaced the short §3 Environments value table with environment creation guidance.
2. Inserted full §4 with tables, CMD terraform output examples, UI paths, checklist, and resolution diagram.
3. Updated §5 Step B/C/D labels and failure-mode cross-references.
4. Renumbered first dry run to §6; linked recovery/troubleshooting to §4.

## Files Changed

**Documentation:**

* `docs/CICD.md` — Added GitHub Actions variables/secrets configuration section; renumbered operator setup steps; aligned chart repo default and production `IMAGE_NAME` examples with workflow / mapping table.
* `docs/changes/2026-07-13-cicd-github-actions-vars-secrets.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Configuration values still come from `techx-corp-infra/bootstrap` outputs (`github_actions_ecr_*_role_arn`) and existing chart repo access; no code or Terraform change required.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No change |
| **Deployment** | Clearer one-time operator setup for platform CI |
| **Performance** | No change |
| **Security** | Documents correct secret placement and PAT scoping; no new secrets in Git |
| **Reliability** | Reduces misconfiguration (missing env vars / wrong `IMAGE_NAME`) |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible (docs only) |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| N/A | Documentation-only change | N/A |

### Manual Verification

* Reviewed `build-and-push.yml` for `vars.*` / `secrets.*` consumers (`AWS_ROLE_ARN`, `IMAGE_NAME`, `AWS_REGION`, `CHART_REPO`, `CHART_BRANCH`, `CHART_REPO_TOKEN`).
* Confirmed section numbering and cross-references (§4 ↔ §5, failure recovery, troubleshooting).

### Remaining Verification (Post-Merge)

* Operators should confirm Environments and secrets match the new checklist on the live platform GitHub repository.

## Migration or Deployment Notes

None for running clusters. New or rebuilt platform repos should follow **CICD.md §3–§4** before the first image publish.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Doc drift if workflow vars rename later | Low | Low | Update §4 when workflow changes |

**Rollback procedure:**

Revert `docs/CICD.md` (and this change document) to the previous commit.
