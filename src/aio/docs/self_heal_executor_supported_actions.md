# Báo cáo năng lực action/runbook executor cho Self-Heal AIOps

## Mục tiêu

Tài liệu này mô tả các action mà CDO đang công bố cho team AI sử dụng trong remediation engine. Nguồn machine-readable nằm tại `src/aio/config/executor_supported_actions.json` và endpoint runtime là `GET /v1/actions/catalog`.

## Kết luận hiện tại

Ở phạm vi P0/Phase 3, CDO executor chỉ có một remediation có thể lập kế hoạch và submit qua executor: `scale_product_catalog` cho `Deployment/product-catalog` trong namespace `techx-corp-prod`.

Action này có dry-run/plan, có execute ở mức executor audit/simulation, có rollback token và rollback action `restore_deployment_replicas`. Tuy nhiên, live Kubernetes mutation vẫn đang tắt: `live_execute_supported=false`. Vì vậy AI runtime không được coi đây là live auto-heal thật sự cho tới khi policy và cấu hình live apply được bật có kiểm soát.

## Endpoint catalog

Endpoint hiện có:

```text
GET /v1/actions/catalog
```

Endpoint yêu cầu cùng cơ chế xác thực với các endpoint executor khác:

```text
Authorization: Bearer <AIOPS_LIVE_EXECUTOR_TOKEN>
X-AIOPS-Account: aiops-runtime
X-Request-Id: <request-id>
```

Payload trả về là danh sách action capability, mỗi phần tử có các trường chính:

```text
action_id, action_type, target, target_kind, namespace,
executor_supported, recommendation_only, audit_only,
dry_run_supported, execute_supported, live_execute_supported,
rollback_supported, rollback_action_id,
verification_query_id, policy_id, policy_approval_required,
protected, blocked, blocked_reason, blast_radius_services
```

## Bảng action capability

| action_id | action_type | target | namespace | dry-run | execute | live execute | rollback | verification | policy/approval | protected/blocked | blast radius |
|---|---|---|---|---:|---:|---:|---:|---|---|---|---|
| `scale_product_catalog` | `scale_deployment` | `product-catalog` | `techx-corp-prod` | Có | Có, executor simulation/audit | Không | Có, `restore_deployment_replicas` | `product-catalog.p95_latency_5m` | `phase3-scale-policy-v1`, cần approval | Không | `frontend`, `recommendation`, `product-reviews`, `checkout` |
| `restart_product_catalog` | `restart` | `product-catalog` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Không | `frontend`, `recommendation`, `product-reviews`, `checkout` |
| `restart_checkout` | `restart` | `checkout` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Không | `frontend`, `frontend-proxy` |
| `restart_cart` | `restart` | `cart` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Không | `checkout`, `frontend` |
| `restart_frontend` | `restart` | `frontend` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Không | `frontend-proxy` |
| `restart_frontend_proxy` | `restart` | `frontend-proxy` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Không | `frontend`, `checkout`, `product-catalog`, `cart` |
| `restart_payment` | `restart` | `payment` | `techx-corp-prod` | Chỉ recommendation | Không | Không | Không | Chưa có | Không áp dụng | Có, blocked | `checkout` |
| `page_oncall` | `page` | `platform-team` | Không áp dụng | Có | Không | Không | Không | Không áp dụng | Không áp dụng | Không, audit-only | Không có |
| `page_data_oncall` | `page` | `data-platform-oncall` | Không áp dụng | Có | Không | Không | Không | Không áp dụng | Không áp dụng | Không, audit-only | Không có |

## Protected targets

Executor policy hiện chặn các target/system sau:

```text
postgresql, kafka, valkey-cart, redis, flagd, openfeature,
aiops-runtime, observability, payment
```

Executor policy hiện chặn các namespace sau:

```text
kube-system, kube-public, kube-node-lease, linkerd, monitoring, observability
```

Team AI không nên sinh live action cho các target hoặc namespace này. Nếu incident liên quan các target này, hướng xử lý mặc định là `page_oncall` hoặc runbook thủ công.

## Cách team AI nên consume

Nếu AI runtime muốn chọn action có thể gọi executor, lọc:

```text
executor_supported=true AND blocked=false
```

Nếu AI runtime muốn chọn action có thể mutate live Kubernetes, lọc:

```text
executor_supported=true AND live_execute_supported=true AND blocked=false
```

Với cấu hình hiện tại, tập action live mutation là rỗng. Action `scale_product_catalog` chỉ nên được dùng cho plan/execute qua executor ở trạng thái simulation/audit, chưa được coi là auto-heal live.

Các action `restart_*` vẫn tồn tại trong `actions.json` để phục vụ incident history, scoring, recommendation và fallback decision, nhưng CDO executor chưa hỗ trợ restart thật, rollback thật hoặc post-action verification cho nhóm này.

Các action `page_*` hiện chỉ ghi audit/no-op. Chúng chưa tích hợp Slack, PagerDuty, email, SNS hoặc paging provider thật.
