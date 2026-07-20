# Thiết kế Prometheus Query Registry và Collector

## Mục tiêu

Thiết kế này giải quyết ba vấn đề chính:

1. PromQL chỉ có một nguồn chuẩn, không còn chia giữa `runtime.json` và mã Python.
2. Mỗi dòng metric range cách nhau đúng 1 giây; query không có series trả về `0` theo policy thống nhất của registry.
3. Có thể thêm hoặc áp dụng lại query bằng JSON mà không sửa pipeline Python.

Các file có trách nhiệm riêng:

- `config/runtime.json`: topology, detector, policy và RCA.
- `config/prometheus_queries.json`: collection profile, PromQL template, service group và query instance.
- `config/prometheus_e2e.json`: chỉ chọn các `query_id` dùng cho E2E, không sao chép PromQL.
- `config/hyperparameters.json`: tham số detector/model, không chứa cấu hình collection của Prometheus.

Khi nạp runtime, pipeline compile registry thành `prometheus_query_specs`, signal definitions và PromQL cụ thể. Registry kiểm tra template/profile không tồn tại, query ID hoặc signal ID trùng, service không có trong topology, và placeholder chưa được render.

## Vì sao mỗi loại service dùng query khác nhau

Không nên dùng một metric chung cho mọi protocol. Metric và label được chọn theo telemetry thực tế của platform:

| Nhóm | Latency | Error ratio và traffic | Lý do |
|---|---|---|---|
| HTTP application (`frontend`, `cart`, `quote`) | `http_server_request_duration_seconds_bucket` | `http_server_request_duration_seconds_count`, HTTP 5xx | Metric server HTTP có đơn vị giây và status code chuẩn. |
| gRPC application | `rpc_server_duration_milliseconds_bucket` | `rpc_server_duration_milliseconds_count`, gRPC code khác `0` | Checkout và các dependency chính là gRPC; latency được đổi từ milliseconds sang seconds. |
| `frontend-proxy` | `traces_span_metrics_duration_milliseconds_bucket`, `span_kind=SERVER` | `traces_span_metrics_calls_total` | Proxy Envoy không được giả định có metric HTTP SDK giống application. Filter `SERVER` tránh trộn client/internal spans. |
| Kafka consumer (`fraud-detection`, `accounting`) | spanmetrics, `span_kind=CONSUMER` | spanmetrics calls/error | Đo đúng thời gian xử lý message và lỗi consumer, không trộn request server. |

Mỗi nhóm RED có p95, p99, error ratio và request/message rate. p99 được giữ riêng vì tail latency có thể tăng mạnh trong khi p95 vẫn bình thường.

Các tín hiệu saturation/resource bổ sung gồm CPU millicores, memory, disk I/O, network I/O, ready pod/ratio, PostgreSQL backend connections, DB client-pool utilization, Kafka consumer lag, OTel exporter queue saturation và Valkey memory. Metric phụ thuộc deployment và không chắc luôn được export có `required_for_monitoring: false`; thiếu chúng không được tự động mở incident monitoring-loss.

## Quy tắc viết PromQL

### Phân biệt zero và no-data

Registry khai báo policy mặc định trong `result_defaults.on_empty`. Giá trị `zero` làm compiler bọc PromQL bằng `or on() vector(0)`, vì vậy query hợp lệ nhưng không có series vẫn trả về đúng một series giá trị `0`. Template đặc thù có thể đặt `result.on_empty: "missing"` để ghi đè khi no-data phải được giữ lại.

Policy zero chỉ áp dụng cho kết quả PromQL rỗng. Timeout, lỗi HTTP, response sai định dạng, quá cardinality và NaN/Inf vẫn không được đổi thành zero; collector tiếp tục trả `MISSING` hoặc `INVALID` tương ứng.

Với error ratio, numerator được viết theo mẫu:

```promql
errors or 0 * total
```

Mẫu này chỉ tạo zero-error khi series tổng traffic thực sự tồn tại. Toàn bộ ratio tiếp tục được khóa bởi:

```promql
and on() (total > 0)
```

Vì vậy:

- Có traffic và không có error series: kết quả là `0` hợp lệ.
- Không có traffic hoặc expression không tìm thấy series: fallback mặc định trả `0`.
- Prometheus không truy cập được hoặc từ chối query: collector đánh dấu `MISSING`, không fallback.

Mẫu ratio dùng epsilon `0.000000001`, không dùng `clamp_min(..., 1)` cho rate/increase. Ép denominator thành 1 làm giảm sai error ratio của service có lưu lượng dưới 1 request/giây hoặc counter bị Prometheus extrapolate.

### Aggregate cardinality

Query collector phải aggregate về đúng một series. Contract mặc định là `max_series: 1`. Nếu Prometheus trả nhiều series, collector trả `INVALID/CardinalityExceeded`; collector không còn âm thầm lấy `result[0]`.

### Rolling window và cadence

`rate(...[5m])` vẫn đúng khi cần một dòng mỗi giây. Mỗi dòng là kết quả của cửa sổ rolling 5 phút tại thời điểm tương ứng. Không đổi thành `rate(...[1s])`, vì counter thưa sẽ gây nhiễu hoặc không đủ sample.

## Contract 1 giây

Profile `one_second` quy định:

```json
{
  "step_seconds": 1,
  "lookback_seconds": 6200,
  "detector_bucket_seconds": 60,
  "required_source_resolution_seconds": 1,
  "incremental": true,
  "max_concurrency": 8
}
```

Cadence phải nhất quán từ nguồn đến collector:

- Application SDK: `OTEL_METRIC_EXPORT_INTERVAL=1000` ms trong Compose.
- OTel receivers và spanmetrics flush: 1 giây.
- Prometheus scrape/evaluation interval: 1 giây.
- Grafana Prometheus datasource minimum interval: 1 giây.
- Collector `/query_range`: `step=1`.

Collector kiểm tra timestamp sau khi sort và loại duplicate. Bất kỳ gap nào khác 1 giây trả về `INVALID/UnexpectedGap`; lỗi request hoặc raw response rỗng bất thường sau khi đã áp dụng zero fallback trả về `MISSING`. Giá trị NaN/Inf trả về `INVALID`.

`lookback_seconds=6200` cung cấp khoảng 104 bucket một phút cho anomaly/RCA. Pipeline giữ raw 1 giây ở collector/evidence nhưng lấy sample cuối của mỗi bucket 60 giây trước khi chạy model, nhờ đó không làm thay đổi seasonal/min-points đã được hiệu chỉnh theo phút.

Sau lần bootstrap, collector cache theo `query_id` và chỉ tải đoạn mới từ timestamp cuối cùng. Tối đa 8 query chạy đồng thời để registry lớn không làm chu kỳ collection bị kéo dài tuyến tính.

## Cách thêm query

### Áp dụng template cho nhiều service

Thêm template vào `templates`, sau đó tham chiếu nó trong `service_groups`:

```json
{
  "services": ["service-a", "service-b"],
  "template_ids": ["red.grpc.p95_latency", "red.grpc.error_ratio"]
}
```

Các placeholder chuẩn là `$service`, `${service_id}` và `$flow`; group có thể bổ sung `parameters`.

### Query đặc thù

Query dependency, database hoặc SLO nên dùng `instances`:

```json
{
  "query_id": "checkout.payment_error_rate.5m",
  "signal_id": "checkout_payment_error_rate_5m",
  "template_id": "dependency.grpc_client.error_ratio",
  "service": "checkout",
  "parameters": {
    "dependency": "payment",
    "dependency_id": "payment"
  },
  "labels": {"dependency": "payment"}
}
```

Dependency checkout-to-payment dùng `rpc_client_duration_milliseconds_count`, không dùng HTTP server metric. Điều này đo lỗi tại đúng cạnh gọi từ checkout sang payment thay vì lỗi tổng của một service khác.

## Checklist trước khi merge template mới

1. Xác nhận metric name và label bằng Prometheus discovery trên môi trường đích.
2. Xác nhận protocol và `span_kind`; không trộn server, client, consumer và internal.
3. Xác nhận unit nguồn và unit output, nhất là milliseconds/seconds và bytes/bytes-per-second.
4. Aggregate về một series hoặc khai báo `max_series` có chủ đích.
5. Kiểm tra ba trường hợp: healthy zero, no traffic/no-data và exporter failure.
6. Với range query, kiểm tra mọi timestamp cách nhau đúng 1 giây.
7. Chỉ đặt `required_for_monitoring: true` khi metric chắc chắn tồn tại trên mọi deployment được hỗ trợ.
8. Thêm query ID vào `prometheus_e2e.json` nếu query cần nằm trong acceptance run.

Sau khi đổi cadence, cần restart/redeploy application, OTel Collector, Prometheus và Grafana để cấu hình 1 giây có hiệu lực. `query_range step=1` một mình không thể biến source 60 giây thành telemetry thật 1 giây.
