# Self-heal CDO Phase 1 Validation

Date: 2026-07-28

Mục đích: ghi lại kết quả Phase 1 cho data/history handoff và golden action catalog.

## Artifact đã thêm/cập nhật

- Cập nhật `src/aio/config/actions.json`
  - Bổ sung `scale_product_catalog`
  - `action_type`: `scale_deployment`
  - `target`: `product-catalog`
  - `replicas`: `3`
  - `verification_defined`: `true`
  - `rollback_defined`: `true`
  - `approved`: `true`
- Thêm `src/aio/config/incidents_history.seed.json`
- Thêm `src/aio/scripts/generate_incident_history.py`
- Generate lại `src/aio/config/incidents_history.json`
- Thêm test file `src/aio/tests/test_generate_incident_history.py`

## Validation command

```bash
src/aio/.venv/bin/python src/aio/scripts/generate_incident_history.py \
  --seed src/aio/config/incidents_history.seed.json \
  --actions src/aio/config/actions.json \
  --check
```

Kết quả:

```text
records=7
valid_actions=7
scenarios:
  busy_with_oom: 1
  busy_with_pod_failure: 1
  fault_cpu_saturation: 1
  fault_database: 1
  fault_dependency: 1
  fault_latency: 1
  protected_unknown_service: 1
errors=0
```

## Generate command

```bash
src/aio/.venv/bin/python src/aio/scripts/generate_incident_history.py \
  --seed src/aio/config/incidents_history.seed.json \
  --actions src/aio/config/actions.json \
  --output src/aio/config/incidents_history.json
```

Kết quả:

```text
wrote=src/aio/config/incidents_history.json
```

## Runtime load check

```text
incident_history_store_load=pass records=7
```

`src/aio/config/incidents_history.json` load được bằng `IncidentHistoryStore.load()` và có action `scale_product_catalog`.

## Test note

- `python -m compileall` pass cho script/test mới.
- `pytest` chưa có trong `src/aio/.venv`, nên chưa chạy được bằng `src/aio/.venv/bin/python -m pytest`.
- Đã chạy trực tiếp generator logic bằng venv Python 3.11 để verify pass case và unknown-action reject case.

## Boundary

- `restart_*` vẫn chỉ là recommendation/dry-run/page trong P0.
- `scale_product_catalog` là golden action đầu tiên để Phase 2/3 triển khai script/executor.
- Không live mutate Kubernetes trong Phase 1.

