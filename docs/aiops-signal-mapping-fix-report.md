# AIOps Prometheus Signal Mapping Fix Report

## Context

Branch used as the source for this fix:

```text
origin/feat/aio/aiops-prometheus-query-registry
```

The current `main` branch does not contain the full AIOps runtime/query registry implementation. The mapping fix therefore targets the AIOps feature branch/codebase that contains:

```text
src/aio/config/prometheus_queries.json
src/aio/config/runtime.json
src/aio/aiops/...
```

## Problem

Recent AIOps alerts showed false or misleading monitoring-loss / zero-vector signals for metrics such as:

```text
*_cpu_millicores
*_socket_io_bytes_per_second
postgresql_active_connections
kafka_consumer_lag
shopping_copilot_* signals
```

The issue was mainly query/mapping mismatch, not necessarily missing telemetry in Prometheus.

Examples:

- CPU/network queries used weak or broad pod matching, causing wrong or empty series.
- Network I/O unit was inconsistent with the metric name.
- PostgreSQL query used `postgresql_backends`, but live Prometheus exposed `db_client_connection_count`.
- Kafka query used `kafka_consumer_group_lag`, but live Prometheus exposed `kafka_consumer_records_lag`.
- `shopping-copilot` existed in the platform/catalog but was missing from AIOps RED/resource signal generation.
- `memory_usage_bytes` had unit `bytes_per_second`, although it is an instant bytes metric.

## Files To Send / Apply

Only these files are needed for the mapping fix:

```text
src/aio/config/prometheus_queries.json
src/aio/config/runtime.json
src/aio/config/hyperparameters.json
src/aio/tests/test_runtime_config.py
src/aio/tests/test_prometheus_collector.py
```

The following later CI-only changes are not required if the goal is only signal mapping:

```text
.licenserc.json
src/aio/scripts/port_forward.sh
src/aio/aiops/anomaly/v001.py
scripts/release_services.json
scripts/check_release_catalog.py
scripts/update_chart_service_digests.py
```

## Mapping Changes

### 1. CPU Millicores

Updated `resource.cpu_millicores` to prefer Kubernetes cAdvisor/container metrics scoped by:

```text
namespace="techx-corp-prod"
pod=~"$service-[0-9a-f]{6,10}-.*"
container="$service"
```

This avoids broad or ambiguous matching and maps each service to its Deployment pod hash pattern.

Fallback branches were kept for compatibility with older metric names.

### 2. Network / Socket I/O

Updated `resource.socket_io_bytes_per_second` to use:

```text
container_network_receive_bytes_total
container_network_transmit_bytes_total
```

with namespace + pod hash matching.

Also corrected the unit from:

```text
bytes
```

to:

```text
bytes_per_second
```

### 3. Memory Unit

Corrected `resource.memory_usage_bytes` unit from:

```text
bytes_per_second
```

to:

```text
bytes
```

### 4. PostgreSQL Active Connections

Changed PostgreSQL active connection query to prefer:

```text
db_client_connection_count{db_client_connection_state="used"}
```

with fallback to:

```text
db_client_connection_count
postgresql_backends
```

Reason: live Prometheus had `db_client_connection_count`, while `postgresql_backends` returned no series.

### 5. Kafka Consumer Lag

Changed Kafka lag query to prefer:

```text
kafka_consumer_records_lag
```

with fallback to:

```text
kafka_consumer_group_lag
```

Reason: live Prometheus had `kafka_consumer_records_lag`, while `kafka_consumer_group_lag` returned no series.

### 6. Shopping Copilot Signals

Added `shopping-copilot` to:

- server spanmetrics RED group
- resource signal group
- runtime topology
- disabled auto error-rate detector
- hyperparameter threshold map

This allows AIOps to generate:

```text
shopping_copilot_request_rate_5m
shopping_copilot_error_rate_5m
shopping_copilot_p95_latency_5m
shopping_copilot_cpu_millicores
shopping_copilot_socket_io_bytes_per_second
...
```

## Validation Performed

Local JSON validation passed:

```bash
python3 -m json.tool src/aio/config/prometheus_queries.json
python3 -m json.tool src/aio/config/runtime.json
python3 -m json.tool src/aio/config/hyperparameters.json
```

Focused tests passed locally:

```bash
cd src/aio
uv run --isolated --with pytest --with . -m pytest \
  tests/test_runtime_config.py \
  tests/test_prometheus_collector.py \
  -q
```

Result:

```text
16 passed
```

Additional anomaly/runtime related tests were also run after the CI fixes:

```text
47 passed
```

Live Prometheus spot-checks confirmed the fixed queries returned series for representative services, including:

```text
cart
product-reviews
frontend
accounting
shopping-copilot
postgresql
kafka
```

## Expected Effect

After applying these files to the active AIOps codebase and redeploying AIOps runtime/config:

- CPU and socket I/O signals should no longer be zero/missing due to bad pod label matching.
- PostgreSQL and Kafka signals should query metric names that actually exist in Prometheus.
- `shopping-copilot` should have generated AIOps RED/resource signals.
- False `AIOPS_NORMAL_GROWTH_GATE zero_score` / `AIOPS_DETECT no_data_fire` alerts caused by mapping mismatch should reduce.

## Important Note

This report only covers Prometheus/AIOps signal mapping.

It does not claim to fix:

```text
checkout_p95_latency_5m
checkout SLO breach
application latency under Locust
resource sizing / autoscaling tuning
```

Those should be investigated separately after the mapping fix is deployed and Prometheus signals are confirmed healthy.
