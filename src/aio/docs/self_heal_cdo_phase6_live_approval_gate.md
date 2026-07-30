# Self-heal CDO Phase 6 Live Approval Gate

Date: 2026-07-28

Mục đích: xác định điều kiện bắt buộc trước khi bật live mutation cho self-heal executor.

## Current Status

```text
live_approval_status=not_approved
live_apply=disabled
```

P0 implementation đã pass fake/simulation smoke tests, nhưng chưa được phép live-mutate Kubernetes.

## Required Approval Checklist

Chỉ bật live khi toàn bộ điều kiện sau được xác nhận:

- Platform owner ký owner/expiry cho policy `phase3-scale-policy-v1`.
- Policy expiry được xác nhận, hiện proposal là `2026-08-31T23:59:59Z`.
- Namespace `techx-corp-prod` được xác nhận là dev/demo được phép mutate, hoặc có namespace demo riêng.
- `Deployment/product-catalog` tồn tại trong namespace approved.
- Baseline replica count của `Deployment/product-catalog` là 2.
- Executor Secret `aiops-live-executor-token` đã được tạo bằng secret manager/ESO
  với cả `token` và `approval-id` từ policy decision đã ký.
- Executor PVC `aiops-live-executor-state` được provision thành công.
- NetworkPolicy đã áp dụng và chỉ cho `aiops-runtime` gọi executor.
- Executor ServiceAccount/RBAC chỉ mutate `Deployment/product-catalog` và
  `HorizontalPodAutoscaler/product-catalog`.
- Trong live-test window, Argo CD phải tạm bỏ reconcile riêng trường
  `HPA/product-catalog.spec.minReplicas`; executor sẽ restore floor ban đầu sau
  verification hoặc rollback. Không giữ ignore rule này khi quay lại guarded mode.
- AIO runtime vẫn giữ Kubernetes read-only.
- AI runtime post-action verification dùng telemetry mới hơn `executed_at`.
- Escalation/page channel thật đã được chốt, hoặc `page_oncall.py` vẫn giữ audit-only.
- Runbook rollback đã được platform owner review.

## Configuration Gate

Chart default:

```yaml
aiopsLiveExecutor:
  enabled: false
  config:
    allowLiveApply: "false"
```

Opt-in overlay hiện vẫn giữ:

```yaml
AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY: "false"
```

Để bật live trong tương lai, cần PR riêng sau approval, không bật ngầm trong P0 handoff.

## Not Allowed Before Approval

- Không mutate production/shared critical namespace.
- Không mutate StatefulSet, database, Kafka, cache, flagd/OpenFeature, AIO runtime, observability stack hoặc payment.
- Không dùng `restart_*` làm live action trong P0.
- Không coi missing/stale telemetry là success.
- Không bỏ qua dry-run/plan hash/resourceVersion/idempotency/rollback token.

## Approved P0 Live Scope Sau Khi Gate Pass

Nếu gate được approve, live scope P0 chỉ là:

```text
action_id: scale_product_catalog
action_type: scale_deployment
target_kind: Deployment
target: product-catalog
namespace: approved dev/demo namespace
replicas: 2 -> 3
rollback: restore to pre-action replica count
```

