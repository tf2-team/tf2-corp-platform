# Action Catalog Đề Xuất Cho CDO

File JSON để gửi CDO:

```text
src/aio/config/desired_executor_action_catalog.json
```

Ý tưởng của file này rất đơn giản: AIOps gen sẵn một danh sách action theo hạ tầng/runbook hiện tại. Bên CDO support được action nào thì giữ lại và viết script executor cho action đó. Action nào không làm được thì xóa khỏi JSON.

File này **không phải runtime allowlist chính thức** và **không có nghĩa là tất cả action đã chạy được live**.

## Format JSON

Format được giữ giống `src/aio/config/actions.json` hiện tại:

```json
{
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "cost_min": 2.0,
  "downtime_min": 0.0,
  "blast_radius_services": ["frontend", "recommendation"],
  "replicas": 3
}
```

Trong đó:

| field | ý nghĩa |
|---|---|
| `action_id` | ID action mà AIOps sẽ chọn/gọi |
| `action_type` | Loại script CDO cần làm: `scale_deployment`, `restart`, `diagnostics`, `page` |
| `target` | Service/dependency/on-call target |
| `target_kind` | Loại target: `Deployment`, `Datastore`, `Pipeline`, `OnCall` |
| `cost_min` | Ước lượng chi phí/thời gian xử lý |
| `downtime_min` | Ước lượng downtime nếu action có rủi ro downtime |
| `blast_radius_services` | Service có thể bị ảnh hưởng |
| `replicas` | Với scale là desired replicas/minReplicas; với action khác để `0` hoặc replica tham chiếu |

## Nhóm Action Trong Catalog

### Scale HPA

Nhóm này ưu tiên nhất vì nhiều service đã có HPA trong chart. Nếu CDO làm được, script nên patch HPA `minReplicas` thay vì patch Deployment replicas trực tiếp.

```text
scale_product_catalog
scale_cart
scale_checkout
scale_currency
scale_frontend
scale_frontend_proxy
scale_product_reviews
scale_quote
scale_recommendation
scale_shipping
```

Quyền Kubernetes cần cho nhóm này:

```text
autoscaling/horizontalpodautoscalers get, patch, update
```

### Restart Deployment

Nhóm này là rolling restart cho các service stateless. CDO support được service nào thì giữ action đó, không support thì xóa.

```text
restart_accounting
restart_ad
restart_cart
restart_checkout
restart_currency
restart_email
restart_fraud_detection
restart_frontend
restart_frontend_proxy
restart_image_provider
restart_llm
restart_product_catalog
restart_product_reviews
restart_quote
restart_recommendation
restart_shipping
restart_payment
```

Quyền Kubernetes cần cho nhóm này:

```text
apps/deployments get, patch, update
```

Lưu ý: `restart_payment` nên để CDO quyết định vì `payment` là service nhạy cảm.

### Diagnostics

Nhóm này dùng cho datastore, pipeline, observability, external dependency. Mục tiêu là lấy snapshot/diagnostics, không mutate live.

```text
collect_postgresql_diagnostics
collect_valkey_cart_diagnostics
collect_kafka_diagnostics
collect_observability_diagnostics
collect_ai_dependency_diagnostics
```

### Page On-call

Nhóm này để CDO nối vào notification/paging provider thật nếu có.

```text
page_oncall
page_checkout_oncall
page_catalog_oncall
page_data_oncall
page_aie_oncall
```

## Cách Làm Việc Với CDO

Gửi CDO file JSON này và nói rõ:

```text
Bên AIOps đã gen candidate action catalog theo service/runbook/HPA hiện tại.
Bên CDO support được action nào thì giữ lại và làm script executor cho action đó.
Action nào chưa support hoặc không an toàn thì xóa khỏi file giúp tụi em.
```

Sau khi CDO trả lại file đã prune, AIOps mới dùng file đó để cập nhật `actions.json` runtime thật.

