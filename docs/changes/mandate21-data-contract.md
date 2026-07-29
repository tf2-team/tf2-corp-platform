# Mandate 21 — Data Contract: JSONL Ledger & Prometheus Metrics

**Date:** 2026-07-28  
**Author:** CDO-03 / TF2 (Người 2)  
**Người 3 reference:** `tf2-corp-chart/scripts/mandate21-fis-drill.ps1`

---

## 1. k6 JSONL Ledger Contract

Người 3 ghi mỗi checkout request thành một dòng JSONL. Người 2 đọc file này trong `mandate21-reconcile.ps1` để đối chiếu với DynamoDB outbox và Accounting RDS.

### Schema

```json
{
  "trace_id":       "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "test_request_id": "k6-iter-0001-vu-1",
  "timestamp":       "2026-07-29T10:00:00.123Z",
  "http_status":     200,
  "latency_ms":      95,
  "order_id":        "550e8400-e29b-41d4-a716-446655440000",
  "outcome":         "accepted"
}
```

### Field definitions

| Field | Type | Description |
|---|---|---|
| `trace_id` | string | W3C traceparent format — dùng để tìm span trong Jaeger |
| `test_request_id` | string | ID duy nhất của k6 iteration — format `k6-iter-{n}-vu-{vu}` |
| `timestamp` | string | ISO 8601 UTC — thời điểm gửi request |
| `http_status` | int | HTTP status code nhận được |
| `latency_ms` | int | Latency end-to-end tính bằng millisecond |
| `order_id` | string | UUID của order từ response body — chỉ có khi `http_status == 2xx` |
| `outcome` | string | `accepted` / `ambiguous` / `rejected` — xem định nghĩa bên dưới |

### Outcome definitions

| Outcome | Điều kiện | Reconciler xử lý |
|---|---|---|
| `accepted` | HTTP 2xx **và** response body có `order_id` | Phải có durable DynamoDB record **và** RDS record |
| `ambiguous` | Timeout / connection error / HTTP 5xx không có `order_id` | Reconciler tra cứu Jaeger xem có Payment span thành công không |
| `rejected` | HTTP 4xx / HTTP 5xx rõ ràng / charge failed | Không expect durable record |

### Không chứa

- Card number, CVV, expiry
- Email address, customer name, shipping address
- AWS credentials, tokens, secrets

---

## 2. Prometheus Metric Names

Người 3 dùng các metric sau trong Grafana dashboard `Mandate 21 - AZ Failover`. Đây là tên **thực tế** từ code — cập nhật nếu tên khác.

### Accounting persistence errors

Các metric này được emit qua OpenTelemetry từ Accounting service khi ghi DB thất bại. Hiện tại lỗi được log nhưng **chưa có custom counter** — observable qua log query hoặc span error.

| Metric | Nguồn | Ghi chú |
|---|---|---|
| Log query: `Order parsing failed` | OpenSearch / CloudWatch | Filter `level=error AND message="Order parsing failed"` |
| Span error rate: `accounting.Consumer` | Jaeger / Prometheus (via OTel) | `rate(traces_spanmetrics_calls_total{service="accounting",status_code="ERROR"}[1m])` |

**Sau khi migration:** `shipping_pkey` và `order_parse_failed` sẽ về 0. Gate xác nhận bằng log query này liên tục 30 phút không có kết quả.

### Outbox age metrics (checkout service)

| Metric | Label | Mô tả |
|---|---|---|
| `checkout_outbox_pending_age_seconds` | — | Tuổi của item `pending` cũ nhất trong DynamoDB outbox |
| `checkout_outbox_published_age_seconds` | — | Tuổi của item `published` cũ nhất (chưa ACK) |

> **Lưu ý:** Các metric này hiện chưa được instrument trong `outbox/store.go`. Cách đo thay thế: query DynamoDB trực tiếp trong dashboard qua YACE hoặc CloudWatch custom metric. Người 3 đang dùng YACE — confirm tên metric YACE với Người 1.

### Order flow counters

| Metric | Nguồn | Mô tả |
|---|---|---|
| `accepted_orders_total` | k6 JSONL ledger | Tổng `outcome=accepted` trong cửa sổ đo |
| `durable_orders_total` | DynamoDB item count (status≠deleted) | Số order có durable intent |
| `persisted_orders_total` | RDS `accounting.order` count | Số order đã persist vào PostgreSQL |
| `ambiguous_requests_total` | k6 JSONL ledger | Tổng `outcome=ambiguous` |

### Acceptance invariant (reconciler checks)

```
accepted_orders_total == durable_orders_total == persisted_orders_total
ambiguous_requests_total với Payment span == 0
duplicate order_id trong RDS == 0
```

---

## 3. Reconciler interface (cho Người 3)

```powershell
./mandate21-reconcile.ps1 `
  -EvidenceDirectory <evidence-directory> `
  -FaultId <fault-id>
```

- Exit code `0` = PASS
- Exit code `1` = có sai lệch
- Output: `<evidence-directory>/reconciliation-report.json`

---

## 4. Changelog

| Date | Author | Change |
|---|---|---|
| 2026-07-28 | CDO-03 | Initial contract document |
