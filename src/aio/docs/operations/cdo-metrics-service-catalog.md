# CDO Handoff — Service & Metrics Catalog

**Mục đích:** liệt kê toàn bộ service và toàn bộ metric cần lấy để CDO đổ dữ liệu vào Prometheus phục vụ tối ưu tài nguyên.

**Nguồn dữ liệu :**
- `tf2-corp-platform/src/aio/docs/operations/topology/platform-topology.graph.json` — danh sách service, tier, criticality
- `tf2-corp-platform/docker-compose.yml`, `tf2-corp-platform/scripts/release_services.json` — danh sách image/service triển khai thực tế
- `tf2-corp-platform/src/aio/config/prometheus_queries.json` — toàn bộ PromQL template + service_groups (nguồn chuẩn cho mọi metric AIOps đang dùng)
- `tf2-corp-platform/src/prometheus/prometheus-config.yaml` — `scrape_interval`
- `tf2-corp-platform/src/otel-collector/otelcol-config.yml` — receiver/collection interval, spanmetrics flush interval

---

## 1. Danh sách Service (tất cả service)

| STT | Service | Nhóm (tier) | Criticality | Mô tả ngắn |
|---|---|---|---|---|
| 1 | frontend-proxy | edge | critical | Envoy proxy, cổng vào duy nhất của storefront |
| 2 | frontend | web | critical | Storefront (Next.js) |
| 3 | image-provider | asset | medium | Serve ảnh sản phẩm (nginx) |
| 4 | product-catalog | api | critical | Danh mục / tìm kiếm sản phẩm (gRPC + PostgreSQL) |
| 5 | product-reviews | ai | high | Đánh giá sản phẩm + AI review assistant |
| 6 | llm | ai | medium | LLM nội bộ phục vụ product-reviews |
| 7 | recommendation | ml | medium | Gợi ý sản phẩm |
| 8 | cart | api | critical | Giỏ hàng (Valkey/Redis) |
| 9 | checkout | api | critical | Điều phối đặt hàng (đường revenue chính) |
| 10 | currency | api | high | Quy đổi tiền tệ |
| 11 | shipping | api | high | Tính phí / vận đơn |
| 12 | quote | api | high | Báo giá vận chuyển cho shipping |
| 13 | payment | api | critical | Xử lý thanh toán |
| 14 | email | api | low | Gửi email xác nhận đơn hàng |
| 15 | accounting | worker | high | Kafka consumer – ghi sổ kế toán đơn hàng |
| 16 | fraud-detection | worker | high | Kafka consumer – phát hiện gian lận |
| 17 | ad | api | low | Quảng cáo theo context-key |
| 18 | shopping-copilot | ai | medium | AI shopping assistant (Bedrock/tools) |
| 19 | mem0 | support | low | Bộ nhớ/context cho shopping-copilot |
| 20 | flagd | control | critical | Feature-flag engine (đường protected, AIOps không được đụng) |
| 21 | flagd-ui | control | medium | UI quản trị feature flag |
| 22 | load-generator | traffic | low | Sinh traffic giả lập (Locust) |
| 23 | otel-collector | observability | high | Thu thập & fan-out OTLP → Prometheus/Jaeger/OpenSearch |
| 24 | grafana | observability | high | Dashboard + alerting |
| 25 | aiops (aiops-runtime) | aiops | high | Runtime phát hiện bất thường / RCA |
| 26 | prometheus | store | high | TSDB lưu metrics |
| 27 | jaeger | store | medium | Lưu trace |
| 28 | opensearch | store | medium | Lưu log |
| 29 | kafka | store | high | Message broker (async order) |
| 30 | postgresql | store | critical | DB dùng chung (catalog, reviews, accounting) — managed bên ngoài |
| 31 | valkey-cart | store | critical | Redis-compatible store cho cart — managed bên ngoài |

---

## 2. Danh sách Metric chuẩn hóa (mọi service đều lấy đủ các metric này)

Không cần điền tham số bucket (`le`) — chỉ cần tên metric + đơn vị để đổ vào Prometheus. Scrape interval = **1s** cho toàn bộ.

| STT | Metric | Loại | Đơn vị | Mô tả | Scrape interval |
|---|---|---|---|---|---|
| 1 | Request rate | Counter | request/s | Tổng lượng request/message xử lý mỗi giây | 1s |
| 2 | Error rate | Counter | % (ratio lỗi/tổng) | Tỷ lệ request lỗi (5xx / gRPC status ≠ 0 / span error) | 1s |
| 3 | Latency p95 | Histogram | ms | Độ trễ p95 xử lý request | 1s |
| 4 | Latency p99 | Histogram | ms | Độ trễ p99 xử lý request | 1s |
| 5 | CPU usage | Gauge | millicores | CPU đang sử dụng theo pod/container | 1s |
| 6 | Memory usage | Gauge | bytes | RAM (working set) đang sử dụng theo pod/container | 1s |
| 7 | Disk I/O | Counter | bytes/s | Tốc độ đọc/ghi đĩa | 1s |
| 8 | Network I/O | Counter | bytes/s | Tốc độ nhận/gửi qua network (receive/transmit) | 1s |
| 9 | Ready pods | Gauge | count / ratio | Số pod đang ready / tỷ lệ ready trên tổng replica | 1s |

---

## 3. Tên metric PromQL thực tế theo từng service

Tên metric gốc khác nhau theo **protocol nhóm** của từng service. Dưới đây là tên metric raw (dùng để cấu hình scrape/remote-write allowlist), không phải câu PromQL truy vấn đầy đủ.

### 3a. Nhóm HTTP (.NET) — `cart`

| Metric chuẩn hóa | Tên metric Prometheus (raw) |
|---|---|
| Request rate | `http_server_request_duration_seconds_count` |
| Latency p95 / p99 | `http_server_request_duration_seconds_bucket` |
| Error rate | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}` |

### 3b. Nhóm gRPC native — `checkout`, `product-catalog`, `ad`

| Metric chuẩn hóa | Tên metric Prometheus (raw) |
|---|---|
| Request rate | `rpc_server_duration_milliseconds_count` |
| Latency p95 / p99 | `rpc_server_duration_milliseconds_bucket` |
| Error rate | `rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}` |

### 3c. Nhóm Server spanmetrics — `frontend-proxy`, `frontend`, `payment`, `product-reviews`, `recommendation`, `currency`, `shipping`, `email`, `quote`, `shopping-copilot`

| Metric chuẩn hóa | Tên metric Prometheus (raw) |
|---|---|
| Request rate | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_SERVER"}` |
| Latency p95 / p99 | `traces_span_metrics_duration_milliseconds_bucket{span_kind="SPAN_KIND_SERVER"}` |
| Error rate | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}` |

### 3d. Nhóm Kafka consumer spanmetrics — `fraud-detection`, `accounting`

| Metric chuẩn hóa | Tên metric Prometheus (raw) |
|---|---|
| Request rate | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_CONSUMER"}` |
| Latency p95 / p99 | `traces_span_metrics_duration_milliseconds_bucket{span_kind="SPAN_KIND_CONSUMER"}` |
| Error rate | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_CONSUMER", status_code="STATUS_CODE_ERROR"}` |

### 3e. Nhóm Resource (CPU/Memory/Disk/Network/Ready) — 16 service: `checkout`, `payment`, `frontend-proxy`, `frontend`, `product-catalog`, `product-reviews`, `recommendation`, `ad`, `currency`, `cart`, `shipping`, `email`, `quote`, `fraud-detection`, `accounting`, `shopping-copilot`

| Metric chuẩn hóa | Tên metric Prometheus (raw) |
|---|---|
| CPU usage | `container_cpu_usage_seconds_total` (fallback: `container_cpu_usage_total`, `k8s_pod_cpu_usage`) |
| Memory usage | `container_memory_working_set_bytes` (fallback: `container_memory_usage_bytes`, `k8s_pod_memory_usage`) |
| Disk I/O | `container_fs_reads_bytes_total`, `container_fs_writes_bytes_total` (fallback: `container_blockio_io_service_bytes_recursive`) |
| Network I/O | `container_network_receive_bytes_total`, `container_network_transmit_bytes_total` (fallback: `container_network_io_usage_rx_bytes`, `container_network_io_usage_tx_bytes`) |
| Ready pods | `k8s_pod_ready` (fallback: `kube_pod_status_ready`) |
| Ready ratio | tính từ `k8s_pod_ready` / tổng pod (fallback: `kube_pod_status_ready`) |

### 3f. Metric riêng biệt theo instance (không thuộc nhóm chung)

| Service | Metric | Tên metric Prometheus (raw) | Mô tả |
|---|---|---|---|
| checkout | SLO bad ratio (24h, method `PlaceOrder`) | `rpc_server_duration_milliseconds_count{rpc_method="PlaceOrder"}` | Tỷ lệ request lỗi 24h cho SLO chính thức |
| checkout | Error budget burn rate (24h) | tính từ `rpc_server_duration_milliseconds_count` / error_budget=0.01 | Tốc độ đốt error budget |
| checkout | Dependency error rate → payment | `traces_span_metrics_calls_total{span_kind="SPAN_KIND_CLIENT", span_name=~".*PaymentService/Charge"}` | Lỗi khi checkout gọi payment |
| postgresql | Active connections | `db_client_connection_count{db_client_connection_state="used"}` | Số connection đang dùng |
| product-catalog | DB pool utilization | `db_client_connection_count` / `db_client_connection_max` | % pool connection đã dùng |
| kafka | Consumer lag | `kafka_consumer_records_lag` | Độ trễ consumer Kafka |
| otel-collector | Exporter queue saturation | `otelcol_exporter_queue_size` / `otelcol_exporter_queue_capacity` | % hàng đợi export đã đầy |
| valkey-cart | Memory used | `redis_memory_used_bytes` | RAM Redis/Valkey đang dùng |

### 3g. Service không nằm trong registry AIOps (vẫn phát metric qua OTel/host/docker receiver, chưa gắn thành AIOps signal)

`load-generator`, `image-provider`, `llm`, `flagd`, `flagd-ui`, `mem0`, `grafana`, `jaeger`, `prometheus`, `opensearch`, `aiops` — các service này vẫn có metric hạ tầng (CPU/Memory/network qua `hostmetrics`/`docker_stats` receiver) nhưng chưa được đăng ký thành signal RED/Resource chuẩn trong `prometheus_queries.json`. Nếu CDO cần cả nhóm này, nên lấy cùng bộ 9 metric ở Bảng 2 qua raw container/host metric tương ứng (`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, v.v., filter theo tên container).

---

## 4. Metric bị thiếu / chưa được dùng — soát lại theo yêu cầu anh Huy (25/07)

Đối chiếu trực tiếp `prometheus_queries.json` ↔ `runtime.json` ↔ code (`aiops/anomaly/v001.py`, `aiops/rca/engine.py`, `aiops/config/runtime.py`) để trả lời 2 câu: (1) docs này thiếu gì, (2) `runtime.json` thiếu signal/detector cho metric gì đã có/đã đề cập.

### 4a. `oom_kill` — **thiếu thật, ở tận gốc `prometheus_queries.json`**

- Code (`v001.py`, `rca/engine.py`) có hẳn hàm `_is_oom_metric()` coi bất kỳ metric có chữ `"oom"` là **hard-failure signal** (ngang hàng với error_rate, ready_pods giảm) — tức engine được thiết kế sẵn để xử lý tín hiệu OOM.
- Test `tests/test_v001_anomaly_rca.py::test_oom_signal_is_kept` dùng mock signal `checkout_oom_kills` để test hành vi này.
- **Nhưng `prometheus_queries.json` không có bất kỳ template/instance nào tạo ra signal `*_oom_kills`** — nghĩa là ngoài đời không có query nào thật sự thu thập OOM kill count. Đây là **gap thật trong config**, không phải chỉ thiếu trong docs.
- Muốn dùng được, cần thêm 1 template mới, ví dụ dựa trên `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` hoặc `container_oom_events_total`, rồi mới khai báo signal `<service>_oom_kills` + detector tương ứng trong `runtime.json`.

### 4b. `burn_rate` — **có trong config nhưng chỉ 1 service (checkout), chưa mở rộng**

- Đã có template `slo.grpc.method_burn_rate` (generic theo `$service`/`$method`) và **1 instance duy nhất**: `checkout.error_budget_burn_rate.24h` → signal `checkout_error_budget_burn_rate_24h` → detector `ops01_checkout_slo_burn_rate` (đang `enabled: true`).
- Đã liệt kê ở Mục 3f phía trên, nhưng dễ bị bỏ sót vì nằm chung bảng "metric riêng biệt" — tách riêng ở đây theo yêu cầu.
- **Chưa có burn-rate cho bất kỳ service/method nào khác** (cart, payment...) dù template đã generic hóa sẵn — nếu CDO/team cần burn-rate cho flow khác thì chỉ cần thêm instance mới trong `prometheus_queries.json`, không cần code mới.

### 4c. Signal đã có trong `prometheus_queries.json` nhưng **không có detector nào dùng tới** (thu thập về nhưng chưa ai alert)

Auto-detector-generation (`aiops/config/runtime.py: _expand_detector_signal_groups`) **chỉ** tự sinh detector cho 2 loại metric: `error_rate_5m` và `p95/p99_latency_5m`. Mọi signal khác phải khai báo tay trong `runtime.json` — và các signal sau **chưa được khai báo tay**, nên tồn tại nhưng không kích hoạt cảnh báo:

| Signal (đã có trong `prometheus_queries.json`) | Áp dụng cho | Trạng thái detector |
| --- | --- | --- |
| `*_memory_usage_bytes` | 16 service resource-group | Không có detector nào |
| `*_disk_io_bytes_per_second` | 16 service resource-group | Không có detector nào |
| `*_socket_io_bytes_per_second` | 16 service resource-group | Không có detector nào |
| `*_workload_ready_pods` / `*_workload_ready_ratio` | 16 service resource-group | Không có detector nào |
| `*_cpu_millicores` | 16 service resource-group | Chỉ `product-catalog` có detector (`ops06_product_catalog_cpu`) — và đang **`enabled: false`** |
| `postgresql_active_connections` | postgresql | Không có detector |
| `product_catalog_db_pool_utilization` | product-catalog | Không có detector |
| `kafka_consumer_lag` | kafka | Không có detector |
| `otel_collector_exporter_queue_saturation` | otel-collector | Không có detector |
| `valkey_cart_memory_used_bytes` | valkey-cart | Không có detector |

→ **Đây là nhóm quan trọng nhất với CDO**: toàn bộ metric tài nguyên (CPU/Memory/Disk/Network/Ready) đang **được thu thập (signal tồn tại) nhưng không được AIOps dùng để cảnh báo** — nghĩa là dữ liệu này hoàn toàn "sạch" và sẵn để CDO lấy riêng cho mục đích tối ưu tài nguyên, không lo xung đột/trùng với logic alert hiện tại của AIOps.

### 4d. Threshold "mồ côi" trong `hyperparameters.json`

`hyperparameters.json → detectors.thresholds` có khai `auto_llm_error_rate: 0.05` và `latency_slo_overrides.llm: 5.0`, nhưng `llm` **không thuộc bất kỳ `service_group` nào** trong `prometheus_queries.json` → không có signal `llm_error_rate_5m`/`llm_p95_latency_5m` nào được tạo ra để auto-detector dùng threshold này. Threshold này hiện không có tác dụng (khớp với việc `llm` cũng nằm trong danh sách 10 service "chưa có RED signal" ở Mục 3g).

---

## 5. Lưu ý cấu hình scrape / remote-write

- **Scrape/collection interval: `1s`** — đã set thật xuyên suốt pipeline hiện tại: `prometheus-config.yaml` (`scrape_interval: 1s`, `evaluation_interval: 1s`), `otelcol-config.yml` (mọi receiver `collection_interval: 1s`, spanmetrics `metrics_flush_interval: 1s`), app SDK (`OTEL_METRIC_EXPORT_INTERVAL=1000`).
- **Không cần tham số bucket (`le`)** — CDO chỉ cần lấy metric thô theo tên ở Mục 3, không cần dựng lại câu `histogram_quantile(...)`.
- Toàn bộ tên metric ở Mục 3 lấy trực tiếp từ template `promql` trong `prometheus_queries.json`, đã bỏ phần hàm tính (`histogram_quantile`, `rate`, `sum`, `clamp_min`...) — chỉ giữ lại tên metric gốc + label lọc quan trọng.
