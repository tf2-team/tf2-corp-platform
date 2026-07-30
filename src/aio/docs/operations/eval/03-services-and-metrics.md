# 3. Danh sách Service & Metrics ta sẽ lấy

Đây là phần trả lời yêu cầu của team CDO (đo tài nguyên để tối ưu). Tài liệu chi tiết đã có sẵn, không lặp lại nội dung ở đây — xem trực tiếp:

**→ [`docs/operations/cdo-metrics-service-catalog.md`](../cdo-metrics-service-catalog.md)**

Tóm tắt nhanh nội dung file đó:

- **Bảng 1** — 31 service/store trong platform (tier, criticality, mô tả 1 dòng mỗi service).
- **Bảng 2** — 9 metric chuẩn hóa mọi service phải có (request rate, error rate, latency p95/p99, CPU, memory, disk I/O, network I/O, ready pods), scrape interval cố định **1s**.
- **Mục 3** — tên metric Prometheus thật (raw metric name) theo từng nhóm protocol: HTTP (`cart`), gRPC native (`checkout`, `product-catalog`, `ad`), spanmetrics server (10 service), spanmetrics consumer/Kafka (`fraud-detection`, `accounting`), resource metrics (16 service), và các metric riêng theo instance (checkout SLO, postgresql, kafka, otel-collector, valkey-cart).
- **Mục 3g** — 10 service hiện **chưa** có signal RED/Resource chuẩn hoá trong registry AIOps (`load-generator`, `image-provider`, `llm`, `flagd`, `flagd-ui`, `mem0`, `grafana`, `jaeger`, `prometheus`, `opensearch`, `aiops`) — cần một vòng kiểm tra riêng nếu CDO muốn cả nhóm này.

Nguồn dữ liệu gốc: `src/aio/config/prometheus_queries.json`, `src/prometheus/prometheus-config.yaml`, `src/otel-collector/otelcol-config.yml`, `src/aio/docs/operations/topology/platform-topology.graph.json`, `scripts/release_services.json`.
