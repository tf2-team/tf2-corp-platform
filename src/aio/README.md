# TF2 AIO4 AIOps Runtime

Modular-monolith AIOps service scaffold and evolving runtime described by `../../docs/aiops/instruction/raws/architect.md` and `../../docs/aiops/instruction/raws/implement_plan.md`.

## Folder Layout

```text
aiops/
├── api/              # FastAPI app and route handlers
├── collectors/       # production collector interfaces; fixtures stay under tests
├── qualification/    # gate.py
├── normalization/    # normalizer.py
├── features/         # builder.py
├── detectors/        # base.py, engine.py, threshold.py, no_data.py, dependency.py
├── correlation/      # correlator.py
├── enrichment/       # enricher.py
├── incidents/        # manager.py
├── notifications/    # builder.py
├── remediation/      # policy.py
├── verification/     # engine.py
├── storage/          # memory.py, sqlite.py
├── pipeline/         # runtime.py
├── schemas/          # shared Pydantic request/domain/response models
├── shared/           # reusable helpers
└── models.py         # compatibility exports for older imports
```

`__init__.py` files only re-export public classes. Pipeline logic stays in named modules.
Add new Pydantic classes under `aiops/schemas/`, not beside the business logic.

## Shared Code

- `aiops.shared.features.index_features`: build a `signal_id -> Feature` map.
- `aiops.shared.features.find_feature`: lookup one feature by `signal_id`.

These are reused by detectors, enrichment, and verification. Other code is still small and module-specific, so it stays local until real duplication appears.

## Run Tests

Create the locked Conda environment:

```bash
conda env create --file environment.yml
conda run -n capstone python -m pip install --no-deps -e .
conda run -n capstone python -m pytest
```

Or use an existing Python 3.11-3.13 environment from the repository root:

```bash
make aiops-install
make aiops-check
```

The committed `uv.lock`, `requirements.lock`, and `requirements-dev.lock` are generated dependency locks. Regenerate them only after reviewing dependency changes.

## Developer and CI commands

```text
make aiops-format-check
make aiops-lint
make aiops-typecheck
make aiops-config-check
make aiops-unit
make aiops-contract
make aiops-integration
make aiops-replay SCENARIO=normal
make aiops-eval
make aiops-artifact-check
make aiops-image
make aiops-check
```

## Configuration

The prototype runtime still loads process settings from `.env` through `aiops.config.Settings`. The production-owned, disabled configuration scaffold lives under `config/` and is checked with `make aiops-config-check`. It contains no enabled signal, query, detector, topology, route, endpoint, or credential until live TF2 evidence and signed ADRs exist.

- Hyperparameters: thresholds, confidence, default replicas.
- Runtime paths: API paths, evidence dir, state store path.
- Operational IDs: detector IDs, signal IDs, runbook IDs, severity, environment.
- Safety policy values: protected targets, stateful kinds, non-actionable flows.
- Integration credentials: Prometheus, Grafana webhook, Jaeger, OpenSearch, Kubernetes API, notification webhook, AIE status, CDO cost feed, live executor.

List/set values use JSON array syntax in `.env`:

```env
AIOPS_NO_DATA_REQUIRED_SIGNAL_IDS=["checkout_bad_ratio_24h"]
AIOPS_PROTECTED_TARGETS=["flagd","openfeature","secrets","btc-incident"]
```

## Current Scope

The service/package scaffold is present, including the locked dependency set, digest-pinned non-root container, executable API entry point, production configuration boundary, support scripts, canonical P0 runbooks, tests, Make targets, and CI job.

The business runtime is still a prototype: it has synchronous `run_once` behavior, basic FastAPI routes, SQLite incident persistence, and thin HTTP clients. Continuous scheduling, complete schema-validated configuration loading, real adapter wiring, durable lifecycle/outbox/audit, P0 detector coverage, self-observability, Grafana assets, and EKS deployment remain separate P0 tasks. Disabled configuration files must not be enabled using guessed values.

## Run locally

The local `.env` contains non-production values for tests and must never be copied into an image or deployment.

```bash
conda run -n capstone aiops-api
```

The liveness endpoint is `GET /health/live`. Other production API and scheduler behaviors remain subject to their P0 implementation tasks.

## Build the image

```bash
make aiops-image
docker run --rm --env-file src/aio/.env -p 8080:8080 tf2-aiops:local
```

The local `.env` argument is only for workstation validation. The image contains no settings or secrets and intentionally fails fast when required configuration is absent. The image uses an immutable Python base digest, installs the hash-locked runtime dependency set, runs as UID/GID 10001, and excludes `.env`, tests, fixtures, planning docs, and generated state/evidence. Kubernetes must provide configuration and Secrets at deployment time.

## Integrations

Direct outbound clients live under `aiops/integrations/`:

- `PrometheusClient`
- `JaegerClient`
- `OpenSearchClient`
- `KubernetesClient` for read-only status
- `NotificationClient`
- `AieClient`
- `CostClient`
- `LiveExecutorClient` for the optional separate executor

Grafana is inbound at `POST /api/v1/events/grafana`.

Blocked by design: Kubernetes Secrets, database mutation, flagd/OpenFeature mutation, and direct Kubernetes mutation from the normal runtime.

## Dependency boundaries

The codebase uses Pydantic v2 models for all domain contracts. Python 3.12 is used in Conda, CI, and the production image.

FastAPI is used only in the API layer. Core pipeline code stays framework-free.

Runtime code must not import from `tests` or `tf2-corp-platform/docs/aiops`. `scripts/check_runtime_imports.py` enforces this boundary. Fake collectors and replay fixtures stay under `tests/` and are excluded from the production image.
