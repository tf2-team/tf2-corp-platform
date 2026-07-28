# Self-heal CDO Phase 2 Validation

Date: 2026-07-28

Mục đích: ghi lại kết quả Phase 2 cho runbook action scripts.

## Artifact đã thêm

```text
src/aio/runbooks/actions/__init__.py
src/aio/runbooks/actions/common.py
src/aio/runbooks/actions/plan_scale_deployment.py
src/aio/runbooks/actions/scale_deployment.py
src/aio/runbooks/actions/restore_deployment_replicas.py
src/aio/runbooks/actions/page_oncall.py
src/aio/tests/test_runbook_action_scripts.py
```

## Scope Phase 2

Phase 2 cung cấp script Python theo contract `def run(context: dict) -> dict`.

Các script hiện hỗ trợ:

- Dry-run plan cho `scale_product_catalog`.
- Execute simulation cho plan hợp lệ bằng `kubernetes_snapshot` trong context.
- Reject stale `resource_version`.
- Rollback simulation bằng snapshot của execution.
- Page-only audit cho `page_oncall`.

Phase 2 chưa live-mutate Kubernetes. Nếu context bật `live_apply=true`, mutating scripts sẽ block bằng reason `live_apply_disabled_phase2`.

## Validation đã chạy

Compile check bằng venv Python 3.11:

```bash
src/aio/.venv/bin/python -m compileall -q \
  src/aio/runbooks/actions \
  src/aio/tests/test_runbook_action_scripts.py
```

Kết quả: pass.

Smoke trực tiếp bằng venv Python 3.11:

```text
phase2_runbook_scripts=pass
```

Smoke đã verify:

- `plan_scale_deployment.run()` trả dry-run plan từ 2 lên 3 replicas.
- Plan response có `plan_hash`, `rollback_token`, before/after snapshot và blast radius.
- `scale_deployment.run()` execute simulation thành công khi plan còn hạn và `resource_version` khớp.
- `scale_deployment.run()` block bằng `resource_version_mismatch` khi state đổi sau plan.
- `restore_deployment_replicas.run()` restore replica count về snapshot trước action.
- `page_oncall.run()` là audit-only, `executed=false`.
- Tất cả response smoke đều JSON-serializable.

## Test environment note

- `src/aio/.venv` dùng Python 3.11.14 nhưng chưa có `pytest`.
- System `python3` là Python 3.9.6, không tương thích runtime AIOps vì project yêu cầu Python `>=3.11`.
- Do đó chưa chạy được pytest bằng venv trong Phase 2.
- Khi môi trường dev được cài pytest cho Python 3.11, chạy:

```bash
PYTHONPATH=src/aio src/aio/.venv/bin/python -m pytest \
  src/aio/tests/test_runbook_action_scripts.py \
  src/aio/tests/test_generate_incident_history.py \
  -q
```

## Boundary

- `restart_*` vẫn không phải live action trong P0.
- `scale_product_catalog` là golden action duy nhất cho path plan/execute/rollback.
- Các script không tin namespace/target tùy ý từ caller; config P0 được resolve từ allowlist nội bộ.
- Live mutation thuộc Phase 3 executor và Phase 6 approval gate.

