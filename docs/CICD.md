# CI/CD — techx-corp-platform

This repository builds and pushes microservice container images to AWS ECR.
Helm deploy stays in `techx-corp-chart`.

## Workflows

| Workflow | File | When | What |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `pull_request` to `main` / `techx-dev-corp`; also `workflow_call` | Lint + selective unit tests; on PRs only, local (no-push) image bake for changed services |
| Build & Push | `.github/workflows/build-and-push.yml` | `push` to `main` / `techx-dev-corp` with image-affecting path changes, tags `v*`, `workflow_dispatch` | Gated multi-arch bake and/or ECR retag → verify all 23 tags → Mem0 FastEmbed artifact (build/retag) → chart promote (dev push / prod PR) |

### Job graph (PR CI)

```text
lint  ||  unit-tests  ||  prepare-pr-images → build-pr-images (matrix) → pr-image-build
```

| Job | When | Behavior |
|---|---|---|
| **prepare-pr-images** | `pull_request` only | Diff PR base…head; classify full vs selective bake list (same path rules as publish) |
| **build-pr-images** | PR and `build_count != 0` | `docker buildx bake` per changed service: **linux/amd64 only**, registry cache disabled, `output=type=cacheonly`, **no** AWS OIDC, **no** ECR login, **no** `--push` |
| **pr-image-build** | always on PR | Stable required-check aggregator (success if prepare ok and matrix success or skipped) |

`workflow_call` from Build & Push runs **lint + unit-tests only** (PR image jobs are skipped). Publish still owns multi-arch bake + ECR.

**Required checks (branch protection):** require **`PR image build`**, **`Semgrep
SAST`**, and **`TruffleHog secrets`**. Image promotion is additionally blocked by
**`Trivy image scan`** and
**`Sign and attest <service>`** for every catalog service. See
`docs/changes/2026-07-19-secure-delivery-person-1.md` for repository settings and the
selective per-service digest contract.

**PR path classification** (same image-affecting roots as publish):

| Change | PR bake plan |
|---|---|
| `src/<release-service>/**` | Selective: bake those services only |
| `third-party/mem0` (submodule pin) | Selective: bake `mem0` only |
| `pb/**`, `buildkitd.toml`, `.env`, `.gitmodules` | Full: all 23 release services |
| `docker-compose.yml`, `docker-bake.hcl` | Selective: catalog change only (no automatic full matrix); bake services that also have `src/**` changes |
| Docs / workflows / other non-image paths only | Skip bake matrix (`build_count=0`); **pr-image-build** still succeeds |

PR bake intentionally differs from publish: single platform, no registry cache, no push. It exists to catch Dockerfile/context compile failures (e.g. missing `COPY` of a new package) before merge.

### Job graph (Build & Push)

```text
CI (reusable lint + unit tests)
  → prepare            # env, tag, bake catalog validation, classify build vs retag
  → AWS/ECR preflight  # OIDC + verify 23 ECR repos; refine lists if PREV_TAG missing
  → build matrix       # changed services only (bake from source + GHA BuildKit cache)
  → retag matrix       # unchanged services: PREV_TAG → NEW_TAG (parallel with build)
  → verify ECR         # describe-images for every release service under NEW_TAG
  → Mem0 FastEmbed     # build model cache when mem0 bakes; else S3 retag PREV_TAG→NEW_TAG
  → release-ready      # if: always(); sole gate for chart promotion
  → update-chart-dev      # development only: always() + release-ready success + env
  → create-chart-prod-pr  # production only: always() + release-ready success + env
```

Failing CI never reaches AWS authentication or image push.  
`release-ready` succeeds when CI, prepare, preflight, and verify-ecr succeed, build/retag are each **success** or **skipped** (skipped when that side of the plan is empty), and the Mem0 FastEmbed job succeeds (skip-with-warning when `MEM0_FASTEMBED_ARTIFACT_S3_URI` is unset). At least one of build/retag must have run.  
Chart promote jobs also use `always()` so a skipped empty build/retag matrix does not cascade-skip them after a green `release-ready`.

| Environment | After `release-ready` |
|---|---|
| `development` | Job **update-chart-dev** direct-pushes `default.image.tag` in chart `values-dev.yaml` on branch `techx-dev-corp` |
| `production` | Job **create-chart-prod-pr** opens a chart PR updating `values-prod.yaml` on base `main` (no auto-merge) |

The workflow does **not** deploy Helm resources, call Argo CD APIs, or merge production chart PRs. Dev promotion relies on Argo CD auto-sync after the direct push; prod deploy still requires a human to merge the chart PR.

### Path filter (branch pushes)

On branch pushes (`main`, `techx-dev-corp`), the publishing workflow runs when at least one file under these paths changes:

```text
src/**
third-party/mem0
.gitmodules
pb/**
docker-compose.yml
docker-bake.hcl
buildkitd.toml
.env
```

Examples that **do not** start a branch publish: docs, README, workflows, `Makefile`, and other root config not listed above.

Git tag pushes (`v*`) and manual `workflow_dispatch` always run the pipeline (no path filter).

### Selective rebuild (build vs retag)

Helm still uses **one global image tag** for all release services. Every successful publish must leave all **23** images present under the new tag (`sha-<7>` or `v*`). Selective CI does **not** promote a partial catalog.

| Service classification | Action |
|---|---|
| **Changed** (`src/<service>/**`, or `third-party/mem0` for mem0) | `docker buildx bake … --push` from source (BuildKit uses GHA `type=gha` layer cache) |
| **Unchanged** | Retag previous runtime image: `PREV_TAG` → `NEW_TAG` via `docker buildx imagetools create` (same digest, new tag) |
| **Shared / global path** (`pb/**`, `.env`, `buildkitd.toml`, `.gitmodules`) | **Full** bake of all 23 (no retag) |
| **Catalog only** (`docker-compose.yml`, `docker-bake.hcl`) | **Selective**: does not by itself bake every service; new services missing `PREV_TAG` are moved to build by preflight |

**When mode is full**

* Git tag `v*`
* `workflow_dispatch` with `force_full_rebuild: true` (default)
* First push / zero `before` SHA
* Shared path change above
* Selective requested but no usable `PREV_TAG`

**When mode is selective** (branch push with only per-service `src/<service>/` changes, catalog edits, or dispatch with `force_full_rebuild: false` and a previous tag)

* `PREV_TAG` defaults to `sha-<first-7-of-github.event.before>` on branch pushes
* `workflow_dispatch` can set `previous_tag` (e.g. `sha-a1b2c3d` or `v1.2.3`)
* Preflight checks each retag candidate exists in ECR under `PREV_TAG`; missing services are moved into the build list

Non-release paths under `src/` (e.g. `src/flagd`, Grafana config) do not force a service bake; if nothing maps to a release service, all 23 are retagged to the new global tag.

**Mem0 FastEmbed artifact** (S3, not ECR) follows the same classification as the mem0 image:

| mem0 image side | FastEmbed action |
|---|---|
| **Build** | Rebuild model cache and upload under `…/${NEW_TAG}/` |
| **Retag** | Copy S3 objects `…/${PREV_TAG}/` → `…/${NEW_TAG}/` (no Hugging Face download) |
| **URI unset** | Job succeeds with a warning skip so image promote is not blocked |

Set GitHub Environment variable `MEM0_FASTEMBED_ARTIFACT_S3_URI` on `development` / `production` to enable publish. **Must match chart `mem0.modelDelivery.s3Prefix` and the IRSA-allowed prefix** (not a free-form path):

```text
# production example (IRSA: fastembed/paraphrase-multilingual-MiniLM-L12-v2/*)
s3://techx-prod-tf2-ai-models-<ACCOUNT_ID>/fastembed/paraphrase-multilingual-MiniLM-L12-v2
```

CI uploads to `${MEM0_FASTEMBED_ARTIFACT_S3_URI}/${VERSION}/`. The chart composes the same layout: `${s3Prefix}/${imageTag}/${archiveName}`. A wrong prefix (e.g. `…/mem0/fastembed`) makes objects unreadable by the Mem0 SA and `fetch-mem0-fastembed` fails with S3 403.

| Ref | Purpose |
|---|---|
| GHA `type=gha,scope=<service>` | BuildKit **layer** cache in GitHub Actions only — never an ECR tag |
| `…/<service>:<PREV_TAG>` → `…/<service>:<NEW_TAG>` | Skip source rebuild for unchanged services while keeping the global tag contract |

### workflow_dispatch inputs

| Input | Default | Purpose |
|---|---|---|
| `target_environment` | required | `development` or `production` |
| `force_full_rebuild` | `true` | Bake all 23 from source when true |
| `previous_tag` | empty | When force is false, tag to retag unchanged services from |

### Environment mapping (Build & Push)

| Trigger | GitHub Environment | `IMAGE_NAME` (REGISTRY/PROJECT) |
|---|---|---|
| `push` to `main` | `production` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp` |
| tag `v*` | `production` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp` |
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
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp/frontend:v1.2.3
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

### Release catalog (23 images)

Defined in `docker-bake.hcl` group `release` (layered over `docker-compose.yml`):

| Service |
|---|
| accounting, ad, cart, checkout, currency, email |
| flagd-ui, fraud-detection, frontend, frontend-proxy |
| image-provider, kafka, llm, load-generator, mem0, opensearch, payment |
| product-catalog, product-reviews, quote, recommendation, shipping, shopping-copilot |

`opensearch` is a **customized** image (`src/opensearch/Dockerfile`, based on `opensearchproject/opensearch:3.2.0` with unused plugins removed). CI pushes it to ECR; Helm’s OpenSearch subchart pulls that image (not the public Docker Hub image).

`mem0` is a normal matrix service (multi-arch bake + retag). Its FastEmbed model cache is published separately to S3 under the same global tag identity (build when mem0 bakes; S3 retag otherwise).

`shopping-copilot` is a normal matrix service (multi-arch bake + retag). PR CI also runs `Shopping copilot tests` (pytest under `src/shopping-copilot/tests`).

`prepare` asserts `release` equals all Compose build targets (23), with no duplicates or missing services. A newly added Compose build target must be listed in `docker-bake.hcl` group `release`.

### BuildKit cache and retag

Each release target imports and exports BuildKit cache via **GitHub Actions cache** (not ECR):

```text
type=gha,scope=<service>
cache-to: type=gha,mode=max,scope=<service>
```

This avoids pushing movable tags such as `:buildcache` into ECR, which fails when repositories use `image_tag_mutability=IMMUTABLE`.  
Deploy only uses immutable release tags (`sha-*` or `v*`). Local multiplatform push clears `cache-from` / `cache-to` (GHA cache is unavailable outside Actions).

Selective publishes additionally copy multi-arch **runtime** manifests:

```text
docker buildx imagetools create \
  --tag ${IMAGE_NAME}/<service>:${NEW_TAG} \
  ${IMAGE_NAME}/<service>:${PREV_TAG}
```

That reuses the previous image digest under the new global tag; it does not rebuild layers and does not use GHA cache.

Platforms: `linux/amd64` and `linux/arm64` (QEMU on bake jobs only).

Build / retag matrix settings:

| Setting | Value |
|---|---|
| `fail-fast` | `false` |
| `max-parallel` | `23` |
| runner | `ubuntu-latest` |
| `timeout-minutes` | `120` bake / `20` retag per service |
| builder | Buildx + `buildkitd.toml` (`max-parallelism = 4`) on bake jobs |

Environment-level concurrency uses `cancel-in-progress: false` so a canceled publish cannot leave a partially populated global tag.

PR CI runs **local single-arch** bake for changed services (no ECR). Multi-arch bake + push remains post-merge / dispatch only. e2e / Cypress / tracetest are out of scope for PR CI.

---

## One-time operator setup

### 1–2. AWS IAM OIDC + ECR push roles (Terraform bootstrap)

Managed in **`techx-corp-infra/bootstrap`** (account-level, with the remote state bucket). Module `modules/github-actions-ecr` creates the IAM roles; the GitHub OIDC provider is created once in bootstrap.

| Bootstrap role key | Role name | GitHub Environment | ECR project prefix |
|---|---|---|---|
| `production` | `techx-gha-platform-prod` | `production` | `techx-prod-corp/*` |
| `development` | `techx-gha-platform-dev` | `development` | `techx-dev-corp/*` |

Apply bootstrap **before** environment stacks (and before platform image push):

```bash
terraform -chdir=bootstrap plan -out=bootstrap.tfplan
terraform -chdir=bootstrap apply "bootstrap.tfplan"
```

Read role ARNs:

```bash
terraform -chdir=bootstrap output github_actions_ecr_production_role_arn
terraform -chdir=bootstrap output github_actions_ecr_development_role_arn
terraform -chdir=bootstrap output github_oidc_provider_arn
```

Trust subjects include the GitHub Environment **and** branch refs (`main` / tags for prod, `techx-dev-corp` for dev).

OIDC only — no long-lived AWS access keys.

### 3. GitHub Environments

Create two Environments on the **platform** GitHub repository (**Settings → Environments → New environment**):

| Environment name | Typical protection | Used when |
|---|---|---|
| `development` | optional | push to `techx-dev-corp`, or `workflow_dispatch` → `development` |
| `production` | required reviewers recommended | push to `main`, tags `v*`, or `workflow_dispatch` → `production` |

Environment **names must match exactly** (`development` / `production`). Build jobs select the environment from the prepare step; OIDC trust policies in bootstrap also key off these names.

Variable and secret values for each environment are configured in **§4** below.

### 4. Configure GitHub Actions variables and secrets

Platform workflows read configuration from **GitHub Actions variables** and **secrets**. Nothing below is committed to Git.

| Scope | Where to set | Who can read | Use for |
|---|---|---|---|
| **Environment variable** | Settings → Environments → *env* → Environment variables | Only jobs that declare `environment: <name>` | Per-env AWS role + ECR base (`AWS_ROLE_ARN`, `IMAGE_NAME`) |
| **Repository variable** | Settings → Secrets and variables → Actions → **Variables** | All workflows in the repo | Optional shared defaults (`AWS_REGION`, `CHART_REPO`, `CHART_BRANCH`) |
| **Repository secret** | Settings → Secrets and variables → Actions → **Secrets** | All workflows (masked in logs) | Sensitive tokens (`CHART_REPO_TOKEN`) |

Do **not** store PATs or role ARNs in the repository, in Environment *secrets* unless required, or in plain workflow logs. Prefer **Environment variables** for non-secret per-env config (`AWS_ROLE_ARN`, `IMAGE_NAME`) so values are visible to operators but scoped by environment.

#### 4.1 Quick reference (required vs optional)

**Environment variables** (set on **each** of `development` and `production`):

| Name | Required | Example / source | Consumed by |
|---|---|---|---|
| `AWS_ROLE_ARN` | **Yes** | Bootstrap output `github_actions_ecr_development_role_arn` or `…_production_role_arn` | `preflight`, `build`, `verify-ecr` (OIDC `role-to-assume`) |
| `IMAGE_NAME` | **Yes** | `REGISTRY/PROJECT` only — see table below | `preflight`, `build`, `verify-ecr` (bake push path + `describe-images`) |

| Environment | `IMAGE_NAME` value (REGISTRY/PROJECT only) |
|---|---|
| `development` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` |
| `production` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp` |

Do **not** put a service name in `IMAGE_NAME`. Bake appends `/<service>:<version>` only (layer cache uses GHA `type=gha`, not ECR tags).

**Repository variables** (optional; workflow defaults apply if unset):

| Name | Required | Default if unset | Purpose |
|---|---|---|---|
| `AWS_REGION` | No | `us-east-1` | AWS region for OIDC + ECR CLI |
| `CHART_REPO` | No | `tf2-team/tf2-corp-chart` | Chart GitHub `owner/repo` for chart promote jobs |
| `CHART_BRANCH` | No | `techx-dev-corp` | Chart branch that receives the dev tag push (Argo CD dev `targetRevision`) |
| `CHART_PROD_BRANCH` | No | `main` | Chart base branch for production promote PRs (Argo CD prod `targetRevision`) |

**Repository secrets**:

| Name | Required | Value | Consumed by |
|---|---|---|---|
| `CHART_REPO_TOKEN` | **Yes for chart promote (dev + prod)** | Fine-grained (or classic) PAT on the chart repo: **Contents: Read and write**, and **Pull requests: Read and write** (prod PR job) | **update-chart-dev**, **create-chart-prod-pr** |

Without `CHART_REPO_TOKEN`, development and production can still build, push, and pass **release-ready**; only the chart promote jobs fail. Operators can still edit chart values manually as a fallback.

PR **CI** (`ci.yml`) needs no repository variables or secrets.

#### 4.2 Step-by-step — Environment variables (`AWS_ROLE_ARN`, `IMAGE_NAME`)

1. Obtain role ARNs after bootstrap apply:

   ```cmd
   cd /d techx-corp-infra
   terraform -chdir=bootstrap output github_actions_ecr_development_role_arn
   terraform -chdir=bootstrap output github_actions_ecr_production_role_arn
   ```

2. Open the **platform** repo on GitHub → **Settings → Environments**.
3. Open **`development`** (create it first if missing — §3).
4. Under **Environment variables** → **Add variable**:

   | Name | Value |
   |---|---|
   | `AWS_ROLE_ARN` | ARN from `github_actions_ecr_development_role_arn` |
   | `IMAGE_NAME` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` |

5. Open **`production`** and add the same names with production values:

   | Name | Value |
   |---|---|
   | `AWS_ROLE_ARN` | ARN from `github_actions_ecr_production_role_arn` |
   | `IMAGE_NAME` | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp` |

6. Confirm `IMAGE_NAME` has **no** trailing slash and **no** service segment (wrong: `…/techx-prod-corp/ad`).

#### 4.3 Step-by-step — Repository variables (optional)

1. Platform repo → **Settings → Secrets and variables → Actions → Variables** tab.
2. **New repository variable** for any override you need:

   | Name | When to set |
   |---|---|
   | `AWS_REGION` | If ECR/OIDC is not in `us-east-1` |
   | `CHART_REPO` | If the chart remote is not `tf2-team/tf2-corp-chart` |
   | `CHART_BRANCH` | If Argo CD dev tracks a branch other than `techx-dev-corp` |
   | `CHART_PROD_BRANCH` | If Argo CD prod tracks a branch other than `main` |

Leave unset when the workflow defaults match your layout.

#### 4.4 Step-by-step — Repository secret (`CHART_REPO_TOKEN`)

1. Create a fine-grained PAT with **Contents: Read and write** and **Pull requests: Read and write** on the **chart** repository only (full procedure in **§5**).
2. Platform repo → **Settings → Secrets and variables → Actions → Secrets** tab.
3. **New repository secret**:
   - Name: `CHART_REPO_TOKEN` (exact spelling)
   - Value: the PAT → **Add secret**
4. Do **not** put the PAT in Environment variables, commit it, or print it in workflow steps.

#### 4.5 Configuration checklist

| # | Item | Scope | Done when |
|---|---|---|---|
| 1 | Environments `development` and `production` exist | Environments | Names match workflow |
| 2 | `AWS_ROLE_ARN` on both environments | Env variables | Matches bootstrap outputs |
| 3 | `IMAGE_NAME` on both environments | Env variables | REGISTRY/PROJECT only; matches ECR project |
| 4 | `AWS_REGION` (optional) | Repo variable | Set only if not `us-east-1` |
| 5 | `CHART_REPO` / `CHART_BRANCH` / `CHART_PROD_BRANCH` (optional) | Repo variables | Set only if remotes/branch differ |
| 6 | `CHART_REPO_TOKEN` | Repo secret | Required for automated dev push + prod PR |

#### 4.6 How workflows resolve values

```text
prepare → target_environment = development | production
preflight / build / verify-ecr:
  environment: ${{ target_environment }}
  vars.AWS_ROLE_ARN, vars.IMAGE_NAME   # from that Environment
  vars.AWS_REGION || 'us-east-1'       # repository (or default)
update-chart-dev (development only):
  secrets.CHART_REPO_TOKEN             # repository secret
  vars.CHART_REPO || 'tf2-team/tf2-corp-chart'
  vars.CHART_BRANCH || 'techx-dev-corp'
create-chart-prod-pr (production only):
  secrets.CHART_REPO_TOKEN             # same secret; needs Pull requests write
  vars.CHART_REPO || 'tf2-team/tf2-corp-chart'
  vars.CHART_PROD_BRANCH || 'main'
```

If `AWS_ROLE_ARN` or `IMAGE_NAME` is missing on the selected environment, **preflight** fails fast with an explicit error pointing at this document.

### 5. Operator setup — chart promote token (dev push + prod PR)

Cross-repo Git writes cannot use the platform repo’s default `GITHUB_TOKEN`. Jobs **`update-chart-dev`** and **`create-chart-prod-pr`** authenticate to the **chart** repository with a PAT stored as a platform Actions secret (configured in **§4.4**).

#### How authentication works

| Concern | Identity |
|---|---|
| Platform workflow / AWS OIDC / ECR push | Platform `GITHUB_TOKEN` + environment role |
| Checkout + **push** / **open PR** on chart repo | Secret **`CHART_REPO_TOKEN`** (PAT) |
| Git commit author name/email | `github-actions[bot]` (cosmetic; set in the job) |

The Action does **not** “assume” GitHub’s built-in bot for write access to another repo. The **PAT owner** (or fine-grained token resource grants) is what GitHub authorizes for the push/PR. Prefer a **dedicated machine user** for the PAT if you do not want a personal account owning the token.

Production still requires a **human merge** of the chart PR (no auto-merge, no Argo API call from platform CI).

#### Prerequisites

| Item | Value / notes |
|---|---|
| Platform GitHub repo | the repo where `build-and-push.yml` runs |
| Chart GitHub repo | default `tf2-team/tf2-corp-chart` (override with repo variable `CHART_REPO`) |
| Chart branch for dev | default `techx-dev-corp` (Argo CD Application `techx-corp-dev` `targetRevision`) |
| Chart base branch for prod PRs | default `main` (Argo CD Application `techx-corp` `targetRevision`) |
| Operator rights | Admin (or secrets:write) on platform repo; ability to create PATs; ability to configure chart branch rules |

#### Step A — Create a fine-grained PAT (recommended)

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Token name:** e.g. `techx-platform-chart-promote`.
3. **Expiration:** set a finite expiry (e.g. 90 days) and calendar a rotation.
4. **Resource owner:** org or user that owns the chart repo.
5. **Repository access:** **Only select repositories** → select the chart repo only  
   (default `tf2-team/tf2-corp-chart`, or your fork / remote name).
6. **Permissions → Repository permissions:**
   - **Contents:** **Read and write** (required for checkout + push of values files / promote branches)
   - **Pull requests:** **Read and write** (required for **create-chart-prod-pr**)
   - **Metadata:** Read-only (usually granted automatically)
   - Do **not** grant admin, workflows, or secrets permissions.
7. Generate the token and **copy it once** (GitHub will not show it again).

Classic PAT alternative (less preferred): `repo` scope on an account with write access to the chart repo. Still store it only as `CHART_REPO_TOKEN`.

#### Step B — Add the secret on the **platform** repository

Follow **§4.4** (name **`CHART_REPO_TOKEN`**, value = PAT from Step A).  
Optional chart remote/branch overrides: **§4.3** (`CHART_REPO`, `CHART_BRANCH`, `CHART_PROD_BRANCH`; workflow defaults are usually enough).

Do **not** commit the PAT to Git, put it in Environment variables (non-secret), or paste it into workflow logs.

#### Step C — Allow the PAT identity to push chart branch `techx-dev-corp` (dev) and create promote branches (prod)

On the **chart** repo:

1. Confirm the PAT’s user (or machine user) has **write** access to the chart repository.
2. Review **Settings → Branches / Rulesets** for `techx-dev-corp` (dev direct-push):
   - If **Require a pull request before merging** (or similar) blocks direct pushes, either:
     - add a **bypass** for the PAT’s user / team / app, or
     - temporarily allow force-free direct pushes for that identity only.
   - Status checks required on PR are fine for humans; they must not block the bot’s direct push path if you rely on automation.
3. For production, the bot pushes feature branches `promote/prod-image-<tag>` (not `main`). Ensure branch rules allow the PAT to **create and push** those branches and **open PRs** into `main`.
4. Do **not** require signed commits for that identity unless the PAT workflow is also configured to sign (not implemented today).

#### Step D — Verify end-to-end

**Development**

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

**Production**

1. Run a production publish only after development is validated:
   - push `src/**` to platform `main`, or tag `v*`, or dispatch **`production`**.
2. Confirm job order ends with **Create chart values-prod PR** (green).
3. Open the linked chart PR; confirm `values-prod.yaml` has `default.image.tag: "<version>"`.
4. Review and merge the PR when ready to deploy.
5. Optional: `argocd app wait techx-corp --sync --health --timeout 600`.

#### Failure modes (setup-related)

| Symptom | Fix |
|---|---|
| `Secret CHART_REPO_TOKEN is not set` | Complete §4.4 / Step B on the **platform** repo |
| `Repository not found` / checkout 404 | Wrong `CHART_REPO`, or PAT lacks access to that repo |
| `Permission denied` / push rejected | PAT Contents not Read/write; or branch rules block the PAT identity (Step C) |
| `GraphQL: Resource not accessible` / PR create fails | Grant fine-grained PAT **Pull requests: Read and write** |
| Job skipped entirely | Wrong environment for that job, or `release-ready` failed. If **both** chart jobs skip after a green `release-ready` on a selective run, the job `if` must include `always()` so a skipped empty build/retag matrix does not cascade-skip promote (fixed in workflow). |

Without `CHART_REPO_TOKEN`, builds can still push images and pass `release-ready`, but chart promote jobs fail until the secret is set. Operators can still edit chart values manually as a fallback.

#### Security and rotation

* Scope the PAT to the **chart repo only**; Contents + Pull requests read/write is enough.
* Prefer a **machine user** over a personal account for ownership and offboarding.
* Rotate on expiry or if the secret is exposed: create a new PAT → update `CHART_REPO_TOKEN` → revoke the old PAT.
* Revoking the PAT immediately stops automated chart promotes (images still publish).

### 6. First dry run

1. Merge workflow / bake changes to the development branch.
2. Dry-run development: push to `techx-dev-corp`, or Actions → **Build and push images** → `development`.
3. Confirm all 23 runtime tags, for example:

   ```bash
   aws ecr describe-images --repository-name techx-dev-corp/ad \
     --image-ids imageTag=sha-<7char> --region us-east-1
   # no :buildcache tag required — layer cache lives in GitHub Actions
   ```

4. Confirm the workflow summary shows **Release ready**, then **Chart values-dev update** with the new tag.
5. Confirm chart `values-dev.yaml` on `techx-dev-corp` has `default.image.tag: "sha-<7char>"`.
6. Production: merge/push `main` (or tag `v*` / protected dispatch) only after development passes → ECR production project; confirm job **Create chart values-prod PR** opens a chart PR for `values-prod.yaml`, then merge that PR to deploy.

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
export IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-prod-corp
export IMAGE_VERSION=sha-manual
export DEMO_VERSION=sha-manual

# Release group only (23 services). Clear GHA cache outside Actions.
docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push \
  --set "*.cache-from=" --set "*.cache-to="
# Produces: .../techx-prod-corp/ad:sha-manual (runtime tag only)
```

Makefile (after setting `.env.override`):

```bash
make create-multiplatform-builder
make build-multiplatform-and-push   # invokes bake group "release"; clears GHA cache flags
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
| release-ready red | Treat as not promotable; chart promote jobs are skipped. |
| update-chart-dev / create-chart-prod-pr skipped after green release-ready | Empty build or retag side is **skipped** by design; promote jobs use `always()` plus `needs.release-ready.result == 'success'` so they still run. Re-run on a commit that includes that `if` fix if an older workflow skipped them. |
| update-chart-dev / create-chart-prod-pr fails: missing `CHART_REPO_TOKEN` | Add the secret (see §4.4 / §5); re-run failed job or full workflow. |
| update-chart-dev fails: push rejected / protected branch | Allow the PAT identity to push to `techx-dev-corp`, or temporarily open a manual values commit. |
| create-chart-prod-pr fails: cannot create PR | Ensure PAT has **Pull requests: Read and write**; confirm `CHART_PROD_BRANCH` exists. |
| create-chart-prod-pr / update-chart-dev fails: `Could not locate default.image.tag under default.image` | Chart overlay has `default.image.tag` but not the old rigid layout (sibling keys under `default:` before `image:`). Workflow regex must allow indented lines before `image:` / `tag:`; re-run after that fix is on the platform default branch. |

Rollback of this CI design: revert workflow, `docker-bake.hcl`, Makefile, and docs. Stale ECR `:buildcache` tags (if any) may remain or be deleted; they are not used by deploy or current CI.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` does not match environment name or repo |
| `denied: User is not authorized to perform ecr:PutImage` | Role policy missing repo ARN or wrong repository name |
| Bake OOM / disk full | Runner disk; workflow frees space — re-run or use larger runner |
| `The image tag 'buildcache' already exists … cannot be overwritten because the tag is immutable` | ECR is IMMUTABLE; CI must use GHA `type=gha` cache, not ECR `:buildcache`. Merge the GHA-cache bake change and re-run; optional: delete orphan `:buildcache` images in ECR |
| Images pushed to wrong registry | `IMAGE_NAME` missing or wrong on the GitHub Environment (see §4) |
| `GitHub Environment variable AWS_ROLE_ARN is not set` | Add `AWS_ROLE_ARN` on that Environment (§4.2) |
| `GitHub Environment variable IMAGE_NAME is not set` | Add `IMAGE_NAME` on that Environment (§4.2) |
| Compose missing Dockerfile path | `.env` not sourced before bake |
| Catalog mismatch in prepare | New Compose `build:` service not listed in bake group `release` |
| `Could not locate default.image.tag under default.image in values-prod.yaml` | Tag updater expected `default:` → `image:` with no intervening keys; prod overlay may set lifecycle keys first — fixed flexible regex in promote jobs |

## Image promotion → GitOps (REL-09)

Platform CI builds, pushes, and verifies images. Deploy is Argo CD reading the chart repo (Git desired state).

Because the chart uses a **global** `default.image.tag` for all nested services (including first-party `opensearch`):

1. **Rebuild and push the full release set** (23 services, including `mem0`, `opensearch`, and `shopping-copilot`) with the same tag.
2. **Wait for `release-ready`** (includes ECR `describe-images` for every service).
3. **Development:** job **update-chart-dev** direct-pushes `default.image.tag` in `values-dev.yaml` on chart branch `techx-dev-corp` (requires `CHART_REPO_TOKEN`).
4. **Production:** job **create-chart-prod-pr** opens a chart PR updating `values-prod.yaml` (`default.image.tag` only) against base `main` (requires `CHART_REPO_TOKEN` with Pull requests write). A human merges the PR.
5. Argo CD auto-syncs after the chart commit lands (dev Application `techx-corp-dev` after direct push; prod Application `techx-corp` after PR merge). Optional wait: `argocd app wait techx-corp-dev --sync --health --timeout 600` or `argocd app wait techx-corp --sync --health --timeout 600`.

Do **not** promote chart values while any matrix job or verification is incomplete.

```text
# Development
CI → prepare → preflight → build (all 23) → verify ECR → release-ready
  → update-chart-dev (direct push values-dev.yaml) → Argo auto-sync

# Production
CI → prepare → preflight → build (all 23) → verify ECR → release-ready
  → create-chart-prod-pr (open values-prod.yaml PR) → human merge → Argo sync
```

See chart runbook: `techx-corp-chart/docs/operations/gitops-argocd.md`.

## Security notes

- Actions pinned to full commit SHAs (major-version patch pins) with version comments.
- Every external Dockerfile `FROM` is pinned to an immutable manifest digest; `scripts/check_pinned_base_images.py` blocks regressions in PR CI.
- Trivy image CVE and IaC misconfiguration scans block on `HIGH`/`CRITICAL`; Semgrep and TruffleHog are also blocking gates.
- Cosign signs each immutable image digest with AWS KMS. Both the CycloneDX SBOM and the provenance predicate are KMS-signed attestations.
- Provenance schema v1 records commit, merged PR, approving reviewer, signing key URI, workflow run, SBOM status, and every blocking scan result.
- Selective chart promotion writes only rebuilt services' `values-<service>.yaml`; a full rebuild is manual and requires a recorded reason.
- Weekly Dependabot updates for `github-actions` (`.github/dependabot.yml`).
- `id-token: write` only on preflight, build, and verify-ecr jobs.
- GitHub expressions passed into shell steps via quoted environment variables.
- OIDC authentication only; no long-lived AWS keys.
- Production chart path still requires human PR merge (no auto-merge from platform CI).

## Out of scope (v1)

- Auto-merge of production chart PRs (human review remains the prod deploy gate)
- Helm/kubectl deploy or Argo CD API calls from this repo
- Admission policy installation and enforcement (owned by `tf2-corp-chart` and `tf2-corp-infra`)
- GitHub branch-protection administration (required checks must be enabled by a repository administrator)
- Full e2e / tracetest in PR CI

## Mandate 10 cross-repository contract

The chart repository must consume the generated overlays and enforce the following keys:

- Normal service: `components.<service>.imageOverride.digest`
- Mem0: `mem0.image.digest`
- Load generator: the same digest is written for `load-generator` and `load-generator-worker`
- Flagd UI sidecar: `components.flagd.sidecarImageDigests.flagd-ui`

The flagd UI map is intentionally not a `sidecarContainers` array override: replacing
that array would discard the existing sidecar configuration and violate the mandate's
requirement not to disable or alter flagd. The chart schema and template must support
this map before the shared Mandate 10 branch is promoted.

Admission must require two independent facts for first-party ECR images: a valid KMS
signature and the custom provenance attestation type
`https://techx-corp.dev/attestations/provenance/v1`. The attestation policy must require
all `scans` values to equal `pass` and `sbom.attested` to equal `true`.

<!-- Change trail: @hungxqt - 2026-07-19 - Document shopping-copilot in 23-image release catalog and CI tests. -->
