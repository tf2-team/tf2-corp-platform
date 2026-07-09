# CI/CD — techx-corp-platform

This repository builds and pushes microservice container images to AWS ECR.
Helm deploy stays in `techx-corp-chart`.

## Workflows

| Workflow | File | When | What |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `pull_request` / `push` to `main`, `techx-dev-corp` | Lint + selective unit tests |
| Build & Push | `.github/workflows/build-and-push.yml` | `push` to `main` / `techx-dev-corp`, tags `v*`, `workflow_dispatch` | Multi-arch `docker buildx bake` → ECR |

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

Platforms: `linux/amd64,linux/arm64` (same as `docs/DEPLOYMENT.md` Phase 3).

CI does **not** run full multi-arch bake (too slow). e2e / Cypress / tracetest are out of scope for PR CI.

---

## One-time operator setup

### 1–2. AWS IAM OIDC + ECR push roles (Terraform)

Managed in **`techx-corp-infra`** via module `modules/github-actions-ecr`:

| Environment stack | Role name | GitHub Environment | ECR repo | Creates OIDC provider? |
|---|---|---|---|---|
| `enviroments/production` | `techx-gha-platform-prod` | `production` | `techx-corp` | yes (account singleton) |
| `enviroments/development` | `techx-gha-platform-dev` | `development` | `techx-dev-corp` | no (looks up existing) |

Apply production first (creates `token.actions.githubusercontent.com` OIDC provider), then development:

```bash
terraform -chdir=enviroments/production plan -out=prod.tfplan
terraform -chdir=enviroments/production apply "prod.tfplan"

terraform -chdir=enviroments/development plan -out=dev.tfplan
terraform -chdir=enviroments/development apply "dev.tfplan"
```

Read role ARNs:

```bash
terraform -chdir=enviroments/production output github_actions_ecr_role_arn
terraform -chdir=enviroments/development output github_actions_ecr_role_arn
```

Trust subjects include the GitHub Environment **and** branch refs (`main` / tags for prod, `techx-dev-corp` for dev).

### 3. GitHub Environments

In the GitHub repo **Settings → Environments**:

| Environment | Variable `AWS_ROLE_ARN` | Variable `IMAGE_NAME` (REGISTRY/PROJECT only) | Protection |
|---|---|---|---|
| `development` | ARN of `techx-gha-platform-dev` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` | optional |
| `production` | ARN of `techx-gha-platform-prod` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp` | required reviewers recommended |

Do **not** put the service name in `IMAGE_NAME`; bake appends `/<service>:<version>`.

Optional repository variable: `AWS_REGION=us-east-1` (workflows default to `us-east-1` if unset).

No long-lived AWS access keys are required.

### 4. First dry run

1. Merge workflow files to `main`.
2. Dry-run development: push to branch `techx-dev-corp`, or Actions → **Build and push images** → `development`.
3. Confirm images:

   ```bash
   aws ecr describe-images --repository-name techx-dev-corp --region us-east-1 --max-items 5
   ```

4. Production: merge/push `main` (or tag `v*` / protected dispatch) → `techx-corp`.

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

docker buildx bake -f docker-compose.yml --push \
  --set "*.platform=linux/amd64,linux/arm64"
# Produces: .../techx-corp/ad:sha-manual , .../techx-corp/checkout:sha-manual , ...
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` does not match environment name or repo |
| `denied: User is not authorized to perform ecr:PutImage` | Role policy missing repo ARN or wrong repository name |
| Bake OOM / disk full | Runner disk; workflow frees space — re-run or use larger runner |
| Images pushed to wrong registry | `IMAGE_NAME` env var missing on GitHub Environment |
| Compose missing Dockerfile path | `.env` not sourced before bake |

## Out of scope

- Helm upgrade / smoke tests (`techx-corp-chart`)
- Path-filtered partial image builds
- Full e2e / tracetest in PR CI
