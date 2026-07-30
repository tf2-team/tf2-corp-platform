# Self-heal CDO Phase 3 Validation

Date: 2026-07-28

Mục đích: ghi lại kết quả Phase 3 cho live executor service P0.

## Artifact đã thêm

```text
src/aio/aiops/live_executor/__init__.py
src/aio/aiops/live_executor/app.py
src/aio/aiops/live_executor/service.py
src/aio/aiops/live_executor/store.py
src/aio/tests/test_live_executor_service.py
```

## Scope Phase 3

Executor service P0 cung cấp HTTP API riêng để AI runtime gọi bằng JSON.
AIO runtime vẫn không nhận Kubernetes write permission.

Endpoints đã có trong `create_app()`:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/actions/catalog`
- `POST /v1/actions/plan`
- `POST /v1/actions/execute`
- `GET /v1/actions/{execution_id}`
- `POST /v1/actions/{execution_id}/rollback`
- `POST /actions` legacy endpoint cho `LiveExecutorClient.submit_action()`

## Persistent store

`LiveExecutorStore` dùng SQLite WAL và tạo các bảng:

- `plans`
- `executions`
- `idempotency_keys`
- `target_cooldowns`
- `audit_events`

Audit event được ghi append-only cho plan/execute/rollback/page transitions.

## Guardrail P0

Executor/service hiện hỗ trợ:

- allowlist P0 từ action scripts: `scale_product_catalog`;
- policy id `phase3-scale-policy-v1`;
- policy approval/expiry checks qua action scripts;
- idempotency key cho plan/execute/rollback;
- single-flight theo target khi execution đang `running`;
- stale state reject bằng `resource_version_mismatch`;
- rollback bằng snapshot của đúng execution;
- bearer token auth trong FastAPI app khi `AIOPS_LIVE_EXECUTOR_TOKEN` hoặc explicit token được cấu hình;
- legacy `/actions` route.

Phase 3 vẫn không live-mutate Kubernetes. Mutating scripts block `live_apply=true` cho tới Phase 6 approval gate.

## Validation đã chạy

Compile check bằng venv Python 3.11:

```bash
src/aio/.venv/bin/python -m compileall -q \
  src/aio/aiops/live_executor \
  src/aio/tests/test_live_executor_service.py
```

Kết quả: pass.

Direct service/app tests bằng venv Python 3.11:

```text
phase3_direct_tests=pass
```

Audit store check:

```text
phase3_audit_store=pass events=1
```

Direct tests đã verify:

- plan -> execute -> status -> rollback flow;
- execute idempotency trả cùng response, không tạo action mới;
- stale resource version bị block;
- FastAPI auth block request thiếu bearer token;
- FastAPI `/v1/actions/plan` trả planned response khi auth hợp lệ.

## Test environment note

- `src/aio/.venv` dùng Python 3.11.14 nhưng chưa có `pytest`.
- System `python3` là Python 3.9.6, không tương thích runtime AIOps `>=3.11`.
- Direct tests được gọi bằng venv Python 3.11 để thay thế cho pytest trong Phase 3.
- FastAPI TestClient chạy được nhưng phát deprecation warning từ Starlette/httpx; warning này không ảnh hưởng kết quả Phase 3.

## Boundary

- Chưa kết nối live Kubernetes write client.
- Chưa triển khai Helm/RBAC/NetworkPolicy; phần đó thuộc Phase 4.
- Chưa bật live mutation; cần platform owner approve namespace/cluster ở Phase 6.

