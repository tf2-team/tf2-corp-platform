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

## Live Smoke Test Through EKS Port-Forward

The canonical endpoint and credential inventory is in
[`docs/live_endpoints.md`](docs/live_endpoints.md). From `src/aio`, keep the
port-forward helper running in one terminal:

```powershell
Copy-Item .env.live.example .env.live
powershell -File scripts/port_forward.ps1
```

To test the inbound Grafana webhook, start AIOps in a second terminal. Use
`AIOPS_ENV_FILE`; do not copy `.env.live` over the tracked `.env` template:

```powershell
$env:AIOPS_ENV_FILE = ".env.live"
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

The E2E runner reads allow-listed PromQL from `config/prometheus_e2e.json`,
collects real instant and range data through the Prometheus port-forward, and
runs the complete incident, RCA, and remediation pipeline locally. It refuses
to start unless `AIOPS_POLICY_MODE=dry-run`; it never constructs or calls the
live executor.

Keep `scripts/port_forward.ps1` running, then execute from `src/aio`. The
runner loads `.env.live` by default; `--env-file` can select another
operator-managed settings file:

```powershell
python -B scripts/run_prometheus_e2e.py
```

Each invocation uses isolated temporary SQLite/audit/RCA state and writes
`evidence/e2e/<run_id>.json`. The report contains the
capture time, Prometheus endpoint, query IDs and PromQL, converted observations,
range samples used by RCA, incidents, RCA candidates, policy/remediation
decisions, and a pass/fail result for every acceptance criterion. Secrets and
authorization headers are not written.

Acceptance requires a fresh occurrence-count-one incident from verified real
metrics and a visible notification; persistent incidents from older runs cannot
satisfy it. The command exits `0` only when all criteria pass. A healthy cluster can
legitimately produce a `failed` report because no incident was opened. For the
acceptance run, activate an approved existing failure scenario such as
`paymentFailure`, wait for the five-minute query window to contain failures,
run the command, and then turn the scenario off. The AIOps runner itself does
not activate faults or execute remediation.

For a labeled injection, pass `--scenario-id`, `--incident-started-at`, and
`--require-labeled-scenario`; the evidence records detector fire time and lead
time. To change metric names for another cluster, edit the tracked collection plan;
keep each query aggregated to exactly one Prometheus series. Observation signal
IDs, query IDs, units, windows, and required labels are validated against
`config/runtime.json` before any query runs.

## Configuration

Runtime secrets, URLs, and paths are loaded through `aiops.config.Settings`.
Set `AIOPS_ENV_FILE=.env.live` to select the ignored live file without copying
secrets into the tracked template.
Set `AIOPS_ENV_FILE=disabled` in CI or isolated tests to prevent any dotenv file
from being read; required settings must then be supplied through process environment variables.
Infrastructure topology, PromQL templates, selected services/metrics, signal
IDs, detector definitions, impact metadata, and policy lists are loaded from
`config/runtime.json`.
Detector thresholds/confidences, anomaly scale floors, RCA, remediation,
no-data, and correlation parameters are loaded from `config/hyperparameters.json`.

- Hyperparameters: detector thresholds, anomaly, RCA, remediation, no-data, correlation.
- Runtime paths: API paths, evidence dir, state store path.
- Operational IDs: detector IDs, signal IDs, runbook IDs, severity, environment.
- Safety policy values: protected targets, stateful kinds, non-actionable flows.
- Integration credentials: Prometheus, Grafana webhook, Jaeger, OpenSearch, Kubernetes API, notification webhook, AIE status, CDO cost feed, live executor.

List/set/map values use JSON syntax in `.env`:

```env
AIOPS_NO_DATA_REQUIRED_SIGNAL_IDS=["checkout_bad_ratio_24h"]
AIOPS_PROTECTED_TARGETS=["flagd","openfeature","secrets","btc-incident"]
```

## Current Scope

This baseline includes FastAPI routes, SQLite incident persistence, config-driven detectors, HTTP integration clients, and the v0.0.1 anomaly/RCA path:

- univariate EWMA plus seasonal residual scoring
- per-service multivariate isolation-style scoring
- graph traversal RCA plus repo-native robust score ranking
- confirmed adaptive findings converted into normal incident, notification, and runbook events
- two-sample confirmation before an adaptive incident is opened
- confirmed SLO/dependency breaches seed RCA when current range data is stable, without being relabeled as adaptive incidents
- persisted recovery and clean incident reopening on recurrence

It still does not perform Kubernetes mutation directly.

Prometheus queries preserve missing/no-traffic results as missing instead of
coercing absent series to zero. Error ratios synthesize a zero numerator only
when a real non-zero request denominator exists.

The bounded configured scope performs 21 instant and 16 range queries per
autonomous cycle (37 Prometheus requests total), covering checkout, payment,
cart, and product-catalog. Same-impact checkout SLO/burn fires are correlated
into one incident and notification with all contributing signals retained.

## Autonomous Container Runtime

The FastAPI lifespan starts periodic live collection when
`AIOPS_AUTO_RUN_ENABLED=true`; its interval is configured through
`AIOPS_AUTO_RUN_INTERVAL_SECONDS`. The container entry point requires
`AIOPS_API_BIND_HOST` and `AIOPS_API_BIND_PORT` at runtime, so it embeds no
operational endpoint or fixed listening port:

```powershell
docker build -t aio4-aiops:local .
docker run --rm --env-file path/to/operator-managed-settings aio4-aiops:local
```

The image excludes `.env*`, local state, and evidence. Helm/EKS wiring remains
gated on the real CDO-owned chart revision and owner; this repository does not
guess those deployment facts.

## Labeled Mandate 7b Evaluation

`evaluate/e2e_pipeline.py` requires explicit reviewer labels and reports
TP/FP/TN/FN, precision, recall, lead time, and RCA top-K. It rejects missing
case labels and marks evidence invalid when incident/normal coverage or timing
labels are absent. See `evaluate/README.md` and `evaluate/labels.example.json`.

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
