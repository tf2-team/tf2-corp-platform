# [Nội bộ] Gap giữa signal đã thu thập và detector đang dùng

**Không gửi file này cho CDO** — đây là ghi chú nội bộ AIOps, trả lời câu hỏi soát lại của anh Huy Phan (25/07): "vào `aio/config` xem thử `prometheus_queries.json` xem docs còn thiếu gì không". Danh sách service/metric gửi CDO nằm ở `cdo-metrics-service-catalog.md`, không có nội dung dưới đây.

Đối chiếu `prometheus_queries.json` ↔ `runtime.json` ↔ code (`aiops/anomaly/v001.py`, `aiops/rca/engine.py`, `aiops/config/runtime.py`).

## 1. `oom_kill` — thiếu ở gốc `prometheus_queries.json`

Code (`v001.py`, `rca/engine.py`) có sẵn `_is_oom_metric()` coi metric chứa `"oom"` là hard-failure signal, và test `test_v001_anomaly_rca.py::test_oom_signal_is_kept` dùng mock `checkout_oom_kills`. Nhưng `prometheus_queries.json` chưa có template/instance nào tạo signal `*_oom_kills` thật. Muốn dùng được: thêm template dựa trên `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` hoặc `container_oom_events_total`, rồi khai signal + detector trong `runtime.json`.

## 2. `burn_rate` — chỉ có ở checkout

Template `slo.grpc.method_burn_rate` đã generic hóa theo `$service`/`$method`, nhưng chỉ có 1 instance (`checkout.error_budget_burn_rate.24h`). Muốn thêm burn-rate cho cart/payment/flow khác chỉ cần thêm instance mới, không cần code mới.

## 3. Signal có nhưng không detector nào dùng

Auto-detector-generation (`_expand_detector_signal_groups`) chỉ tự sinh detector cho `error_rate_5m` và `p95/p99_latency_5m`. Các signal sau có trong `prometheus_queries.json` nhưng chưa khai detector tay:

| Signal | Áp dụng cho | Trạng thái |
| --- | --- | --- |
| `*_memory_usage_bytes` | 16 service resource-group | Không có detector |
| `*_disk_io_bytes_per_second` | 16 service resource-group | Không có detector |
| `*_socket_io_bytes_per_second` | 16 service resource-group | Không có detector |
| `*_workload_ready_pods` / `*_workload_ready_ratio` | 16 service resource-group | Không có detector |
| `*_cpu_millicores` | 16 service resource-group | Chỉ `product-catalog` (`ops06_product_catalog_cpu`), đang `enabled: false` |
| `postgresql_active_connections` | postgresql | Không có detector |
| `product_catalog_db_pool_utilization` | product-catalog | Không có detector |
| `kafka_consumer_lag` | kafka | Không có detector |
| `otel_collector_exporter_queue_saturation` | otel-collector | Không có detector |
| `valkey_cart_memory_used_bytes` | valkey-cart | Không có detector |

Ý nghĩa: nhóm resource này thu thập về nhưng chưa dùng để alert — nên đây cũng là lý do CDO lấy nhóm này thoải mái, không đụng logic alert hiện tại của AIOps.

## 4. Threshold mồ côi

`hyperparameters.json` khai `auto_llm_error_rate` và `latency_slo_overrides.llm`, nhưng `llm` không thuộc `service_group` nào trong `prometheus_queries.json` nên không có signal để threshold này dùng — hiện không có tác dụng.
