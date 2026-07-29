# Báo cáo năng lực CDO executor theo action và theo service

## Mục tiêu

Tài liệu này dùng để team AI/AIOps cập nhật action catalog của remediation engine. Mục tiêu chính là để engine chỉ recommend các action mà CDO executor thật sự hỗ trợ, thay vì nhầm lẫn giữa action từng xuất hiện trong dữ liệu/history và action có thể gọi executor để chạy.

CDO công bố hai nguồn machine-readable:

```text
src/aio/config/executor_supported_actions.json
src/aio/config/executor_service_support.json
```

Runtime executor cũng công bố hai endpoint:

```text
GET /v1/actions/catalog
GET /v1/services/catalog
```

`/v1/actions/catalog` trả capability theo từng action. `/v1/services/catalog` trả ma trận support theo từng service trong `runbooks/service_runbook_map.json`.

## Kết luận hiện tại

Ở phạm vi P0/Phase 3, CDO executor chỉ có một remediation action có thể lập plan/submit qua executor:

```text
scale_product_catalog
```

Target của action này là:

```text
Deployment/product-catalog
Namespace: techx-corp-prod
```

Action này có dry-run/plan, có execute ở mức executor audit/simulation, có rollback token và rollback action `restore_deployment_replicas`. Tuy nhiên, live Kubernetes mutation vẫn đang tắt, nên `live_execute_supported=false`.

Vì vậy:

- Nếu AI muốn chọn action có thể gọi executor ở mức plan/execute simulation: chỉ có `scale_product_catalog`.
- Nếu AI muốn chọn action có thể mutate live Kubernetes: hiện tại chưa có action nào.
- Các action `restart_*` chỉ là recommendation/history catalog, chưa phải action CDO executor chạy được.
- Các action `page_*` chỉ ghi audit/no-op, chưa gọi paging provider thật như Slack/PagerDuty/email/SNS.

## Authentication

Các endpoint executor yêu cầu cùng cơ chế auth:

```text
Authorization: Bearer <AIOPS_LIVE_EXECUTOR_TOKEN>
X-AIOPS-Account: aiops-runtime
X-Request-Id: <request-id>
```

## Action Catalog

Endpoint:

```text
GET /v1/actions/catalog
```

Payload trả về là danh sách action capability. Các trường chính:

```text
action_id, action_type, target, target_kind, namespace,
executor_supported, recommendation_only, audit_only,
dry_run_supported, execute_supported, live_execute_supported,
rollback_supported, rollback_action_id,
verification_query_id, policy_id, policy_approval_required,
protected, blocked, blocked_reason, blast_radius_services
```

| action_id | action_type | target | namespace | executor supported | live execute | rollback | verification | policy/approval | trạng thái |
|---|---|---|---|---:|---:|---:|---|---|---|
| `scale_product_catalog` | `scale_deployment` | `product-catalog` | `techx-corp-prod` | Có | Không | Có, `restore_deployment_replicas` | `product-catalog.p95_latency_5m` | `phase3-scale-policy-v1`, cần approval | Executor simulation/audit |
| `restart_product_catalog` | `restart` | `product-catalog` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Recommendation-only |
| `restart_checkout` | `restart` | `checkout` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Recommendation-only |
| `restart_cart` | `restart` | `cart` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Recommendation-only |
| `restart_frontend` | `restart` | `frontend` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Recommendation-only |
| `restart_frontend_proxy` | `restart` | `frontend-proxy` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Recommendation-only |
| `restart_payment` | `restart` | `payment` | `techx-corp-prod` | Không | Không | Không | Chưa có | Không áp dụng | Protected/blocked |
| `page_oncall` | `page` | `platform-team` | Không áp dụng | Có | Không | Không | Không áp dụng | Không áp dụng | Audit-only/no-op |
| `page_data_oncall` | `page` | `data-platform-oncall` | Không áp dụng | Có | Không | Không | Không áp dụng | Không áp dụng | Audit-only/no-op |

## Service Catalog

Endpoint:

```text
GET /v1/services/catalog
```

Payload trả về là danh sách service support. Các trường chính:

```text
service, namespace, support_status, executor_supported,
live_execute_supported, protected, supported_actions,
recommendation_actions, fallback_action, runbooks
```

`supported_actions` chỉ chứa action mà CDO executor hỗ trợ chạy qua executor. `recommendation_actions` chỉ dùng cho scoring/history/recommendation và không được coi là executable executor action.

| service | namespace | support_status | executor supported | live execute | supported_actions | recommendation_actions | fallback |
|---|---|---|---:|---:|---|---|---|
| `accounting` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `ad` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `aiops` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `aws-bedrock` | Không áp dụng | `external_dependency_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `cart` | `techx-corp-prod` | `recommendation_only` | Không | Không | Không có | `restart_cart` | `page_oncall` |
| `checkout` | `techx-corp-prod` | `recommendation_only` | Không | Không | Không có | `restart_checkout` | `page_oncall` |
| `currency` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `email` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `external-llm` | Không áp dụng | `external_dependency_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `flagd` | `techx-corp-prod` | `protected_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `flagd-ui` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `fraud-detection` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `frontend` | `techx-corp-prod` | `recommendation_only` | Không | Không | Không có | `restart_frontend` | `page_oncall` |
| `frontend-proxy` | `techx-corp-prod` | `recommendation_only` | Không | Không | Không có | `restart_frontend_proxy` | `page_oncall` |
| `grafana` | `observability` | `observability_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `image-provider` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `jaeger` | `observability` | `observability_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `kafka` | `techx-corp-prod` | `protected_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `llm` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `load-generator` | `techx-corp-prod` | `excluded_from_remediation` | Không | Không | Không có | Không có | `page_oncall` |
| `mem0` | Không áp dụng | `external_dependency_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `opensearch` | `observability` | `observability_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `otel-collector` | `observability` | `observability_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `payment` | `techx-corp-prod` | `protected_recommendation_only` | Không | Không | Không có | `restart_payment` | `page_oncall` |
| `postgresql` | `techx-corp-prod` | `protected_manual_only` | Không | Không | Không có | Không có | `page_data_oncall` |
| `product-catalog` | `techx-corp-prod` | `executor_supported_simulation_only` | Có | Không | `scale_product_catalog` | `restart_product_catalog` | `page_oncall` |
| `product-reviews` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `prometheus` | `observability` | `observability_manual_only` | Không | Không | Không có | Không có | `page_oncall` |
| `quote` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `recommendation` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `shipping` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `shopping-copilot` | `techx-corp-prod` | `manual_runbook_only` | Không | Không | Không có | Không có | `page_oncall` |
| `valkey-cart` | `techx-corp-prod` | `protected_manual_only` | Không | Không | Không có | Không có | `page_oncall` |

## Protected targets và namespace

Executor policy hiện chặn các target/system sau:

```text
postgresql, kafka, valkey-cart, redis, flagd, openfeature,
aiops-runtime, observability, payment
```

Executor policy hiện chặn các namespace sau:

```text
kube-system, kube-public, kube-node-lease, linkerd, monitoring, observability
```

Nếu incident liên quan target/namespace protected, AI runtime không được sinh live mutation. Hướng xử lý mặc định là page/audit hoặc runbook thủ công.

## Rule consume cho team AI

Để chọn action có thể gọi CDO executor:

```text
action.executor_supported=true
AND action.blocked=false
AND service.executor_supported=true
```

Để chọn action có thể mutate live Kubernetes:

```text
action.executor_supported=true
AND action.live_execute_supported=true
AND action.blocked=false
AND service.live_execute_supported=true
```

Với catalog hiện tại, tập live mutation là rỗng.

Để tránh recommend nhầm:

- Không coi `restart_*` là executable action.
- Không coi `page_*` là paging thật; hiện chỉ audit/no-op.
- Không chọn action cho service có `support_status=protected_manual_only`, `observability_manual_only`, `external_dependency_manual_only` hoặc `excluded_from_remediation` làm live remediation.
- Với các service `manual_runbook_only`, AI nên trả về runbook/fallback page thay vì action executor.

## Ghi chú triển khai

`GET /v1/actions/catalog` vẫn trả list action để không phá client hiện có. `GET /v1/services/catalog` được thêm mới để đáp ứng yêu cầu support theo từng service.

Hai file JSON được copy vào image AIOps qua thư mục `config/`, nên executor runtime có thể đọc trực tiếp khi deploy image mới.
