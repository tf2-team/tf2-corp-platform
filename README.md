# TechX Corp Platform

Internal microservice platform powering the TechX Corp online store: a polyglot,
Kubernetes-native system with a web storefront, product/cart/checkout/payment
services, an async messaging pipeline, an AI product-review summarizer, and a
full observability stack (metrics, logs, traces, dashboards).

## Layout
- `src/` - application microservices + AI review service + LLM
- `kubernetes/` - all-in-one manifest (`techx-corp-platform.yaml`)
- `docker-compose.yml` - local run
- `Makefile` - build / run helpers
- `.github/workflows/` - CI checks and ECR build/push

Kubernetes deploy: use the Helm chart in `../techx-corp-chart`.

## CI/CD
GitHub Actions builds multi-arch images and pushes them to AWS ECR via OIDC.

**Job graph:** `CI → prepare → AWS/ECR preflight → 23-service matrix → verify ECR → release-ready → update-chart-dev (dev) | create-chart-prod-pr (prod)`

| Trigger | Environment | What |
|---|---|---|
| PR | — | lint + unit tests (`ci.yml`) |
| push `main` with `src/**` changes / tag `v*` | `production` | full publish → ECR, then open chart PR for `values-prod.yaml` |
| push `techx-dev-corp` with `src/**` changes | `development` | full publish → ECR, then direct-push chart `values-dev.yaml` tag |
| branch push without `src/**` changes | — | publishing skipped (docs, workflows, compose/bake-only, etc.) |
| manual dispatch | chosen | matching environment (use for republish without `src/` edits) |

- **23 release images** defined in `docker-bake.hcl` (group `release`), including customized `opensearch` and `shopping-copilot`.
- **BuildKit cache:** GitHub Actions `type=gha` (not an ECR tag; safe with immutable ECR tags).
- **`release-ready`** gates promotion. **Dev** direct-pushes chart `default.image.tag`. **Prod** opens a chart PR for `values-prod.yaml` (human merge). Both need secret `CHART_REPO_TOKEN`.

Image format: `[REGISTRY]/[PROJECT]/[SERVICE]:[VERSION]`  
(e.g. `…/techx-dev-corp/ad:sha-a1b2c3d`).

Setup:

* IAM OIDC roles, GitHub Environment variables: **[docs/CICD.md](docs/CICD.md)**
* Chart promote (PAT / `CHART_REPO_TOKEN` / branch rules): **[docs/CICD.md §5 Operator setup](docs/CICD.md#5-operator-setup--chart-promote-token-dev-push--prod-pr)**
* End-to-end production runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**

## Run locally

Full local build/run guide (Make targets, env files, minimal stack, tests, troubleshooting):

**[docs/LOCAL_BUILD_AND_RUN.md](docs/LOCAL_BUILD_AND_RUN.md)**

```sh
# Preferred (loads .env + .env.override)
make start

# Or plain Compose
docker compose --env-file .env --env-file .env.override up --force-recreate --remove-orphans --detach
```
Storefront: http://localhost:8080/

## License
Distributed under the Apache License 2.0. See `LICENSE`.

<!-- Change trail: @hungxqt - 2026-07-19 - Document 23 release images including shopping-copilot. -->
