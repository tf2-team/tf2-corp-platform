# Self-heal CDO Phase 7 validation

Ngay cap nhat: 2026-07-29

## Scope

Phase 7 mo rong CDO live executor de support executable scale actions theo yeu cau team AI:

- `scale_frontend_proxy`
- `scale_frontend`
- `scale_checkout`
- `scale_cart`

Dong thoi giu `scale_product_catalog` trong allowlist hien co.

## Ket qua implementation

- Da tao branch platform: `feat/aio-executable-scale-actions`.
- Da mo rong runtime allowlist trong `runbooks/actions/common.py`.
- Da them 4 action scale vao `config/actions.json`.
- Da cap nhat `config/executor_supported_actions.json`.
- Da cap nhat `config/executor_service_support.json`.
- Da sua rollback resolver de rollback dung action goc tu execution snapshot thay vi default ve `scale_product_catalog`.
- Da them runtime catalog gating:
  - static catalog co the khai bao action live-capable;
  - endpoint runtime chi tra `live_execute_supported=true` khi `allow_live_apply=true`.
- Da them action budget guardrail cho executor service:
  - `AIOPS_LIVE_EXECUTOR_ACTION_BUDGET_WINDOW_SECONDS`;
  - `AIOPS_LIVE_EXECUTOR_ACTION_BUDGET_MAX_EXECUTIONS`.
- Da cap nhat docs capability tai `docs/self_heal_executor_supported_actions.md`.

## Validation da chay

```bash
cd techx-corp-platform/src/aio
.venv/bin/python -m compileall aiops runbooks tests
```

Ket qua:

```text
compileall=pass
```

Do `.venv` chua co `pytest`, da chay direct harness bang Python 3.11 cho cac test module lien quan:

```text
tests/test_runbook_action_scripts.py
tests/test_live_executor_service.py
tests/test_generate_incident_history.py
```

Ket qua:

```text
phase7_direct_tests=pass tests=31
```

JSON/generator validation:

```bash
.venv/bin/python -m json.tool config/actions.json >/dev/null
.venv/bin/python -m json.tool config/executor_supported_actions.json >/dev/null
.venv/bin/python -m json.tool config/executor_service_support.json >/dev/null
.venv/bin/python scripts/generate_incident_history.py \
  --seed config/incidents_history.seed.json \
  --actions config/actions.json \
  --check
```

Ket qua:

```text
records=7
valid_actions=7
errors=0
```

## Chart validation

Da tao branch chart: `feat/aio-executable-scale-actions`.

Chart thay doi:

- RBAC `resourceNames` duoc mo rong cho:
  - `product-catalog`;
  - `frontend-proxy`;
  - `frontend`;
  - `checkout`;
  - `cart`.
- Default deploy van `AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY=false`.
- Them overlay live-test `values-aiops-live-executor-live-test.yaml` voi `AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY=true`.
- Them env cooldown/action budget vao chart.

Validation da chay:

```bash
cd techx-corp-chart
helm lint . -f values-aiops-live-executor.yaml
helm lint . -f values-aiops-live-executor-live-test.yaml
helm template techx-corp . -f values-aiops-live-executor.yaml \
  --show-only templates/aiops-live-executor.yaml
helm template techx-corp . -f values-aiops-live-executor-live-test.yaml \
  --show-only templates/aiops-live-executor.yaml
```

Ket qua:

```text
helm_lint_default_overlay=pass
helm_lint_live_test_overlay=pass
helm_template_default_overlay=pass
helm_template_live_test_overlay=pass
```

## Live Kubernetes status

Chua live-mutate Kubernetes trong validation nay.

Truoc khi live smoke:

- Xac nhan namespace test la dev/demo approved.
- Xac nhan bearer token secret da san sang.
- Deploy executor voi `values-aiops-live-executor-live-test.yaml`.
- Xac nhan 5 Deployment allowlisted ton tai.
- Ghi baseline replicas cho tung Deployment.
- Goi plan/execute/status/rollback qua endpoint executor cho tung action.
- Sau moi action, rollback ve baseline replicas.
