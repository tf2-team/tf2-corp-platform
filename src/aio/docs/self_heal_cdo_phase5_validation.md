# Self-heal CDO Phase 5 Validation

Date: 2026-07-28

Mục đích: ghi lại integration/smoke validation cho P0 self-heal handoff.

## Validation đã chạy

### Platform compile

```bash
src/aio/.venv/bin/python -m compileall -q \
  src/aio/scripts/generate_incident_history.py \
  src/aio/runbooks/actions \
  src/aio/aiops/live_executor \
  src/aio/tests/test_generate_incident_history.py \
  src/aio/tests/test_runbook_action_scripts.py \
  src/aio/tests/test_live_executor_service.py
```

Kết quả:

```text
platform_compileall=pass
```

### Integration smoke

Smoke chạy bằng Python 3.11 venv, fake/simulation mode, không live-mutate Kubernetes.

Kết quả:

```text
phase5_integration_smoke=pass records=7 valid_actions=7
```

Smoke đã verify:

- Generator seed pass với `records=7`, `valid_actions=7`.
- `IncidentHistoryStore.load()` load được runtime history.
- `plan_scale_deployment.run()` trả plan 2 -> 3 replicas, có `plan_hash` và `rollback_token`.
- `scale_deployment.run()` execute simulation thành công với plan hợp lệ.
- `scale_deployment.run()` block stale state bằng `resource_version_mismatch`.
- `restore_deployment_replicas.run()` rollback về 2 replicas bằng execution snapshot.
- `page_oncall.run()` audit-only, không execute.
- Executor service plan -> execute -> status -> rollback pass.
- Protected target `payment` bị block với reason `protected_target`.
- Duplicate execute idempotency trả cùng response, không tạo action mới.
- FastAPI auth block request thiếu bearer token.
- FastAPI `/v1/actions/plan` pass khi token/header hợp lệ.
- SQLite audit store ghi append-only audit events.
- Các response smoke đều JSON-serializable.

### Chart validation

Chart repo: `techx-corp-chart`, branch `cdo/self-heal-live-executor-chart`.

```bash
helm lint . -f values-aiops-live-executor.yaml
```

Kết quả:

```text
1 chart(s) linted, 0 chart(s) failed
```

```bash
helm template techx-corp . \
  -n techx-corp-prod \
  -f values-aiops-live-executor.yaml \
  --show-only templates/aiops-live-executor.yaml
```

Kết quả:

```text
chart_executor_template=pass lines=234
```

## Test environment note

- `src/aio/.venv` dùng Python 3.11.14 nhưng chưa có `pytest`.
- System `python3` là Python 3.9.6, không tương thích runtime AIOps `>=3.11`.
- Vì vậy Phase 5 dùng direct smoke bằng venv Python 3.11 thay cho pytest.
- FastAPI TestClient có deprecation warning từ Starlette/httpx; warning không ảnh hưởng kết quả.

## Boundary

- Không live-mutate Kubernetes trong Phase 5.
- Live execution vẫn disabled trong chart default và overlay có `AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY=false`.
- Phase 6 approval gate phải pass trước khi bật live.

