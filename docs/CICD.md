# CI/CD — techx-corp-platform

This repository builds and pushes microservice container images to AWS ECR.
Helm deploy stays in `techx-corp-chart`.

## Workflows

| Workflow | File | When | What |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `pull_request` to `main` / `techx-dev-corp`; also `workflow_call` | Lint + selective unit tests |
| Build & Push | `.github/workflows/build-and-push.yml` | `push` to `main` / `techx-dev-corp` with changes under `src/**`, tags `v*`, `workflow_dispatch` | Gated multi-arch bake → ECR → verify → (dev) chart tag promote |

### Job graph (Build & Push)

```text
CI (reusable lint + unit tests)
  → prepare          # env, tag, service matrix, bake catalog validation
  → AWS/ECR preflight  # OIDC + verify 21 ECR repositories
  → build matrix     # 21 services, max-parallel: 4, fail-fast: false
  → verify ECR       # describe-images for every release tag
  → release-ready    # if: always(); sole gate for chart promotion
  → update-chart-dev # development only: direct-push values-dev.yaml tag
```

Failing CI never reaches AWS authentication or image push.  
`release-ready` succeeds only when **all** of CI, prepare, preflight, build, and verify-ecr succeed.

| Environment | After `release-ready` |
|---|---|
| `development` | Job **update-chart-dev** direct-pushes `default.image.tag` in chart `values-dev.yaml` on branch `techx-dev-corp` |
| `production` | Still **manual** chart values PR (`values-prod.yaml`); no automated chart write |

The workflow does **not** deploy Helm resources or call Argo CD APIs. Dev promotion relies on Argo CD auto-sync reading the chart Git commit.

### Path filter (branch pushes)

On branch pushes (`main`, `techx-dev-corp`), the publishing workflow runs **only** when at least one file under:

```text
src/**
```

changes. Examples that **do not** start a branch publish: docs, README, workflows, `docker-bake.hcl`, `docker-compose.yml`, `Makefile`, root config.

Any matching `src/**` change still builds and pushes the **full 21-image release set** (not a single service), because Helm uses one global image tag (plus matching `opensearch.image.tag`).

Git tag pushes (`v*`) and manual `workflow_dispatch` always run the full pipeline (no path filter). Use **workflow_dispatch** when you need to republish after bake/Compose/CI-only changes without touching `src/`.

### Environment mapping (Build & Push)

| Trigger | GitHub Environment | `IMAGE_NAME` (REGISTRY/PROJECT) |
|---|---|---|
| `push` to `main` | `production` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp` |
| tag `v*` | `production` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp` |
| `push` to `techx-dev-corp` | `development` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` |
| `workflow_dispatch` | chosen input | same as that environment’s `IMAGE_NAME` |

### Image naming convention

```text
[REGISTRY]/[PROJECT]/[SERVICE]:[VERSION]
```

Examples:

```text
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp/ad:sha-a1b2c3d
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp/checkout:sha-a1b2c3d
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp/frontend:v1.2.3
```

Compose / bake use:

```text
${IMAGE_NAME}/<service>:${DEMO_VERSION}
```

| Trigger | `IMAGE_VERSION` / `DEMO_VERSION` |
|---|---|
| push `main` / `techx-dev-corp` / dispatch | `sha-<7-char-sha>` (e.g. `sha-a1b2c3d`) |
| tag `v1.2.3` | git tag name (e.g. `v1.2.3`) |

**CI release identity vs local `.env`:** committed `.env` keeps `DEMO_VERSION=latest` (and a default `IMAGE_NAME`) for local Compose. The build job loads Dockerfile-related vars from `.env`, then **overrides** them with the prepare-resolved `IMAGE_NAME` / `DEMO_VERSION` / `IMAGE_VERSION` so ECR receives immutable tags (`sha-*` or `v*`).

### Release catalog (21 images)

Defined in `docker-bake.hcl` group `release` (layered over `docker-compose.yml`):

| Service |
|---|
| accounting, ad, cart, checkout, currency, email |
| flagd-ui, fraud-detection, frontend, frontend-proxy |
| image-provider, kafka, llm, load-generator, opensearch, payment |
| product-catalog, product-reviews, quote, recommendation, shipping |

`opensearch` is a **customized** image (`src/opensearch/Dockerfile`, based on `opensearchproject/opensearch:3.2.0` with unused plugins removed). CI pushes it to ECR; Helm’s OpenSearch subchart pulls that image (not the public Docker Hub image).

`prepare` asserts `release` equals all Compose build targets (21), with no duplicates or missing services. A newly added Compose build target must be listed in `docker-bake.hcl` group `release`.

### Registry cache

Each release target imports and exports BuildKit registry cache at:

```text
${IMAGE_NAME}/<service>:buildcache
```

Export uses `mode=max`, OCI media types, and an image manifest.  
**`buildcache` is a movable cache artifact only** — never a Helm-deployable runtime tag. Deploy only uses immutable release tags (`sha-*` or `v*`).

Platforms: `linux/amd64` and `linux/arm64` (QEMU on `ubuntu-latest`).

Build matrix settings:

| Setting | Value |
|---|---|
| `fail-fast` | `false` |
| `max-parallel` | `4` |
| runner | `ubuntu-latest` |
| `timeout-minutes` | `120` per service |
| builder | Buildx + `buildkitd.toml` (`max-parallelism = 4`) |

Environment-level concurrency uses `cancel-in-progress: false` so a canceled publish cannot leave a partially populated global tag.

PR CI does **not** run multi-arch bake. e2e / Cypress / tracetest are out of scope for PR CI.

---

## One-time operator setup

### 1–2. AWS IAM OIDC + ECR push roles (Terraform)

Managed in **`techx-corp-infra`** via module `modules/github-actions-ecr`:

| Environment stack | Role name | GitHub Environment | ECR repo | Creates OIDC provider? |
|---|---|---|---|---|
| `environments/production` | `techx-gha-platform-prod` | `production` | `techx-corp` | yes (account singleton) |
| `environments/development` | `techx-gha-platform-dev` | `development` | `techx-dev-corp` | no (looks up existing) |

Apply production first (creates `token.actions.githubusercontent.com` OIDC provider), then development:

```bash
terraform -chdir=environments/production plan -out=prod.tfplan
terraform -chdir=environments/production apply "prod.tfplan"

terraform -chdir=environments/development plan -out=dev.tfplan
terraform -chdir=environments/development apply "dev.tfplan"
```

Read role ARNs:

```bash
terraform -chdir=environments/production output github_actions_ecr_role_arn
terraform -chdir=environments/development output github_actions_ecr_role_arn
```

Trust subjects include the GitHub Environment **and** branch refs (`main` / tags for prod, `techx-dev-corp` for dev).

OIDC only — no long-lived AWS access keys.

### 3. GitHub Environments

In the GitHub repo **Settings → Environments**:

| Environment | Variable `AWS_ROLE_ARN` | Variable `IMAGE_NAME` (REGISTRY/PROJECT only) | Protection |
|---|---|---|---|
| `development` | ARN of `techx-gha-platform-dev` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` | optional |
| `production` | ARN of `techx-gha-platform-prod` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp` | required reviewers recommended |

Do **not** put the service name in `IMAGE_NAME`; bake appends `/<service>:<version>`.

Optional repository variable: `AWS_REGION=us-east-1` (workflows default to `us-east-1` if unset).

### 4. Operator setup — chart promote token (dev automation)

Cross-repo Git writes cannot use the platform repo’s default `GITHUB_TOKEN`. Job **`update-chart-dev`** authenticates to the **chart** repository with a PAT stored as a platform Actions secret.

#### How authentication works

| Concern | Identity |
|---|---|
| Platform workflow / AWS OIDC / ECR push | Platform `GITHUB_TOKEN` + environment role |
| Checkout + **push** to chart repo | Secret **`CHART_REPO_TOKEN`** (PAT) |
| Git commit author name/email | `github-actions[bot]` (cosmetic; set in the job) |

The Action does **not** “assume” GitHub’s built-in bot for write access to another repo. The **PAT owner** (or fine-grained token resource grants) is what GitHub authorizes for the push. Prefer a **dedicated machine user** for the PAT if you do not want a personal account owning the token.

Production chart promotion remains **manual** (no token write to `values-prod.yaml`).

#### Prerequisites

| Item | Value / notes |
|---|---|
| Platform GitHub repo | e.g. `tmcmanhcuong/tf2-corp-platform` (where `build-and-push.yml` runs) |
| Chart GitHub repo | default `tmcmanhcuong/tf2-corp-chart` |
| Chart branch for dev | default `techx-dev-corp` (Argo CD Application `techx-corp-dev` `targetRevision`) |
| Operator rights | Admin (or secrets:write) on platform repo; ability to create PATs; ability to configure chart branch rules |

#### Step A — Create a fine-grained PAT (recommended)

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Token name:** e.g. `techx-platform-chart-promote-dev`.
3. **Expiration:** set a finite expiry (e.g. 90 days) and calendar a rotation.
4. **Resource owner:** org or user that owns the chart repo.
5. **Repository access:** **Only select repositories** → select the chart repo only  
   (`tmcmanhcuong/tf2-corp-chart`, or your fork).
6. **Permissions → Repository permissions:**
   - **Contents:** **Read and write** (required for checkout + push of `values-dev.yaml`)
   - **Metadata:** Read-only (usually granted automatically)
   - Do **not** grant admin, workflows, or secrets permissions.
7. Generate the token and **copy it once** (GitHub will not show it again).

Classic PAT alternative (less preferred): `repo` scope on an account with write access to the chart repo. Still store it only as `CHART_REPO_TOKEN`.

#### Step B — Add the secret on the **platform** repository

1. Open the **platform** repo on GitHub (not the chart repo).
2. **Settings → Secrets and variables → Actions → New repository secret**.
3. Name: **`CHART_REPO_TOKEN`**
4. Value: paste the PAT from Step A → **Add secret**.

Do **not** commit the PAT to Git, put it in Environment variables (non-secret), or paste it into workflow logs.

#### Step C — Optional repository variables (defaults are usually enough)

In the **same platform** repo: **Settings → Secrets and variables → Actions → Variables**.

| Variable | Default | Purpose |
|---|---|---|
| `CHART_REPO` | `tmcmanhcuong/tf2-corp-chart` | Chart GitHub `owner/repo` |
| `CHART_BRANCH` | `techx-dev-corp` | Branch that receives the direct push and that Argo CD dev tracks |

Override only if your chart remote or branch names differ.

#### Step D — Allow the PAT identity to push chart branch `techx-dev-corp`

On the **chart** repo:

1. Confirm the PAT’s user (or machine user) has **write** access to the chart repository.
2. Review **Settings → Branches / Rulesets** for `techx-dev-corp`:
   - If **Require a pull request before merging** (or similar) blocks direct pushes, either:
     - add a **bypass** for the PAT’s user / team / app, or
     - temporarily allow force-free direct pushes for that identity only.
   - Status checks required on PR are fine for humans; they must not block the bot’s direct push path if you rely on automation.
3. Do **not** require signed commits for that identity unless the PAT workflow is also configured to sign (not implemented today).

#### Step E — Verify end-to-end

1. Ensure `CHART_REPO_TOKEN` exists on the platform repo.
2. Run a development publish:
   - Actions → **Build and push images** → environment **`development`**, or
   - push a change under `src/**` to platform branch `techx-dev-corp`.
3. Confirm job order: matrix builds → **Verify ECR tags** → **Release ready** (green) → **Update chart values-dev tag** (green).
4. On the chart repo, branch `techx-dev-corp`, open `values-dev.yaml` and confirm:

   ```yaml
   default:
     image:
       tag: "sha-<7char>"   # matches the platform release tag
   ```

5. Optional: `argocd app wait techx-corp-dev --sync --health --timeout 600`.

#### Failure modes (setup-related)

| Symptom | Fix |
|---|---|
| `Secret CHART_REPO_TOKEN is not set` | Complete Step B on the **platform** repo |
| `Repository not found` / checkout 404 | Wrong `CHART_REPO`, or PAT lacks access to that repo |
| `Permission denied` / push rejected | PAT Contents not Read/write; or branch rules block the PAT identity (Step D) |
| Job skipped entirely | Environment was not `development`, or `release-ready` failed |

Without `CHART_REPO_TOKEN`, development builds can still push images and pass `release-ready`, but **update-chart-dev fails** until the secret is set. Operators can still edit `values-dev.yaml` manually as a fallback.

#### Security and rotation

* Scope the PAT to the **chart repo only**; Contents read/write is enough.
* Prefer a **machine user** over a personal account for ownership and offboarding.
* Rotate on expiry or if the secret is exposed: create a new PAT → update `CHART_REPO_TOKEN` → revoke the old PAT.
* Revoking the PAT immediately stops automated dev promotes (images still publish).

### 5. First dry run

1. Merge workflow / bake changes to the development branch.
2. Dry-run development: push to `techx-dev-corp`, or Actions → **Build and push images** → `development`.
3. Confirm all 21 runtime tags and cache tags, for example:

   ```bash
   aws ecr describe-images --repository-name techx-dev-corp/ad \
     --image-ids imageTag=sha-<7char> --region us-east-1
   # also expect tag buildcache on each service repository
   ```

4. Confirm the workflow summary shows **Release ready**, then **Chart values-dev update** with the new tag.
5. Confirm chart `values-dev.yaml` on `techx-dev-corp` has `default.image.tag: "sha-<7char>"`.
6. Production: merge/push `main` (or tag `v*` / protected dispatch) only after development passes → `techx-corp`; open a **manual** chart values PR for prod.

---

## Local equivalent (manual)

Do **not** rely on `.env.override` for production (it may point at `/test`).

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 493499579600.dkr.ecr.us-east-1.amazonaws.com

docker buildx create --name techx-corp-builder --bootstrap --use \
  --driver docker-container --config ./buildkitd.toml

set -a
# shellcheck disable=SC1091
source .env
set +a
export IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp
export IMAGE_VERSION=sha-manual
export DEMO_VERSION=sha-manual

# Release group only (21 services + registry cache)
docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push
# Produces: .../techx-corp/ad:sha-manual + .../techx-corp/ad:buildcache , ...
```

Makefile (after setting `.env.override`):

```bash
make create-multiplatform-builder
make build-multiplatform-and-push   # invokes bake group "release"
```

Local non-push Compose builds (`make build`, `make start`) are unchanged and use BuildKit’s local cache.

---

## Failure recovery

| Failure | Recovery |
|---|---|
| CI (lint/unit) fails | Fix code; re-run. No AWS auth or images pushed. |
| prepare catalog assert fails | Add new Compose build targets to `docker-bake.hcl` group `release`. |
| preflight missing ECR repo | Create nested repo via `techx-corp-infra` ECR module; re-run. |
| Individual matrix build fails | Re-run failed jobs or full workflow; `fail-fast: false` keeps other services building. |
| verify-ecr reports missing tags | Re-run build for missing services or full workflow; do **not** promote chart values. |
| release-ready red | Treat as not promotable; `update-chart-dev` is skipped. |
| update-chart-dev fails: missing `CHART_REPO_TOKEN` | Add the secret (see §4); re-run failed job or full workflow. |
| update-chart-dev fails: push rejected / protected branch | Allow the PAT identity to push to `techx-dev-corp`, or temporarily open a manual values commit. |

Rollback of this CI design: revert workflow, `docker-bake.hcl`, Makefile, and docs. Existing `:buildcache` tags may remain or be deleted; they do not affect deployed SHA/version tags.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` does not match environment name or repo |
| `denied: User is not authorized to perform ecr:PutImage` | Role policy missing repo ARN or wrong repository name |
| Bake OOM / disk full | Runner disk; workflow frees space — re-run or use larger runner |
| Images pushed to wrong registry | `IMAGE_NAME` env var missing on GitHub Environment |
| Compose missing Dockerfile path | `.env` not sourced before bake |
| Catalog mismatch in prepare | New Compose `build:` service not listed in bake group `release` |

## Image promotion → GitOps (REL-09)

Platform CI builds, pushes, and verifies images. Deploy is Argo CD reading the chart repo (Git desired state).

Because the chart uses a **global** `default.image.tag` for all nested services (including first-party `opensearch`):

1. **Rebuild and push the full release set** (21 services, including `opensearch`) with the same tag.
2. **Wait for `release-ready`** (includes ECR `describe-images` for every service).
3. **Development:** job **update-chart-dev** direct-pushes `default.image.tag` in `values-dev.yaml` on chart branch `techx-dev-corp` (requires `CHART_REPO_TOKEN`).
4. **Production:** open a **manual** PR on the chart repo updating `values-prod.yaml` (`default.image.tag` only).
5. Argo CD auto-syncs (dev Application `techx-corp-dev`); optional wait: `argocd app wait techx-corp-dev --sync --health --timeout 600`.

Do **not** promote chart values while any matrix job or verification is incomplete.

```text
# Development
CI → prepare → preflight → build (all 21) → verify ECR → release-ready
  → update-chart-dev (direct push values-dev.yaml) → Argo auto-sync

# Production
CI → prepare → preflight → build (all 21) → verify ECR → release-ready
  → manual values-prod.yaml PR → merge → Argo sync
```

See chart runbook: `techx-corp-chart/docs/operations/gitops-argocd.md`.

## Security notes

- Actions pinned to full commit SHAs (major-version patch pins) with version comments.
- Weekly Dependabot updates for `github-actions` (`.github/dependabot.yml`).
- `id-token: write` only on preflight, build, and verify-ecr jobs.
- GitHub expressions passed into shell steps via quoted environment variables.
- OIDC authentication only; no long-lived AWS keys.

## Out of scope (v1)

- Automated **production** chart PR / write to `values-prod.yaml`
- Helm/kubectl deploy or Argo CD API calls from this repo
- Path-filtered partial image builds while using a global tag (unsafe for promotion)
- Per-service Helm runtime tags / movable runtime tags
- Native multi-arch runners, image security gates, SBOM/provenance, Cosign
- Full e2e / tracetest in PR CI
