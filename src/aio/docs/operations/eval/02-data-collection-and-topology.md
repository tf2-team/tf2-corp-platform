# 2. Câu chuyện thu thập dữ liệu & Topology

## 2.1 Toàn cảnh: dữ liệu đi từ đâu đến đâu

```text
Platform services (frontend, checkout, cart, catalog, payment, ...)
  --OTel metrics/traces/logs-->  OTel Collector
                                     |-- metrics --> Prometheus
                                     |-- traces  --> Jaeger
                                     |-- logs    --> OpenSearch

Prometheus  --bounded query IDs, chỉ metrics--> AIOps Runtime
Grafana     --authenticated webhook (firing/resolved)--> AIOps Runtime
Jaeger      --on-demand, bounded enrichment (chỉ khi có candidate)--> AIOps Runtime
OpenSearch  --on-demand, bounded log evidence (đã redact)--> AIOps Runtime
Kubernetes API --read-only (deployments/pods/status)--> AIOps Runtime

AIOps Runtime --> SQLite WAL/PVC (incidents, audit, observations)
AIOps Runtime --normalized incident, dry-run recommendation--> TF2 on-call channel
Grafana       --route độc lập, không phụ thuộc AIOps--> TF2 on-call channel
AIOps Runtime --/metrics aiops_*--> Prometheus (self-scrape)
```

Nguồn: `src/aio/docs/Infra.md` (mermaid gốc), `src/aio/docs/blocks/1..12`.

**Nguyên tắc quan trọng nhất:** AIOps là **consumer** của observability plane, **không nằm trên đường request của khách hàng**. Nếu AIOps chết/mất PVC/restart, hệ thống SLO chính (Grafana → on-call) vẫn phải hoạt động độc lập — đây là lý do có 2 route riêng từ Grafana (một route thẳng tới on-call, một route qua webhook AIOps).

## 2.2 Hai nguồn tín hiệu đầu vào

| Nguồn | Cách hoạt động | Khi nào dùng |
| --- | --- | --- |
| **Prometheus polling** | AIOps chủ động query Prometheus theo các `query_id` đã đăng ký sẵn trong `prometheus_queries.json` — **không tự tạo PromQL tùy tiện** | Theo dõi liên tục mọi signal RED/resource |
| **Grafana hard-rule webhook** | Grafana tự đánh giá rule SLO định lượng (hard-rule, ví dụ `checkout_bad_ratio_24h > 1%`), khi rule đổi trạng thái `firing`/`resolved` thì Grafana `POST /api/v1/events/grafana` sang AIOps, xác thực bằng secret/HMAC | Alert SLO chính thức — fire ngay, không cần chờ AIOps correlation/anomaly |

Điểm mấu chốt: **hard-rule không cần AI/anomaly/correlation để quyết định** — nếu `bad_ratio_24h` vượt ngưỡng là firing luôn. AIOps chỉ xử lý phần "hiểu, enrich, route, audit, verify" sau khi đã có sự kiện.

## 2.3 Data phải "qua cổng" trước khi detector được dùng

Trước khi bất kỳ detector nào được chạy trên 1 signal, signal đó phải qua **Signal qualification gate**, phân loại thành:

| Trạng thái | Ý nghĩa | Detector có dùng được không |
| --- | --- | --- |
| `verified` | Đúng metric, đúng label, đúng unit, đúng semantic | Có |
| `missing` | Series không tồn tại | Không — mở `Monitoring-data incident` |
| `stale` | Dữ liệu quá cũ | Không — mở `Monitoring-data incident` |
| `invalid` | Sai shape/unit/label, cardinality vượt giới hạn | Không |
| `fallback-only` | Chỉ hỗ trợ, không dùng làm official SLI chính | Chỉ dùng bổ trợ |

> Nguyên tắc bắt buộc: **missing data không bao giờ được hiểu là "zero error" hay "healthy"**. Thiếu dữ liệu = một loại incident riêng (monitoring-data incident), không phải hệ thống đang tốt.

Sau khi `verified`, dữ liệu được **normalize** (đơn vị, label, time window, service naming — ví dụ `duration_milliseconds` → `seconds`, `service_name="checkout"` → `service="checkout"`) để các detector phía sau không phải tự xử lý dữ liệu lộn xộn từ nhiều nguồn (HTTP/gRPC/span metrics khác nhau).

## 2.4 Enrichment on-demand — không query tràn lan

Sau khi có candidate/correlation (chưa phải trước đó), AIOps mới gọi thêm:

- **Jaeger** — trace ID, service/operation, duration, error span, link trace UI.
- **OpenSearch** — log count, safe excerpts (đã redact PII/secret/prompt), link query.
- **Kubernetes API (read-only)** — pod restart count, available replicas, readiness, rollout state.

Lý do chỉ query on-demand: **kiểm soát cost và dữ liệu nhạy cảm**. Nếu Jaeger/OpenSearch fail, incident vẫn được mở — chỉ giảm confidence hoặc ghi nhận enrichment failure, không chặn alert chính.

## 2.5 Topology — bản đồ blast-radius

Nguồn: `src/aio/docs/operations/topology/platform-topology.graph.json`.

Topology mô tả 3 lớp:

- **`services`** (27 node): mỗi service có `tier`, `team`, `owner_pager`, `criticality` (`low/medium/high/critical`).
- **`stores`** (7 node): PostgreSQL, Valkey-cart, Kafka, Prometheus, Jaeger, OpenSearch, AIOps-state — trong đó PostgreSQL/Valkey-cart được đánh dấu `remediation_class: protected-stateful-external` (AIOps không được mutate).
- **`edges`**: quan hệ gọi thật giữa các service (http/grpc/kafka/flagd/otlp/promql...) — dùng để AIOps suy ra "checkout phụ thuộc payment", "kafka làm cầu nối accounting/fraud-detection", v.v.

**Vì sao topology quan trọng với detection/RCA:**

- Correlation/RCA dùng topology để tính `likely_dependency` (ví dụ: lỗi checkout xảy ra cùng lúc với lỗi payment, và payment nằm trên đường gọi của checkout → nghi ngờ payment).
- Topology xác định **đường bị bảo vệ** (`flagd`, `flagd-ui`) — AIOps chỉ được quan sát, không được mutate/redirect/bypass.
- Topology xác định **blast radius** ví dụ: `frontend-proxy` là cổng vào duy nhất (ảnh hưởng cả storefront + Grafana + Jaeger + flag UI nếu chết); `checkout` là coordinator doanh thu, blast radius đồng bộ gồm cart, valkey-cart, product-catalog, postgresql, currency, shipping, quote, payment.
- File tự ghi rõ: đây là **static JSON**, không được coi là xác nhận SPOF cuối cùng nếu chưa validate lại với kubectl/Jaeger thật.

## 2.6 Vì sao kiến trúc tách 2 vùng: AIOps deployment vs Optional Live Action Boundary

Theo `Infra.md` (mermaid RBAC), AIOps chạy trong 1 pod (`aiops-runtime`, 1 replica, chiến lược `Recreate`) với `ServiceAccount aiops-reader` **chỉ có quyền `get/list/watch` metadata** trên Kubernetes API — không có quyền mutate. Nếu sau này cần hành động thật (restart/scale...), hành động đó phải đi qua một **executor riêng biệt**, với `ServiceAccount` khác, `Role/RoleBinding` hẹp theo `resourceNames`, và chỉ được bật khi có ADR riêng (`ADR-LIVE-001`) — không nằm trong runtime AIOps mặc định.
