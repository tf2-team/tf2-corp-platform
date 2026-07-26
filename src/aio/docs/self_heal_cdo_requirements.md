# Self-heal module: yêu cầu dữ liệu và script từ CDO

Tài liệu này là contract tối thiểu để CDO cung cấp dữ liệu cho self-heal module. Mục tiêu không phải viết tay một `incidents_history.json` thật lớn, mà là có một seed nhỏ, sạch, có script validate/generate để AIO engine dùng ổn định.

## Runtime hiện tại cần gì

Self-heal hiện đọc:

- `aio/config/actions.json`: catalog action được phép đề xuất.
- `aio/config/incidents_history.json`: lịch sử incident đã biết.

Engine sẽ:

- Extract feature từ incident + RCA: `affected_services`, `log_signatures`, `trace_signatures`, `metric_ratios`.
- Tìm incident history gần nhất bằng similarity.
- Vote action theo history.
- Chạy guardrail/cost model.
- Trả action dạng `dry-run-recorded` hoặc fallback `page_oncall`.

Vì vậy dữ liệu CDO cung cấp phải ưu tiên đúng schema và đúng semantics, không cần phức tạp hơn.

## Deliverables CDO cần bàn giao

1. `aio/config/incidents_history.seed.json`

   File seed do CDO quản lý, dễ đọc, có thể thêm field mô tả như `description`, `owner`, `source`, `notes`. Các field phụ này chỉ để con người review, không đi vào runtime.

2. `scripts/generate_incident_history.py`

   Script tạo `aio/config/incidents_history.json` từ seed. Nên dùng Python stdlib là đủ. Nếu script chạy trong repo thì có thể import schema Pydantic hiện có để validate.

3. `aio/config/incidents_history.json`

   Output runtime, JSON array đúng schema `IncidentHistoryRecord`.

4. Báo cáo validation ngắn

   Chỉ cần stdout từ `--check`: số record, số action hợp lệ, số scenario theo nhóm lỗi, và danh sách lỗi nếu có.

## Output schema runtime

`incidents_history.json` phải là JSON array. Set trong Python được encode thành JSON array.

```json
[
  {
    "incident_id": "hist-cart-oom-001",
    "affected_services": ["cart"],
    "log_signatures": ["container_oom_detected"],
    "trace_signatures": [],
    "metric_ratios": {
      "cart_memory_usage_bytes": 2.4,
      "cart_oom_events_total": 1.0
    },
    "actions_taken": [
      {
        "action_id": "restart_cart",
        "target": "cart",
        "outcome": "success"
      }
    ]
  }
]
```

Field bắt buộc:

- `incident_id`: unique, stable, không đổi giữa các lần generate.
- `affected_services`: service bị ảnh hưởng hoặc nghi là root cause.
- `log_signatures`: signature ngắn, đã normalize, không chứa PII/secret.
- `trace_signatures`: optional, dùng khi trace có pattern rõ.
- `metric_ratios`: ratio giữa observed và baseline/threshold, không phải raw value.
- `actions_taken`: action từng giải quyết incident tương tự.

`actions_taken[].action_id` phải tồn tại trong `aio/config/actions.json`.

`actions_taken[].outcome` chỉ nên dùng:

- `success`: action xử lý được incident.
- `partial`: giảm ảnh hưởng nhưng chưa xử lý hết.
- `failed`: action không hiệu quả, dùng để engine học giảm vote.

## Semantics của metric_ratios

`metric_ratios` là phần quan trọng nhất vì self-heal đang so sánh bằng log-ratio distance.

Quy ước:

- `1.0`: metric gần baseline/threshold.
- `> 1.0`: metric tăng so với baseline/threshold.
- `< 1.0`: metric giảm so với baseline/threshold.
- Giá trị phải finite và dương.
- Không dùng raw value như bytes, seconds, millicores.

Ví dụ:

```json
{
  "checkout_error_rate_5m": 4.2,
  "checkout_p95_latency_5m": 2.1,
  "payment_request_rate_5m": 0.7
}
```

Tên metric nên khớp signal/runtime hiện có, ví dụ:

- `*_cpu_millicores`
- `*_memory_usage_bytes`
- `*_socket_io_bytes_per_second`
- `*_error_rate_5m`
- `*_p95_latency_5m`
- `*_error_budget_burn_rate_*`
- `*_workload_ready_pods`
- `*_oom_events_total`

## Coverage tối thiểu

Seed ban đầu nên có khoảng 20-50 record. Ít nhưng đúng còn tốt hơn nhiều record synthetic mơ hồ.

CDO nên cover các nhóm sau:

- Memory leak/OOM: memory tăng liên tục, request không tăng tương ứng, có OOM counter hoặc drawdown.
- CPU saturation: CPU tăng theo symptom và action restart/scale/page phù hợp.
- Socket/network saturation: socket IO tăng bất thường, latency/error downstream.
- Error rate: service trả lỗi cao nhưng RCA/action vẫn ưu tiên root metric/action, không lấy error-rate làm root cause duy nhất.
- Latency creep: latency tăng chậm, có service/root dependency rõ.
- Burn rate: SLO burn rate tăng theo service, dùng làm context cho severity/self-heal.
- Ready pods giảm: deployment/pod health issue.
- Dependency failure: ví dụ checkout bị ảnh hưởng bởi payment/cart/product-catalog.
- Protected/unknown service: fallback `page_oncall`.
- Deadlock/lock signature: không đề xuất `increase_pool_size`.

Mỗi runbook/action quan trọng nên có ít nhất 2-3 record đại diện, gồm cả case `success` và case `failed` nếu CDO có dữ liệu thật.

## Case phổ biến cần seed trước

Không đưa `normal` và `busy_normal` vào `incident_history`: hai case đó không cần self-heal. `monitoring_data_missing` cũng nên để detector/alert xử lý bằng fallback, không dùng làm history để vote restart.

Các case dưới đây là nhóm nên seed trước để CDO chỉ cần viết script map sang schema runtime.

| Case | Khi nào dùng | `affected_services` mẫu | `log_signatures` mẫu | `metric_ratios` tối thiểu | Action mong đợi |
| --- | --- | --- | --- | --- | --- |
| `busy_with_oom` | Traffic đang bận nhưng có OOM tail/drawdown | `["cart"]` | `["container_oom_detected", "busy_gate_breakout_oom"]` | `cart_memory_usage_bytes: 2.0`, `cart_oom_events_total: 1.0`, `cart_request_rate_5m: 1.0` | `restart_cart` nếu action tồn tại |
| `fault_oom` | OOM xảy ra dù traffic không tăng | `["cart"]` | `["container_oom_detected"]` | `cart_memory_usage_bytes: 2.2`, `cart_oom_events_total: 1.0` | restart service bị OOM |
| `fault_memory_pressure` | Memory tăng bất thường nhưng chưa có OOM | `["cart"]` | `["memory_pressure"]` | `cart_memory_usage_bytes: 1.8`, `cart_request_rate_5m: 1.0` | restart hoặc `page_oncall` nếu chưa đủ tự tin |
| `busy_with_error` | Busy system nhưng error-rate tăng ở tail | `["checkout"]` | `["busy_gate_breakout_error_rate"]` | `checkout_error_rate_5m: 3.0`, `checkout_request_rate_5m: 1.8` | restart/fallback theo RCA root metric, không ưu tiên error-rate làm root cause |
| `fault_error_rate` | Error-rate tăng, không cần traffic tăng | `["checkout"]` | `["service_error_rate_high"]` | `checkout_error_rate_5m: 4.0`, `checkout_request_rate_5m: 1.0` | restart service nếu có action an toàn |
| `busy_with_latency` | Busy system nhưng P95/P99 breach rõ | `["checkout"]` | `["busy_gate_breakout_latency_slo"]` | `checkout_p95_latency_5m: 2.5`, `checkout_error_budget_burn_rate_1h: 2.0` | restart/fallback theo RCA root metric |
| `fault_latency` | Latency drift/SLO breach không phải busy-normal | `["frontend"]` | `["latency_slo_breached"]` | `frontend_p95_latency_5m: 2.2`, `frontend_request_rate_5m: 1.0` | restart/fallback theo service |
| `fault_cpu_saturation` | CPU tăng bất thường, không giải thích được bằng traffic | `["product-catalog"]` | `["cpu_saturation"]` | `product_catalog_cpu_millicores: 2.0`, `product_catalog_request_rate_5m: 1.0` | restart service nếu action tồn tại |
| `fault_socket_io` | Socket/network IO tăng bất thường | `["frontend-proxy"]` | `["socket_io_saturation"]` | `frontend_proxy_socket_io_bytes_per_second: 2.0`, `frontend_proxy_request_rate_5m: 1.0` | restart hoặc `page_oncall` |
| `busy_with_pod_failure` | Busy system nhưng ready pods/ready ratio giảm | `["product-catalog"]` | `["ready_pods_degraded", "busy_gate_breakout_pod_failure"]` | `product_catalog_workload_ready_pods: 0.5`, `product_catalog_request_rate_5m: 1.5` | restart service |
| `fault_pod_availability` | Ready pod count/ratio giảm độc lập | `["frontend"]` | `["ready_pods_degraded"]` | `frontend_workload_ready_pods: 0.5` | restart service |
| `busy_with_dependency_failure` | Service bận vì dependency lỗi | `["checkout", "payment"]` | `["dependency_signal_breached"]` | `checkout_payment_error_rate_5m: 3.0`, `payment_error_rate_5m: 3.0` | action trên dependency, ví dụ `restart_payment` |
| `fault_dependency` | Dependency breach không cần traffic tăng | `["checkout", "payment"]` | `["dependency_signal_breached"]` | `checkout_payment_error_rate_5m: 2.5`, `payment_error_rate_5m: 2.0` | action trên dependency |
| `fault_database` | PostgreSQL/pool bất thường | `["checkout", "postgresql"]` | `["database_pool_saturation"]` | `checkout_postgresql_error_rate_5m: 2.5`, `postgresql_connections: 1.8` | `page_data_oncall` hoặc `page_oncall` |

Các case như `fault_kafka_lag`, `fault_cache_memory`, `fault_otel_backpressure`, `fault_disk_io` chỉ nên seed khi config collector đã có signal tương ứng. Nếu chưa có metric ổn định thì để backlog, không nhồi history giả.

## Seed template CDO nên dùng

Seed có thể giữ thêm `case` và `description` để review. Script sẽ bỏ field phụ khi generate `incidents_history.json`.

```json
[
  {
    "case": "busy_with_oom",
    "description": "cart busy nhưng memory leak dẫn tới OOM, gate phải breakout",
    "incident_id": "seed-cart-busy-oom-001",
    "affected_services": ["cart"],
    "log_signatures": ["container_oom_detected", "busy_gate_breakout_oom"],
    "trace_signatures": [],
    "metric_ratios": {
      "cart_memory_usage_bytes": 2.3,
      "cart_oom_events_total": 1.0,
      "cart_request_rate_5m": 1.2
    },
    "actions_taken": [
      {
        "action_id": "restart_cart",
        "target": "cart",
        "outcome": "success"
      }
    ]
  },
  {
    "case": "fault_database",
    "description": "checkout lỗi do PostgreSQL/pool bất thường, không auto restart checkout",
    "incident_id": "seed-checkout-db-pool-001",
    "affected_services": ["checkout", "postgresql"],
    "log_signatures": ["database_pool_saturation"],
    "trace_signatures": ["checkout->postgresql"],
    "metric_ratios": {
      "checkout_postgresql_error_rate_5m": 2.8,
      "postgresql_connections": 1.9
    },
    "actions_taken": [
      {
        "action_id": "page_data_oncall",
        "target": "data-platform-oncall",
        "outcome": "success"
      }
    ]
  }
]
```

## Yêu cầu script generate/validate

Script tối thiểu:

```bash
python scripts/generate_incident_history.py \
  --seed aio/config/incidents_history.seed.json \
  --actions aio/config/actions.json \
  --output aio/config/incidents_history.json
```

Validate only:

```bash
python scripts/generate_incident_history.py \
  --seed aio/config/incidents_history.seed.json \
  --actions aio/config/actions.json \
  --check
```

Script phải kiểm tra:

- `incident_id` unique.
- `affected_services` không rỗng.
- `metric_ratios` toàn số finite, dương.
- `actions_taken` không rỗng với record dùng để self-heal.
- `action_id` tồn tại trong `actions.json`.
- `target` trong history khớp target của action catalog.
- `outcome` thuộc `success`, `partial`, `failed`.
- Không duplicate record cùng service + signatures + metric ratios.
- Không chứa secret, token, email cá nhân, raw customer data trong signatures.

Script nên output deterministic:

- Sort theo `incident_id`.
- JSON pretty indent 2.
- UTF-8.
- Exit code khác 0 nếu validation fail.

## Guardrail cần phản ánh trong seed

Không seed những action mà policy hiện sẽ chặn, trừ khi mục đích là test negative case.

Các case nên fallback/page:

- Không có history đủ gần.
- Service/action target không nằm trong `affected_services`.
- Action blast radius lớn nhưng confidence thấp.
- Deadlock/lock signature nhưng action là `increase_pool_size`.
- Target là service protected/stateful mà không có runbook rollback/verification rõ.

## Acceptance criteria

CDO bàn giao được coi là đạt khi:

- `aio/config/incidents_history.json` load được bằng `IncidentHistoryStore.load()`.
- Mọi `action_id` trong history tồn tại trong `aio/config/actions.json`.
- Có ít nhất 20 record seed sạch, không PII/secret.
- Có coverage cho memory/OOM, CPU, socket, latency, error-rate, burn-rate, ready-pods, dependency failure.
- Có ít nhất 3 negative/guardrail records dẫn tới fallback/page.
- Script `--check` chạy pass và in summary.
- Self-heal smoke test với 3 incident mẫu trả đúng nhóm action mong đợi hoặc fallback đúng.

## Điều không nên làm

- Không generate hàng nghìn incident synthetic chỉ để tăng số lượng.
- Không dùng LLM tự bịa incident rồi đưa thẳng vào runtime.
- Không đưa raw log dài, stacktrace đầy đủ, token, email, customer id vào signature.
- Không encode raw metric value vào `metric_ratios`.
- Không tạo action history cho action chưa có trong `actions.json`.

Nếu dùng LLM, chỉ dùng để draft seed ban đầu. CDO vẫn phải review, normalize và validate trước khi bàn giao.

## Ownership

- CDO owns: seed incident, action mapping nghiệp vụ, script generate/validate, data quality.
- AIO owns: schema runtime, similarity scoring, guardrail, decision engine, dry-run/execution policy.
