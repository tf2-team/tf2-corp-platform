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

**Job graph:** `CI → prepare → AWS/ECR preflight → 20-service matrix (max-parallel 4) → verify ECR → release-ready`

| Trigger | Environment | What |
|---|---|---|
| PR | — | lint + unit tests (`ci.yml`) |
| push `main` / tag `v*` | `production` | full publish → `…/techx-corp/<service>:<version>` |
| push branch `techx-dev-corp` | `development` | full publish → `…/techx-dev-corp/<service>:<version>` |
| docs-only branch push | — | publishing skipped (`docs/**`, `README.md`, `frontend-proxy-guide.md`) |
| manual dispatch | chosen | matching environment |

- **20 release images** defined in `docker-bake.hcl` (group `release`); `opensearch` is local-only.
- **Registry cache:** `${IMAGE_NAME}/<service>:buildcache` (not a deployable tag).
- **`release-ready`** is the sole gate for a **manual** chart values PR (no automated chart PR/deploy in v1).

Image format: `[REGISTRY]/[PROJECT]/[SERVICE]:[VERSION]`  
(e.g. `…/techx-dev-corp/ad:sha-a1b2c3d`).

Setup (IAM OIDC roles, GitHub Environment variables): **[docs/CICD.md](docs/CICD.md)**.  
End-to-end production runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Run locally
```sh
docker compose up --force-recreate --remove-orphans --detach
```
Storefront: http://localhost:8080/

## License
Distributed under the Apache License 2.0. See `LICENSE`.
