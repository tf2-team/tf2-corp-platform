# Change: Document bootstrap ownership of GitHub CI/CD IAM

## Summary

Platform deployment and CI/CD docs were updated so operators source GitHub Actions OIDC ECR push role ARNs from `techx-corp-infra` **bootstrap** outputs instead of production/development environment stacks.

## Context

Infra moved account-level GitHub OIDC provider creation and both platform ECR push roles into `bootstrap/`. Platform runbooks still told operators to read `github_actions_ecr_role_arn` from environment Terraform outputs and implied production created the OIDC provider.

## Before

* `docs/CICD.md` described roles as managed per environment stack with production creating the OIDC singleton.
* `docs/DEPLOYMENT.md` listed GHA OIDC as part of production provision and used env outputs for `AWS_ROLE_ARN`.

## After

* Setup steps point at `terraform -chdir=bootstrap` for OIDC + `techx-gha-platform-*` role ARNs.
* Environment provision steps no longer claim to create GHA OIDC/roles.
* `IMAGE_NAME` examples aligned with `techx-prod-corp` / `techx-dev-corp` where those docs were updated.

## Technical Design Decisions

* Documentation-only change in this repository; IAM resources live in `techx-corp-infra`.
* Kept role **names** stable so existing GitHub Environment variable values may not need updates if ARNs are unchanged after import.

## Implementation Details

1. Updated operator setup table and commands in `docs/CICD.md`.
2. Updated Phase 1 bootstrap/production/dev steps in `docs/DEPLOYMENT.md`.
3. Added this change record.

## Files Changed

**Documentation:**
* `docs/CICD.md` — bootstrap-managed OIDC/roles; output commands; Environment variable sources.
* `docs/DEPLOYMENT.md` — bootstrap phase includes GHA IAM; env stacks no longer create OIDC roles.
* `docs/changes/2026-07-12-move-github-cicd-iam-to-bootstrap.md` — this change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-infra/docs/changes/2026-07-12-move-github-cicd-iam-to-bootstrap.md` (implementation + state migration).
* Operators must complete infra bootstrap apply/import before relying on new output paths.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No code/runtime change |
| **Deployment** | Operator docs only; secret wiring source path changes |
| **Backward compatibility** | Old env outputs removed in infra — docs prevent stale instructions |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| N/A | Documentation only | N/A |

### Manual Verification

* Cross-checked role names and bootstrap output names against infra change.

### Remaining Verification (Post-Merge)

* After infra bootstrap import/apply, set GitHub Environment `AWS_ROLE_ARN` from bootstrap outputs if needed.

## Migration or Deployment Notes

None for platform code. Follow infra change doc for AWS state migration, then:

```bash
terraform -chdir=bootstrap output github_actions_ecr_production_role_arn
terraform -chdir=bootstrap output github_actions_ecr_development_role_arn
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Operators follow old env outputs | Medium | Low | Docs updated; env outputs removed in infra |

**Rollback procedure:** Revert this documentation change if infra ownership is rolled back.
