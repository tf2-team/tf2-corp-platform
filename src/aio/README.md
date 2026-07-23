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
├── anomaly/          # v0.0.1 EWMA/STL and service isolation score
├── rca/              # v0.0.1 graph traversal and repo-native robust score ranking
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

## Deployment Scaffold

The runtime now has a production container definition and pinned direct
dependencies in `Dockerfile` and `requirements.lock`. The image runs as UID
10001, exposes port 8000, stores SQLite and audit state under `/app/state`, and
provides these operational endpoints:

- `/health/live` for process liveness
- `/health/ready` for runtime configuration and writable-state readiness
- `/metrics` for Prometheus pipeline counters, duration, and last-run gauges

Both platform Compose files define an internal `aiops` service with a durable
named volume and Prometheus connectivity. The Helm chart provides an opt-in
single-replica workload, internal Service, persistent volume, read-only
Kubernetes RBAC, probes, and Prometheus scrape annotations. Enable it with
`tf2-corp-chart/values-aiops.yaml` only after publishing the image. Keep
`policyMode: dry-run` until live remediation has separate approval.

For Kubernetes, the ESO-managed `techx-corp-aiops-grafana-webhook` Secret is
referenced by `aiops.existingSecret`; do not put credentials in chart values.
The in-cluster endpoint is `http://aiops-runtime:8080`, backed by the FastAPI
container on port 8000. The pod uses its service-account token and cluster CA
for read-only Kubernetes enrichment. Grafana keeps the existing on-call route
and also sends warning, critical, SEV1, and SEV2 events to the authenticated
AIOps contact point. Compose provisions the equivalent local dual route.

## Live Smoke Test Through EKS Port-Forward

The canonical endpoint and credential inventory is in
[`docs/live_endpoints.md`](docs/live_endpoints.md). From `src/aio`, keep the
port-forward helper running in one terminal:

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
powershell -File scripts/port_forward.ps1
```

Fill the ignored `.env` with the required local integration values. To test the
inbound Grafana webhook, start AIOps in a second terminal:

```powershell
python -m uvicorn aiops.api.app:create_app --factory --port 8000
```

Run all strict connectivity checks, or one integration group, in a third
terminal:

```powershell
python -B tests/smoke_test_live.py
python -B tests/smoke_test_live.py TestPrometheus
```

Missing credentials, authentication errors, non-2xx responses, and unreachable
endpoints fail the suite; they are not reported as successful skips.

## Prometheus E2E Acceptance Run Through Port-Forward

Query templates, metric choices, no-data semantics, and the one-second collection
contract are documented in [`docs/prometheus-query-design.md`](docs/prometheus-query-design.md).

The E2E runner reads allow-listed query IDs from `config/prometheus_e2e.json`
and resolves their PromQL from `config/prometheus_queries.json`,
collects real instant and range data through the Prometheus port-forward, and
runs the complete incident, RCA, and remediation pipeline locally. It refuses
to start unless `AIOPS_POLICY_MODE=dry-run`; it never constructs or calls the
live executor.

Keep `scripts/port_forward.ps1` running, then execute from `src/aio`:

```powershell
python -B scripts/run_prometheus_e2e.py
```

Each invocation writes `evidence/e2e/<run_id>.json`. The report contains the
capture time, Prometheus endpoint, query IDs and PromQL, converted observations,
range samples used by RCA, incidents, RCA candidates, policy/remediation
decisions, and a pass/fail result for every acceptance criterion. Secrets and
authorization headers are not written.

The command exits `0` only when all four criteria pass. A healthy cluster can
legitimately produce a `failed` report because no incident was opened. For the
acceptance run, activate an approved existing failure scenario such as
`paymentFailure`, wait for the five-minute query window to contain failures,
run the command, and then turn the scenario off. The AIOps runner itself does
not activate faults or execute remediation.

To change metric names for another cluster, edit the canonical query registry;
keep each query aggregated to exactly one Prometheus series. Observation signal
IDs, query IDs, units, windows, and required labels are validated against
`config/runtime.json` before any query runs.

## Configuration

Runtime secrets, URLs, paths, and operational switches are loaded from
`AIOPS_*` environment variables through `aiops.config.Settings`. Numeric
pipeline tuning lives in `config/hyperparameters.json`; select another file
with `AIOPS_HYPERPARAMETERS_PATH` instead of putting tuning values in `.env`.
Local runtime and integration values use the single ignored `.env` file; copy
`.env.example` only when creating it for the first time.
Infrastructure topology, signal IDs, detector definitions, and policy lists are loaded from `config/runtime.json`.
Topology dependencies are directed RCA-impact edges (`service -> dependency`). The runtime builds one shared NetworkX
`DiGraph` for personalized PageRank, bounded dependency paths, correlation distance, and reverse caller blast radius.
Operator-only proxy routes and telemetry fan-out do not belong in this business-dependency graph.
Detector thresholds and detector confidences are intentionally kept in `config/runtime.json` beside detector IDs.
RCA, remediation, no-data, and correlation hyperparameters are loaded from `config/hyperparameters.json`.

- Hyperparameters: incident cooldowns, correlation, detector thresholds, no-data confidence, remediation, RCA.
- Runtime paths: API paths, evidence dir, state store path.
- Operational IDs: detector IDs, signal IDs, runbook IDs, severity, environment.
- Safety policy values: protected targets, stateful kinds, non-actionable flows.
- Integration credentials: Prometheus, Grafana webhook, Jaeger, OpenSearch, Kubernetes API, notification webhook, AIE status, CDO cost feed, live executor.

Detector IDs, required signal lists, protected targets, stateful kinds, and non-actionable flows are runtime config, not env overrides.

## Current Scope

This baseline includes FastAPI routes, SQLite incident persistence, config-driven detectors, HTTP integration clients, and the v0.0.1 anomaly/RCA path:

- univariate EWMA plus seasonal residual scoring
- per-service multivariate isolation-style scoring
- NetworkX personalized-PageRank traversal plus repo-native timestamp, drift, correlation, and robust-score ranking

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
