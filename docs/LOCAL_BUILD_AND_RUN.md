# Local Build and Run — techx-corp-platform

This guide explains how to **build images and run the TechX Corp platform stack on a developer machine** with Docker Compose. It covers the full demo, a lighter “minimal” profile, single-service rebuilds, protobuf generation, and common local tests.

For CI image publishing to ECR and cluster deploy, see [CICD.md](./CICD.md) and [DEPLOYMENT.md](./DEPLOYMENT.md). Helm/GitOps live in `techx-corp-chart`, not this repository.

---

## 1. What you get

Local Compose starts a polyglot online-store demo:

```text
Browser → frontend-proxy (Envoy :8080) → frontend (Next.js)
                                           │
                         gRPC/HTTP → product-catalog, cart, checkout,
                         currency, shipping, quote, payment, ad,
                         recommendation, product-reviews, email, …
                                           │
                         checkout / payment side-effects → Kafka → accounting, fraud-detection
                                           │
                         All services → OTLP → otel-collector → Prometheus / Jaeger / Grafana / OpenSearch
```

**Primary entry URL:** [http://localhost:8080/](http://localhost:8080/)

All storefront and admin UIs are exposed through `frontend-proxy` on port **8080** (see [§6 Local URLs](#6-local-urls)).

---

## 2. Prerequisites

| Tool | Notes |
|---|---|
| **Docker Engine** + **Docker Compose v2** | `docker compose version` must work. Docker Desktop on Windows/macOS is fine. |
| **Make** (recommended) | Targets wrap Compose with the correct `--env-file` flags. Without Make, use the `docker compose` equivalents below. |
| **Disk / RAM** | Full stack builds and runs many images (app + Kafka + Postgres + OpenSearch + observability). Allocate **≥ 8 GB RAM** to Docker; **16 GB** host memory is more comfortable. First build can take a long time and several GB of disk. |
| **Git** | Clone this repository; run all commands from the **repository root** (`techx-corp-platform/`). |

Optional (only for specific workflows):

| Tool | When needed |
|---|---|
| **Go / .NET / Node / Rust / …** | Only if you run unit tests or services **outside** Docker. Day-to-day local run does not require them. |
| **Docker Buildx** | Multi-arch bake (`make build-multiplatform*`) or manual ECR push. Not required for normal `make start`. |
| **AWS CLI + ECR login** | Only if you pull/push images to the private registry instead of building locally. |

### Shell notes (Windows)

- Prefer **Windows CMD** for the one-liners labeled `cmd` below (workspace convention).
- **Make** often runs under Git Bash / MSYS on Windows; Make recipes that source `.env.override` use sh syntax.
- If Make is unavailable, every common workflow has a plain `docker compose` form.

---

## 3. Environment files

Compose is always started with **two** env files (Make does this for you):

```text
--env-file .env --env-file .env.override
```

| File | Role |
|---|---|
| **`.env`** | Committed defaults: ports, Dockerfile paths, dependent image tags, `IMAGE_NAME`, `DEMO_VERSION=latest`, OTEL settings. |
| **`.env.override`** | Local overrides loaded **after** `.env` (wins on conflicts). Used for registry path, version tags, or optional real LLM settings. |
| **`.env.arm64`** | Auto-loaded by the Makefile on **macOS arm64** only (`_JAVA_OPTIONS` JVM workaround). |

### Image identity (local)

Images are named:

```text
${IMAGE_NAME}/<service>:${DEMO_VERSION}
```

Committed local defaults typically look like:

```text
IMAGE_NAME=<registry>/<project>    # e.g. …/techx-dev-corp
DEMO_VERSION=latest
```

You do **not** need AWS credentials to build and run from source. Compose builds from the Dockerfiles under `src/`.

If `.env.override` points `IMAGE_NAME` at a private ECR and you prefer pure local tags, override it:

```cmd
REM Example: keep builds local / anonymous registry path
echo IMAGE_NAME=techx-corp> .env.override
echo DEMO_VERSION=latest>> .env.override
```

### Amazon Bedrock / Nova for local AI development

Shopping Copilot, Product Reviews and Mem0 use Bedrock by default. Each developer supplies their own AWS profile; do not put an AWS key in `.env` or Git.

1. Log in with a profile that has `bedrock:InvokeModel` for Nova in `us-east-1`:

   ```powershell
   aws sso login --profile <your-profile>
   ```

2. Create/update your untracked `.env.override`:

   ```text
   AWS_PROFILE=<your-profile>
   AWS_CONFIG_DIR=C:/Users/<your-windows-user>/.aws
   AWS_REGION=us-east-1
   BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
   ```

3. Confirm the profile can invoke Nova before starting Compose:

   ```powershell
   aws bedrock-runtime converse --region us-east-1 --profile <your-profile> --model-id us.amazon.nova-2-lite-v1:0 --messages '[{"role":"user","content":[{"text":"Reply with OK"}]}]'
   ```

Compose mounts this credential directory read-only only into the three AI containers. If the profile is unavailable, those services return a controlled fallback instead of using Groq.

---

## 4. Quick start (full stack)

From the repository root:

```cmd
cd /d techx-corp-platform

make start
```

Equivalent without Make:

```cmd
cd /d techx-corp-platform
docker compose --env-file .env --env-file .env.override up --force-recreate --remove-orphans --detach
```

What this does:

1. Builds missing images (or uses existing local tags).
2. Starts the full Compose graph on network `techx-corp`.
3. Prints the main UI links.

Open the storefront: [http://localhost:8080/](http://localhost:8080/)

### Stop everything

```cmd
make stop
```

```cmd
docker compose --env-file .env --env-file .env.override down --remove-orphans --volumes
docker compose --env-file .env --env-file .env.override -f docker-compose-tests.yml down --remove-orphans --volumes
```

`make stop` also tears down the test Compose project and **removes named volumes** (Postgres, Kafka, Valkey data). Expect a clean data plane on the next start.

---

## 5. Minimal stack

For a lighter local footprint (fewer async/backend pieces):

```cmd
make start-minimal
```

```cmd
docker compose --env-file .env --env-file .env.override -f docker-compose.minimal.yml up --force-recreate --remove-orphans --detach
```

`docker-compose.minimal.yml` still serves the storefront and core commerce path plus observability, but omits some full-stack services (for example **accounting**, **fraud-detection**, **kafka**, **postgresql**, **flagd-ui**). Prefer full `make start` when exercising checkout side-effects, Kafka consumers, or feature-flag UI.

Stop with `make stop` (same as full stack).

---

## 6. Local URLs

| Surface | URL |
|---|---|
| Storefront | http://localhost:8080/ |
| Jaeger UI | http://localhost:8080/jaeger/ui |
| Grafana | http://localhost:8080/grafana/ |
| Load generator (Locust) | http://localhost:8080/loadgen/ |
| Feature flags UI (flagd-ui) | http://localhost:8080/feature/ |
| Product images | http://localhost:8080/images/ |
| Flagd API (via proxy) | http://localhost:8080/flagservice/ |
| OTLP HTTP (via proxy) | http://localhost:8080/otlp-http/ |

Most service ports in `.env` are also published for direct debugging (cart, checkout, …). Day-to-day traffic should go through **port 8080** (`frontend-proxy`).

Envoy admin is mapped to host port **10000** (`ENVOY_ADMIN_PORT`) when the full proxy service is up.

---

## 7. Build images

### Build all Compose services

```cmd
make build
```

```cmd
docker compose --env-file .env --env-file .env.override build
```

### Build and restart one service after code changes

Rebuild image + recreate container (recommended during service work):

```cmd
make redeploy service=frontend
```

```cmd
docker compose --env-file .env --env-file .env.override build frontend
docker compose --env-file .env --env-file .env.override stop frontend
docker compose --env-file .env --env-file .env.override rm --force frontend
docker compose --env-file .env --env-file .env.override create frontend
docker compose --env-file .env --env-file .env.override start frontend
```

### Restart one service without rebuild

```cmd
make restart service=checkout
```

### Useful Compose helpers

```cmd
REM Status
docker compose --env-file .env --env-file .env.override ps

REM Logs (follow one service)
docker compose --env-file .env --env-file .env.override logs -f checkout

REM Logs (all)
docker compose --env-file .env --env-file .env.override logs -f
```

### Clean local TechX images

```cmd
make stop
make clean-images
```

Only works when containers that reference those images are stopped. Filters images matching `*/techx-corp/*` and `*/techx-dev-corp/*`.

---

## 8. Frontend hot-reload (development)

Production-style containers bake the Next.js app. For iterative frontend work:

```cmd
cd /d techx-corp-platform
docker compose --env-file .env --env-file .env.override run --service-ports -e NODE_ENV=development ^
  --volume "%CD%/src/frontend:/app" --volume "%CD%/pb:/app/pb" ^
  --user node --entrypoint sh frontend
```

```sh
# sh/bash (Git Bash, WSL, macOS/Linux)
docker compose --env-file .env --env-file .env.override run --service-ports -e NODE_ENV=development \
  --volume "$(pwd)/src/frontend:/app" --volume "$(pwd)/pb:/app/pb" \
  --user node --entrypoint sh frontend
```

Inside the container:

```sh
npm run dev
```

Then open http://localhost:8080/ (ensure dependent backend services are already up via `make start` or that Compose starts them as dependencies of `run`).

See also `src/frontend/README.md`.

---

## 9. Protobuf generation

API contracts live in `pb/demo.proto`. Generated stubs are checked into service trees. After editing the proto:

```cmd
REM Preferred: generate via Docker (no local protoc toolchain required)
make docker-generate-protobuf

REM Alternative host-side script (requires local tooling)
make generate-protobuf
```

```cmd
REM Without Make
docker-gen-proto.sh
```

On Windows without a POSIX shell, run the script from **Git Bash** or **WSL**.

Verify the worktree is clean after generation (CI-style check):

```cmd
make check-clean-work-tree
```

---

## 10. Tests

### Unit tests (host, CI-aligned)

These match what PR CI runs for covered services:

```cmd
cd /d techx-corp-platform\src\checkout
go test ./...

cd /d techx-corp-platform\src\product-catalog
go test ./...

cd /d techx-corp-platform\src\cart
dotnet test --configuration Release --verbosity minimal
```

Other languages (examples):

```cmd
cd /d techx-corp-platform\src\shipping
cargo test
```

### Docker-based frontend Cypress + Tracetest

Requires the stack (or test Compose dependencies) available:

```cmd
make run-tests
```

Tracetest only (optional service filter):

```cmd
make run-tracetesting
make run-tracetesting SERVICES_TO_TEST=checkout
```

```cmd
docker compose --env-file .env --env-file .env.override -f docker-compose-tests.yml run frontendTests
docker compose --env-file .env --env-file .env.override -f docker-compose-tests.yml run traceBasedTests
```

---

## 11. Multi-platform bake (optional)

Normal local run uses single-platform Compose builds. Multi-arch release bake is what CI uses for ECR.

```cmd
make create-multiplatform-builder
```

```cmd
REM Make recipe sources .env.override then bakes group "release" (23 images) and pushes
make build-multiplatform-and-push
```

Manual equivalent (sh-style env load — Git Bash / WSL / Linux):

```sh
set -a; . ./.env.override; set +a
docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push
```

Requirements: Buildx builder with multi-platform support, registry credentials for `IMAGE_NAME`, and a correctly set `.env.override`. **Do not** treat this as the everyday local loop; see [CICD.md](./CICD.md).

Load multi-platform images into the local Docker engine (advanced):

```cmd
make build-multiplatform
```

---

## 12. Service catalog (full Compose)

Application / platform images built from this repo (also the CI `release` set of 23 when using bake):

| Area | Services |
|---|---|
| Commerce | `frontend`, `frontend-proxy`, `image-provider`, `product-catalog`, `cart`, `checkout`, `payment`, `shipping`, `quote`, `currency`, `email`, `ad`, `recommendation`, `product-reviews` |
| Async / AI | `kafka`, `accounting`, `fraud-detection`, `llm`, `mem0`, `shopping-copilot` |
| Feature flags | `flagd`, `flagd-ui` |
| Load | `load-generator` |
| Data | `postgresql`, `valkey-cart` |
| Observability | `otel-collector`, `jaeger`, `grafana`, `prometheus`, `opensearch` |

Release bake catalog details: [CICD.md § Release catalog](./CICD.md#release-catalog-23-images).

---

## 13. Troubleshooting

| Symptom | What to try |
|---|---|
| Port **8080** already in use | Stop the other process, or change `ENVOY_PORT` / `FRONTEND_PORT` in `.env.override` (keep proxy and docs in sync mentally — browser URL follows `ENVOY_PORT`). |
| Containers exit / OOM | Increase Docker Desktop memory; use `make start-minimal`; check `docker compose … logs <service>`. |
| Stale code after edit | `make redeploy service=<name>` (rebuild), not only `restart`. |
| Java services fail on Apple Silicon | Ensure Makefile path is used (loads `.env.arm64`) or set `_JAVA_OPTIONS=-XX:UseSVE=0`. |
| Pull failures for `IMAGE_NAME` on ECR | Build locally instead of pull: `docker compose … build` / `make build`. Or `aws ecr get-login-password` + `docker login` if you intend to pull. |
| “Working tree is not clean” after proto work | Re-run `make docker-generate-protobuf` and commit generated stubs. |
| Postgres / Kafka weird state | `make stop` (removes volumes) then `make start`. |
| Windows Make / script errors | Use Git Bash for Make/`*.sh`, or the pure `docker compose` commands in this doc. |

### Health check snapshot

```cmd
docker compose --env-file .env --env-file .env.override ps
curl -s -o NUL -w "%%{http_code}" http://localhost:8080/
```

```sh
# sh/bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
```

Expect storefront HTTP **200** once the proxy and frontend are healthy (first boot may take several minutes while images build).

---

## 14. Related documentation

| Doc | Scope |
|---|---|
| [README.md](../README.md) | Repository overview |
| [CICD.md](./CICD.md) | GitHub Actions, ECR tags, dev chart promote |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | End-to-end EKS / Helm production runbook |
| `src/<service>/README.md` | Per-service notes |
| Workspace `docs/gitops-argocd.md` | GitOps after images exist |

---

## 15. Makefile target cheat sheet

| Target | Purpose |
|---|---|
| `make start` | Full stack up (detached, force-recreate) |
| `make start-minimal` | Minimal compose file up |
| `make stop` | Down full + test stacks, remove volumes |
| `make build` | Build all Compose images |
| `make restart service=…` | Recreate one service (no rebuild) |
| `make redeploy service=…` | Rebuild + recreate one service |
| `make docker-generate-protobuf` | Regenerate stubs via Docker |
| `make run-tests` | Cypress + Tracetest via Compose |
| `make run-tracetesting` | Tracetest only |
| `make create-multiplatform-builder` | Create Buildx builder `techx-corp-builder` |
| `make build-multiplatform-and-push` | Bake `release` group and push |
| `make clean-images` | Remove local TechX-tagged images |
| `make check` | Docs/tooling checks (misspell, markdownlint, license, links) |

<!-- Change trail: @hungxqt - 2026-07-19 - Document shopping-copilot in release catalog (23 images). -->
