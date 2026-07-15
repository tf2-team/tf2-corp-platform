# AIOps Base Runtime

Minimal base code for the AIOps pipeline described in `docs/`.

## Folder Layout

```text
aiops/
├── api/              # FastAPI app and route handlers
├── collectors/       # base.py, static.py
├── qualification/    # gate.py
├── normalization/    # normalizer.py
├── features/         # builder.py
├── detectors/        # base.py, engine.py, threshold.py, no_data.py, dependency.py
├── anomaly/          # v0.0.1 EWMA/STL, service isolation score, BARO BOCPD
├── rca/              # v0.0.1 graph traversal and BARO robust scorer ranking
├── correlation/      # correlator.py
├── enrichment/       # enricher.py
├── incidents/        # manager.py
├── notifications/    # builder.py
├── remediation/      # policy.py
├── verification/     # engine.py
├── storage/          # sqlite.py
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

```sh
conda run -n capstone python -B -m unittest discover -s tests
```

## Configuration

Runtime secrets, URLs, and paths are loaded from `.env` through `aiops.config.Settings`.
Infrastructure topology, signal IDs, detector definitions, and policy lists are loaded from `config/runtime.json`.

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

This baseline includes FastAPI routes, SQLite incident persistence, config-driven detectors, HTTP integration clients, and the v0.0.1 anomaly/RCA path:

- univariate EWMA plus seasonal residual scoring
- per-service multivariate isolation-style scoring
- BARO `bocpd`
- graph traversal RCA plus BARO `robust_scorer`

It still does not perform Kubernetes mutation directly.

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

## Dependency

The codebase uses Pydantic v2 models for all domain contracts. The expected local runtime is the Conda env named `capstone`.

FastAPI is used only in the API layer. Core pipeline code stays framework-free.
