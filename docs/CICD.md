# CI/CD — techx-corp-platform

This repository builds and pushes microservice container images to AWS ECR.
Helm deploy stays in `techx-corp-chart`.

## Workflows

| Workflow | File | When | What |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `pull_request` to `main` / `techx-dev-corp`; also `workflow_call` | Lint + selective unit tests |
| Build & Push | `.github/workflows/build-and-push.yml` | `push` to `main` / `techx-dev-corp` with changes under `src/**`, tags `v*`, `workflow_dispatch` | Gated multi-arch bake → ECR → verify |

### Job graph (Build & Push)

```text
CI (reusable lint + unit tests)
  → prepare          # env, tag, service matrix, bake catalog validation
  → AWS/ECR preflight  # OIDC + verify 20 ECR repositories
  → build matrix     # 20 services, max-parallel: 4, fail-fast: false
  → verify ECR       # describe-images for every release tag
  → release-ready    # if: always(); sole gate for manual chart values PR
```

Failing CI never reaches AWS authentication or image push.  
`release-ready` succeeds only when **all** of CI, prepare, preflight, build, and verify-ecr succeed. That job is the only signal that permits a **manual** `techx-corp-chart` values PR.

This workflow is **read-only** toward the chart repository: it does not create PRs or deploy Helm resources (v1).

### Path filter (branch pushes)

On branch pushes (`main`, `techx-dev-corp`), the publishing workflow runs **only** when at least one file under:

```text
src/**
```

changes. Examples that **do not** start a branch publish: docs, README, workflows, `docker-bake.hcl`, `docker-compose.yml`, `Makefile`, root config.

Any matching `src/**` change still builds and pushes the **full 20-image release set** (not a single service), because Helm uses one global image tag.

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

### Release catalog (20 images)

Defined in `docker-bake.hcl` group `release` (layered over `docker-compose.yml`):

| Service |
|---|
| accounting, ad, cart, checkout, currency, email |
| flagd-ui, fraud-detection, frontend, frontend-proxy |
| image-provider, kafka, llm, load-generator, payment |
| product-catalog, product-reviews, quote, recommendation, shipping |

`opensearch` is classified under bake group `local-only`: Compose builds a customized image for local demos, while Helm deploys the external OpenSearch chart dependency. It is **not** pushed by CI.

`prepare` asserts `release ∪ local-only` equals all Compose build targets (21), with no duplicates or overlap. A newly added Compose build target must be classified in `docker-bake.hcl`.

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

### 4. First dry run

1. Merge workflow / bake changes to the development branch.
2. Dry-run development: push to `techx-dev-corp`, or Actions → **Build and push images** → `development`.
3. Confirm all 20 runtime tags and cache tags, for example:

   ```bash
   aws ecr describe-images --repository-name techx-dev-corp/ad \
     --image-ids imageTag=sha-<7char> --region us-east-1
   # also expect tag buildcache on each service repository
   ```

4. Confirm the workflow summary shows **Release ready** before any chart PR.
5. Production: merge/push `main` (or tag `v*` / protected dispatch) only after development passes → `techx-corp`.

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

# Release group only (20 services + registry cache)
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
| prepare catalog assert fails | Classify new Compose build targets in `docker-bake.hcl` (`release` or `local-only`). |
| preflight missing ECR repo | Create nested repo via `techx-corp-infra` ECR module; re-run. |
| Individual matrix build fails | Re-run failed jobs or full workflow; `fail-fast: false` keeps other services building. |
| verify-ecr reports missing tags | Re-run build for missing services or full workflow; do **not** open chart PR. |
| release-ready red | Treat as not promotable; no chart values PR. |

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
| Catalog mismatch in prepare | New Compose `build:` service not listed in bake release/local-only |

## Image promotion → GitOps (REL-09)

Platform CI **build & push + ECR verify only**. Deploy is Argo CD reading `techx-corp-chart`.

Because the chart uses a **global** `default.image.tag` for all nested services:

1. **Rebuild and push the full release set** (20 services) with the same tag.
2. **Wait for `release-ready`** (includes ECR `describe-images` for every service).
3. Only then open a **manual** PR on the chart repo updating `values-dev.yaml` or `values-prod.yaml`.
4. After merge, Argo CD syncs (`argocd app wait … --timeout 600`).

Do **not** open the values PR while any matrix job or verification is incomplete.

```text
CI → prepare → preflight → build (all 20) → verify ECR → release-ready
  → manual chart values PR → merge → Argo sync
```

See chart runbook: `techx-corp-chart/docs/operations/gitops-argocd.md`.

Automated chart PR creation remains a follow-up (Phase 6); ECR verification is implemented in this workflow.

## Security notes

- Actions pinned to full commit SHAs (major-version patch pins) with version comments.
- Weekly Dependabot updates for `github-actions` (`.github/dependabot.yml`).
- `id-token: write` only on preflight, build, and verify-ecr jobs.
- GitHub expressions passed into shell steps via quoted environment variables.
- OIDC authentication only; no long-lived AWS keys.

## Out of scope (v1)

- Automated chart PR creation or Helm deploy from this repo
- Path-filtered partial image builds while using a global tag (unsafe for promotion)
- Per-service Helm runtime tags / movable runtime tags
- Native multi-arch runners, image security gates, SBOM/provenance, Cosign
- Full e2e / tracetest in PR CI
