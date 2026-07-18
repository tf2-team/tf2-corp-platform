# Change: Add boto3 to Mem0 production image for RDS IAM auth

## Summary

After master-password bootstrap succeeded, the migrate Job failed on `alembic upgrade head` because `MEM0_RDS_IAM_AUTH=true` requires `boto3` to generate short-lived RDS IAM tokens, and the production image did not install it. `boto3==1.38.46` is pinned in `requirements-production.txt` (mem0 is installed with `--no-deps`, so transitive pyproject deps are not pulled in).

## Context

Runtime error:

```text
ModuleNotFoundError: No module named 'boto3'
...
RuntimeError: boto3 is required when MEM0_RDS_IAM_AUTH is enabled.
```

Call path: `alembic` → `db.py` `do_connect` listener → `mem0.utils.aws_rds_iam.generate_rds_iam_auth_token` → `import boto3`.

The Mem0 Dockerfile installs the submodule with `pip install --no-deps`, so even though the fork declares `boto3>=1.34.0`, it never lands in the image unless listed in `requirements-production.txt`.

## Before

* Production requirements had no `boto3`.
* Bootstrap used master password (no boto3).
* Alembic/API IAM connections failed at import.

## After

* `boto3==1.38.46` pinned as a direct production dependency.
* Contract test asserts `boto3==` remains present while `--no-deps` install is kept.

## Technical Design Decisions

* **Chosen:** pin `boto3` in platform production requirements (matches other direct pins; botocore/jmespath come transitively).
* **Rejected:** drop `--no-deps` for the mem0 package install — would silently pull unpinned upstream deps and break the controlled production dependency set.
* **Rejected:** password auth for alembic/API in cluster — production design is IRSA + RDS IAM for the app user after bootstrap.
* Pin version `1.38.46` is a recent 1.38.x line compatible with `boto3>=1.34.0` from the mem0 fork; not forced to absolute latest to limit surprise in CI bake.

## Implementation Details

1. Added `boto3==1.38.46` to `src/mem0/requirements-production.txt` with comments on `--no-deps` and RDS IAM.
2. Extended `test_production_image.py` with `test_boto3_is_pinned_for_rds_iam_auth`.

## Files Changed

**Dependencies:**
* `src/mem0/requirements-production.txt` — Pin `boto3==1.38.46`.

**Tests:**
* `src/mem0/tests/test_production_image.py` — Assert boto3 pin under `--no-deps` contract.

**Documentation:**
* `docs/changes/2026-07-19-mem0-boto3-rds-iam.md` — This change record.

## Dependencies and Cross-Repository Impact

* **techx-corp-chart:** No change. Chart already sets `MEM0_RDS_IAM_AUTH=true` and IRSA on the migrate Job / Deployment.
* **techx-corp-infra:** No change. Mem0 IRSA already grants `rds-db:connect` for the app user.
* Requires **rebuild and push** of the `mem0` image, then chart image-tag promote.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Alembic and API can generate RDS IAM auth tokens |
| **Infrastructure** | No change |
| **Deployment** | Selective mem0 image rebuild + tag promote |
| **Security** | Uses ambient IRSA credentials via boto3; no long-lived DB password for app user |
| **Reliability** | Unblocks migrate after bootstrap |
| **Cost** | Small image size increase (boto3 + botocore) |
| **Backward compatibility** | Additive dependency |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Unit tests | `python -m unittest discover -s src\mem0\tests -p "test_production_image.py" -v` | Pending run |
| Image import smoke (post-build) | `python -c "import boto3; import mem0.utils.aws_rds_iam"` | Pending rebuild |

### Manual Verification

* Confirmed failure stack matches missing boto3 under IAM auth path.
* Confirmed Dockerfile `--no-deps` and fork dependency declaration for boto3.

### Remaining Verification (Post-Merge)

1. Rebuild/push mem0 image.
2. Promote chart tag; re-run migrate Job.
3. Expect bootstrap (master password) then alembic (IAM token) both succeed.

## Migration or Deployment Notes

1. Merge platform change; wait for CI matrix bake of `mem0` (or bake locally and push).
2. Promote `default.image.tag` / Mem0 image tag via normal chart process.
3. Retry migrate Job after new image is live.

```cmd
cd /d techx-corp-platform
python -m unittest discover -s src\mem0\tests -p "test_production_image.py" -v
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| boto3/botocore size or CVE noise | Low | Low | Pin exact version; upgrade deliberately |
| IRSA still missing rds-db:connect | Low | High | Separate infra check if token gen works but connect fails |

**Rollback procedure:**

1. Revert the requirements pin and rebuild only if a different packaging approach ships first.
2. Re-promote previous image tag that lacks boto3 will re-break IAM migrations.

<!-- Change trail: @hungxqt - 2026-07-19 - Document boto3 pin for Mem0 RDS IAM auth. -->
