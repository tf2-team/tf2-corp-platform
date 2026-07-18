# AI MANDATE #7a — Detection · Implement + Phân tích

**Team:** AIO4 (AIOps sub-team) · **Task Force:** TF2  
**Directive:** #7 — Sự cố phải tự lộ ra — dựng mắt cho hệ thống  
**Chặng:** #7a — implement + phân tích  
**Hạn nộp:** Thứ Bảy 18/07/2026  
**Tác giả:** AIO4 AIOps Team  
**Label:** `ai-mandate`, `m7`

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Link PR / Commit — Bằng chứng implement](#2-link-pr--commit--bằng-chứng-implement)
3. [Phân tích 3 Metrics](#3-phân-tích-3-metrics)
   - [Metric 1: Checkout p95 Latency](#metric-1-checkout-service--p95-latency)
   - [Metric 2: Cart HTTP 5xx Error Rate](#metric-2-cart-service--http-5xx-error-rate)
   - [Metric 3: Product Catalog CPU Saturation](#metric-3-product-catalog-service--cpu-utilization-saturation)
4. [Tổng hợp phương pháp phát hiện](#4-tổng-hợp-phương-pháp-phát-hiện)
5. [ADR ký tên](#5-adr-ký-tên)
6. [Cách chạy lại (Repro)](#6-cách-chạy-lại-repro)
7. [Việc cần làm cho #7b](#7-việc-cần-làm-cho-7b)

---

## 1. Tổng quan

### Bối cảnh hệ thống

TechX Corp Platform là một e-commerce microservice trên Kubernetes, gồm ~18 service polyglot. Luồng chính: **Browse → Cart → Checkout → Payment**. Mọi request vào qua `frontend-proxy` (Envoy) ở port 8080. Telemetry đầy đủ qua OpenTelemetry → Prometheus (metrics), Jaeger (traces), OpenSearch (logs).

Tham khảo:
- Kiến trúc: `phase3/onboarding/ARCHITECTURE.md`
- SLO: `phase3/onboarding/SLO.md`
- Lịch sử sự cố: `phase3/onboarding/INCIDENT_HISTORY.md`
- Topology: `docs/aiops/topology/platform-topology.graph.json`

### SLO hiện tại

| Luồng | SLI | SLO |
|---|---|---|
| Duyệt / tìm sản phẩm | Tỉ lệ request non-5xx | **≥ 99.5%** |
| Duyệt sản phẩm - độ trễ | p95 latency storefront | **< 1s** |
| Giỏ hàng | Tỉ lệ thao tác giỏ thành công | **≥ 99.5%** |
| **Đặt hàng (checkout)** | Tỉ lệ đặt hàng thành công | **≥ 99.0%** |

Checkout là luồng quan trọng nhất (ra tiền) → error budget = **1%**.

### 3 Metrics được chọn

| # | Metric | Service | Signal Type | Lý do chọn (tóm tắt) |
|---|---|---|---|---|
| 1 | **p95 Latency** | `checkout` | Latency | Luồng ra tiền, INC-1 history, coordinator 7+ deps |
| 2 | **HTTP 5xx Error Rate** | `cart` | Error rate | Cart → checkout path, INC-2 (valkey SPOF), SLO ≥ 99.5% |
| 3 | **CPU Utilization** | `product-catalog` | Saturation | Leading indicator, 4 services phụ thuộc, INC-1 root cause |

Ba metrics bao phủ 3 loại tín hiệu khác nhau trong mô hình USE/RED: **Latency**, **Error**, **Saturation** — trên 3 service cùng nằm trong luồng checkout.

---

## 2. Link PR / Commit — Bằng chứng implement

### Codebase structure

```
tf2-corp-platform/src/aio/
├── aiops/
│   ├── anomaly/          ← V001 anomaly engine (EWMA+STL, IsolationForest)
│   │   ├── v001.py       ← confirmed statistical detection algorithms
│   │   ├── events.py     ← converts confirmed findings into incident candidates
│   │   └── stats.py      ← Statistical utilities (mean, stdev, median, IQR, robust_score)
│   ├── detectors/        ← Rule-based detectors (threshold, dependency, no-data)
│   │   ├── threshold.py  ← Hard threshold SLO detector
│   │   ├── dependency.py ← Dependency error detector
│   │   └── no_data.py    ← Missing/stale signal detector
│   ├── pipeline/         ← Full detection → incident → remediation pipeline
│   │   └── runtime.py    ← Orchestrates: collect → qualify → detect → correlate → incident → notify → verify
│   ├── rca/              ← Root Cause Analysis (graph + robust scorer)
│   │   ├── engine.py     ← V001RcaEngine (graph traversal + repo-native robust score)
│   │   ├── graph.py      ← Topology-based graph traversal RCA
│   │   └── robust_score.py ← median/IQR robust scorer for statistical ranking
│   ├── correlation/      ← Event correlation (group by flow/service)
│   ├── enrichment/       ← Evidence enrichment
│   ├── verification/     ← Post-remediation verification via telemetry
│   ├── remediation/      ← Decision engine + policy + audit
│   ├── notifications/    ← Alert builder
│   ├── integrations/     ← Prometheus, Jaeger, OpenSearch, K8s clients
│   ├── config/           ← Pydantic settings + runtime.json
│   └── schemas/          ← Domain models (Pydantic)
├── evaluate/             ← E2E evaluation script (precision/recall/F1)
│   └── e2e_pipeline.py
├── tests/                ← Unit + integration tests (8 files)
└── config/
    └── runtime.json      ← Topology, signals, detectors, thresholds
```

### Key implementation files

| Component | File | Lines |
|---|---|---|
| EWMA+STL detector | `src/aio/aiops/anomaly/v001.py` (class `EwmaStlDetector`) | ~45 lines |
| IsolationForest detector | `src/aio/aiops/anomaly/v001.py` (class `ServiceIsolationForestDetector`) | ~35 lines |
| Adaptive event builder | `src/aio/aiops/anomaly/events.py` (class `AdaptiveAnomalyEventBuilder`) | Converts findings into incidents/alerts |
| V001 Anomaly Engine (orchestrator) | `src/aio/aiops/anomaly/v001.py` (class `V001AnomalyEngine`) | ~20 lines |
| Statistical utils | `src/aio/aiops/anomaly/stats.py` | ~50 lines |
| Threshold detector | `src/aio/aiops/detectors/threshold.py` | ~30 lines |
| Dependency detector | `src/aio/aiops/detectors/dependency.py` | ~35 lines |
| No-data detector | `src/aio/aiops/detectors/no_data.py` | ~45 lines |
| Pipeline runtime | `src/aio/aiops/pipeline/runtime.py` | ~120 lines |
| RCA engine | `src/aio/aiops/rca/engine.py` | ~50 lines |
| Domain schemas (Pydantic) | `src/aio/aiops/schemas/domain.py` | ~197 lines |
| Config schemas (validation) | `src/aio/aiops/schemas/config.py` | ~111 lines |
| Evaluation script | `src/aio/evaluate/e2e_pipeline.py` | ~204 lines |
| Pipeline tests | `src/aio/tests/test_runtime_pipeline.py` | ~249 lines |
| Anomaly/RCA tests | `src/aio/tests/test_v001_anomaly_rca.py` | ~69 lines |

> Core pipeline không phụ thuộc test mock. Numeric detector parameters live in tracked JSON configuration; deterministic severity/runbook routing is implemented in `anomaly/events.py`.

---

## 3. Phân tích 3 Metrics

---

### METRIC 1: Checkout Service — p95 Latency

#### Vì sao chọn metric này?

1. **Checkout là luồng kinh doanh quan trọng nhất** — SLO ≥ 99.0% (ra tiền). Khi checkout chậm, khách bỏ giỏ → mất doanh thu trực tiếp.

2. **Checkout là coordinator phức tạp nhất** — gọi 7+ dependency đồng bộ:

   ```
   checkout → cart (gRPC)
   checkout → product-catalog (gRPC)
   checkout → currency (gRPC)
   checkout → shipping → quote (HTTP)
   checkout → payment (gRPC)
   checkout → email (HTTP)
   checkout → accounting, fraud-detection (Kafka async)
   ```

   Bất kỳ dependency nào chậm đều phản ánh qua checkout latency — đây là **aggregated signal** tự nhiên.

3. **Lịch sử sự cố INC-1** (INCIDENT_HISTORY.md): *"vào giờ cao điểm, p95 latency checkout vọt lên vài giây. Nguyên nhân gốc: DB connection pool cạn."* → p95 latency đã từng là **leading indicator** cho sự cố thật, phát hiện trước khi success rate tụt.

4. **SLO.md** quy định storefront p95 < 1s. Dù checkout latency là diagnostic (không phải official SLO), nó là **early warning** cho checkout success rate.

#### Baseline "bình thường" hiện tại

> **Đo thực tế trên TF2 EKS cluster** (`techx-corp-prod`) lúc 2026-07-15T23:00 UTC+7. Checkout dùng **gRPC** (không phải HTTP).

| Điều kiện | Dải baseline p95 | Ghi chú |
|---|---|---|
| Tải bình thường (load-generator mặc định) | **62 – 87 ms** | Đo thực tế qua `rpc_server_duration_milliseconds_bucket`, range query 1h |
| Idle / tải rất thấp | **4.5 – 5 ms** | Load-generator dừng → chỉ còn health check, p95 giảm xuống ~4.75ms |
| Chuyển tiếp (load on/off) | **5 – 62 ms** | Giai đoạn warm-up khi traffic bắt đầu hoặc dừng |

**PromQL query đo baseline** (checkout dùng gRPC, metric đơn vị milliseconds):

```promql
histogram_quantile(0.95,
  sum(rate(rpc_server_duration_milliseconds_bucket{
    service_name="checkout"
  }[5m])) by (le)
)
```

> **Ghi chú:** Checkout KHÔNG có `http_server_request_duration_seconds_bucket` — phải dùng `rpc_server_duration_milliseconds_bucket`. Đơn vị: **milliseconds** (không phải seconds).

#### Ngưỡng bất thường

| Mức | Điều kiện trigger | Severity | Hành động |
|---|---|---|---|
| **Statistical anomaly** | Hai mẫu gần nhất đều có EWMA residual z-score ≥ 3.0 | SEV2 | Mở incident, gắn runbook, gửi notification và chạy RCA |

**Thiết kế chống false-alarm:**

- Yêu cầu `confirmation_points=2`; một spike đơn lẻ không tạo adaptive incident
- Loại bỏ giai đoạn warm-up cho tới khi có `min_points=30` mẫu baseline cộng hai mẫu xác nhận
- Giữ hard threshold cho official SLO và statistical anomaly cho deviation theo baseline
- Nếu official SLO/dependency rule đã xác nhận incident nhưng range data hiện tại ổn định, rule breach được dùng làm RCA seed; hệ thống không tạo adaptive incident giả.
- p95 latency là **diagnostic**, không tạo official SLO incident — chỉ tạo early warning

#### Phương pháp phát hiện

**EWMA + STL (Exponentially Weighted Moving Average + Seasonal-Trend Decomposition)**

**Cách hoạt động:**

1. Tính EWMA smoothing (α = 0.3) trên chuỗi latency → tạo trend line
2. Trừ seasonal component nếu đủ dữ liệu (≥ 2 periods) bằng STL decomposition
3. Tính residual = actual − (trend + seasonal)
4. Tính z-score của hai residual cuối cùng so với baseline residuals trước cửa xác nhận
5. Chỉ khi cả hai z-score ≥ threshold mới tạo `AnomalyFinding`
6. `AdaptiveAnomalyEventBuilder` chuyển finding thành incident candidate và notification bình thường

**Ưu điểm:**

- Thích nghi với trend thay đổi dần (drift) — EWMA tự điều chỉnh baseline
- Không quá nhạy với spike ngắn hạn nhờ EWMA dampening
- Xử lý được seasonal pattern (giờ cao điểm lặp lại hàng ngày)
- Explainable: có thể output "z-score = X, vượt threshold Y"

**Tham số cấu hình:**

| Parameter | Giá trị | Lý do |
|---|---|---|
| `ewma_alpha` | 0.3 | Cân bằng giữa phản ứng nhanh (α cao) và ổn định (α thấp). α=0.3 → ~70% trọng số 6 điểm gần nhất |
| `ewma_z_threshold` | 3.0 | 3-sigma rule → ~0.27% false-positive rate trong phân phối chuẩn |
| `min_points` | 30 | Cần 30 mẫu lịch sử trước cửa xác nhận |
| `confirmation_points` | 2 | Chặn spike đơn lẻ; cả hai mẫu gần nhất phải bất thường |
| `seasonal_period` | 1 | Không giả định seasonal trước khi có dữ liệu thật; điều chỉnh sau khi quan sát pattern |

**Implementation:** Class `EwmaStlDetector` trong `src/aio/aiops/anomaly/v001.py`

---

### METRIC 2: Cart Service — HTTP 5xx Error Rate

#### Vì sao chọn metric này?

1. **Cart nằm trên đường tới checkout** — mọi đơn hàng đều đi qua cart (add to cart → view cart → checkout). Cart lỗi = khách không thể mua hàng.

2. **SLO giỏ hàng ≥ 99.5%** (tỉ lệ thao tác thành công) — error budget chỉ cho phép **0.5%** lỗi. Nghiêm ngặt hơn checkout (99.0%).

3. **Lịch sử sự cố INC-2** (INCIDENT_HISTORY.md): *"một nhóm khách mất sạch giỏ hàng. Nguyên nhân: lớp lưu giỏ hàng chạy đơn lẻ (valkey-cart), khi pod bị reschedule thì state mất."* → error rate tăng đột biến khi backend store lỗi.

4. **Cart → valkey-cart là critical path** — topology graph cho thấy cart (criticality: critical) phụ thuộc hoàn toàn vào `valkey-cart` (Redis-compatible, criticality: critical). Valkey là SPOF tiềm năng.

5. **Error rate là user-visible** — user thấy lỗi "cannot add to cart" / "cart unavailable" ngay lập tức, ảnh hưởng trải nghiệm mua hàng.

#### Baseline "bình thường" hiện tại

> **Đo thực tế trên TF2 EKS cluster** (`techx-corp-prod`) lúc 2026-07-15T23:00 UTC+7.

| Điều kiện | Dải baseline Error Rate | Ghi chú |
|---|---|---|
| Tải bình thường | **0.0%** | Đo thực tế: không có 5xx. Cart RPS hiện tại: ~0.74 req/s. Cart p95 latency: ~4.86ms |
| Sau deploy / restart | **0.0% – 1.0%** (spike ngắn dự kiến) | INC-3: lỗi thoáng qua do readiness probe chưa xong |
| Khi valkey-cart lỗi | **Dự kiến spike > 5%** | INC-2: khi backend store down, hầu hết request sẽ 5xx |

**PromQL query đo baseline** (tỉ lệ lỗi 5xx trong 5 phút):

```promql
sum(rate(http_server_request_duration_seconds_count{
  service_name="cart",
  http_response_status_code=~"5.."
}[5m]))
/
sum(rate(http_server_request_duration_seconds_count{
  service_name="cart"
}[5m]))
```

> **Xác nhận:** Runtime dùng span-metric `traces_span_metrics_calls_total`. Query chỉ tổng hợp error ratio khi có request thật; không có traffic trả về missing, còn có traffic và không có lỗi trả về 0%.

#### Ngưỡng bất thường

| Mức | Điều kiện trigger | Severity | Hành động |
|---|---|---|---|
| **Warning** | Error rate > **0.5%** | SEV2 | Mở incident, gắn cart runbook và gửi notification |
| **Critical guard (reserved)** | Error rate > **2.0%** | SEV1 | Detector được cấu hình nhưng chưa bật để tránh hai rule tạo hai incident cho cùng triệu chứng |
| **Statistical anomaly** | Hai EWMA residual liên tiếp có z-score ≥ **3.0**; minimum deviation riêng cho signal = **0.5%** | SEV2 | Spike bất thường → correlation/RCA với các metric cùng service và topology |

**Thiết kế chống false-alarm:**

- Không có traffic → query trả về missing và detector business không fire; chỉ signal collection-health chuyên biệt được phép tạo monitoring-loss incident.
- Deploy/restart gây spike ngắn (INC-3) → yêu cầu ≥ 2 chu kỳ liên tục
- Kết hợp hard threshold (0.5%) + adaptive EWMA/STL để bắt cả vi phạm SLO lẫn deviation so với baseline.

#### Phương pháp phát hiện

**EWMA + STL — baseline thích nghi trên error ratio**

**Cách hoạt động:**

1. Lấy tối thiểu 30 mẫu lịch sử trước hai mẫu xác nhận.
2. Tính EWMA trend và trừ seasonal component khi cấu hình seasonal period cho phép.
3. Tính residual z-score với spread từ lịch sử; dùng minimum deviation theo signal khi baseline phẳng.
4. Chỉ fire khi cả hai residual cuối cùng vượt ngưỡng cấu hình.

**Ưu điểm:**

- **Thích nghi với drift** — EWMA cập nhật baseline theo tải gần đây.
- **Xử lý baseline phẳng** — minimum deviation `0.005` cho cart ratio tránh cả chia cho 0 lẫn bỏ sót mức lỗi nhỏ có ý nghĩa.
- **Chống spike đơn** — hai mẫu xác nhận liên tiếp mới tạo finding.

**Tham số cấu hình:**

| Parameter | Giá trị | Lý do |
|---|---|---|
| `ewma_z_threshold` | 3.0 | Ngưỡng residual chuẩn hóa của detector univariate |
| `min_points` | 30 | Cần ≥ 30 mẫu lịch sử trước cửa xác nhận |
| `minimum_deviation_by_signal.cart_error_rate_5m` | 0.005 | Scale tối thiểu cấu hình cho baseline cart phẳng |
| `confirmation_points` | 2 | Cả hai mẫu mới nhất phải bất thường |

**Implementation:** Class `EwmaStlDetector` trong `src/aio/aiops/anomaly/v001.py`. `ServiceIsolationForestDetector` là corroboration multivariate khi một service có ít nhất hai metric đủ lịch sử; robust score chỉ dùng trong RCA ranking và CPU busy-load suppression.

**Secondary:** Hard Threshold Detector (`ThresholdDetector` trong `src/aio/aiops/detectors/threshold.py`) — fire khi error rate vượt SLO boundary.

---

### METRIC 3: Product Catalog Service — CPU Utilization (Saturation)

#### Vì sao chọn metric này?

1. **Product Catalog là service đọc nhiều nhất** — mọi trang sản phẩm, search, recommendation đều gọi product-catalog. Topology graph cho thấy 4 service upstream phụ thuộc:

   ```
   frontend → product-catalog (gRPC)
   recommendation → product-catalog (gRPC)
   product-reviews → product-catalog (gRPC)
   checkout → product-catalog (gRPC)
   ```

   Và product-catalog phụ thuộc `postgresql` (DB quan hệ chính, shared với 2 service khác).

2. **Criticality: critical** — product-catalog down = storefront không hiển thị sản phẩm = mất toàn bộ funnel bán hàng.

3. **Saturation là leading indicator** — CPU cao thường xuất hiện **trước** khi latency tăng và error xảy ra. Phát hiện saturation sớm = cảnh báo trước khi user bị ảnh hưởng.

4. **Lịch sử sự cố INC-1** (INCIDENT_HISTORY.md): *"Nguyên nhân gốc: DB connection pool cạn khi tải tăng đột biến."* Resource pressure lên product-catalog (query PostgreSQL nặng khi search) là contributor. CPU/Memory saturation là tín hiệu cảnh báo sớm cho loại sự cố này.

5. **Loại tín hiệu khác biệt** — 2 metrics trên đo hiện tượng (symptom: latency, error), metric này đo **nguyên nhân tiềm ẩn** (cause: resource exhaustion). Bộ 3 metrics phủ cả symptom lẫn cause → tăng khả năng phát hiện sớm.

6. **Go service** — product-catalog viết bằng Go; dưới áp lực CPU cao, Go GC pause tăng → latency spike → cascading failure cho downstream (checkout, recommendation).

#### Baseline "bình thường" hiện tại

> **Đo thực tế trên TF2 EKS cluster** (`techx-corp-prod`) lúc 2026-07-15T23:00 UTC+7.
> Product-catalog có **2 replicas** (pods: `product-catalog-5987488c4f-cqnrf`, `product-catalog-5987488c4f-mgxtd`). **Không có CPU limits** (`k8s_container_cpu_limit` trả về empty).

| Điều kiện | Dải baseline CPU Usage | Ghi chú |
|---|---|---|
| Tải bình thường | **2 – 4 millicores** (per pod) | Pod 1: ~4.03 mc, Pod 2: ~1.96 mc. Tổng cả 2 pods: ~6 mc |
| Idle | **1 – 2 millicores** | Health check + connection pool keep-alive |
| Product-catalog p95 latency | **9.04 ms** (gRPC) | Rất nhanh, Go + gRPC + PostgreSQL |

> **Lưu ý:** Vì không có CPU limits, không thể tính % utilization. Dùng absolute millicores thay thế. Khi tải tăng đột biến (INC-1 scenario), CPU sẽ tăng đáng kể so với baseline ~4mc.

**PromQL query đo baseline** (absolute CPU usage qua OTel k8s receiver):

```promql
k8s_pod_cpu_usage{k8s_deployment_name="product-catalog"}
```

Alternative (nếu cần tổng cả 2 pods):
```promql
sum(k8s_pod_cpu_usage{k8s_deployment_name="product-catalog"})
```

> **Xác nhận:** Metric `k8s_pod_cpu_usage` (OTel k8s receiver) có sẵn. `container_cpu_usage_seconds_total` (cAdvisor) cũng có nhưng cần `rate()`. Product-catalog dùng **gRPC** (`rpc_server_duration_milliseconds`), p95 hiện tại = 9.04ms.

#### Ngưỡng bất thường

| Mức | Điều kiện trigger | Severity | Hành động |
|---|---|---|---|
| **Warning** | CPU > **20 millicores** (~5× baseline) liên tục ≥ 3 chu kỳ (90s) | SEV3 | Log warning, kiểm tra QPS tương ứng |
| **Critical** | CPU > **50 millicores** (~12× baseline) liên tục ≥ 2 chu kỳ (60s) | SEV2 | Mở incident, gửi alert, đề xuất horizontal scaling |
| **Statistical anomaly** | EWMA z-score ≥ **3.0** (đột biến so với trend hiện tại) | SEV3 | Spike bất thường → correlation check với checkout latency + PostgreSQL |

**Thiết kế chống false-alarm:**

- CPU spike một mẫu do GC hoặc batch job không mở incident → yêu cầu hai mẫu liên tiếp
- Nếu QPS tăng tương ứng (load tăng tự nhiên), CPU cao là **mong đợi** → cần kiểm tra CPU/QPS ratio, không chỉ CPU tuyệt đối
- Chỉ kêu khi CPU cao **bất thường so với trend** (z-score) HOẶC **vượt hard threshold** (85%)

#### Phương pháp phát hiện

**EWMA (Exponentially Weighted Moving Average) z-score**

**Cách hoạt động:** Giống Metric 1 — tính EWMA smoothing → residual → z-score. Áp dụng cho CPU utilization thay vì latency.

**Ưu điểm:**

- Thích nghi với daily pattern (CPU tăng giờ cao điểm là bình thường)
- Chỉ kêu khi deviation **bất thường so với trend hiện tại** chứ không phải threshold cứng
- CPU utilization thường có trend rõ ràng → EWMA bắt drift tốt hơn static threshold

**Tham số cấu hình:** Giống EWMA chung: `α=0.3`, `z_threshold=3.0`, `min_points=30`, `confirmation_points=2`.

**Implementation:** Class `EwmaStlDetector` trong `src/aio/aiops/anomaly/v001.py` (cùng class dùng cho Metric 1, chạy trên time series khác).

**Secondary:** `ServiceIsolationForestDetector` scores multiple aligned metrics inside one service. Cross-service RCA uses the checked topology and robust metric ranking; the repository does not claim a BARO/BOCPD detector.

---

## 4. Tổng hợp phương pháp phát hiện

### Kiến trúc detection pipeline

```
Telemetry Sources          Detection Layer                    Output
─────────────────    ─────────────────────────────    ─────────────────────

                     ┌─────────────────────────────┐
  Prometheus    ───  │     V001AnomalyEngine       │ 
  (metrics)          │                             │
                     │  ┌──────────────────────┐   │
                     │  │ 1. EwmaStlDetector   │   │
                     │  │    (univariate)      │   │    AnomalyFinding[]
                     │  │    • checkout p95    │   │          │
                     │  │    • catalog CPU     │   │          ▼
                     │  │    • cart errors     │   │   ┌──────────────────┐
                     │  └──────────────────────┘   │   │  V001RcaEngine   │
                     │                             │   │  (graph +        │
                     │  ┌──────────────────────┐   │   │  robust score)   │
                     │  │ 2. IsolationForest   │   │   └────────┬─────────┘
                     │  │    (robust score)    │   │           │
                     │  │    • cart error rate │   │           ▼
                     │  │    • combined score  │   │   RootCauseCandidate[]
                     │  └──────────────────────┘   │           │
                     │                             │           ▼
                     │  ┌──────────────────────┐   │   ┌────────────────────┐
                     │  │ Confirmation gate    │   │   │ AiopsPipeline      │
                     │  │ • 2 abnormal samples │   │   │ detect → correlate │
                     │  │ • finding → event    │───┼──▶│ → incident         │
                     │  │ • runbook routing    │   │   │ → notify → verify  │
                     │  └──────────────────────┘   │   └────────────────────┘
                     └─────────────────────────────┘
```

### Ma trận phương pháp × metric

| Phương pháp | Loại | Áp dụng cho Metric | Ưu điểm chính |
|---|---|---|---|
| **EWMA + STL** | Univariate, time-series | 1 (checkout latency), 3 (catalog CPU) | Thích nghi trend, seasonal aware, explainable |
| **EWMA + STL** | Univariate, time-series | 1 (checkout latency), 2 (cart error rate), 3 (catalog CPU) | Baseline riêng cho từng service × signal, chống spike đơn |
| **Isolation Forest** | Multivariate trong một service | Các metric đã align của cùng service | Corroboration giữa nhiều metric |
| **Hard Threshold** | Rule-based | SLO boundaries (backup) | Đảm bảo không bỏ sót vi phạm SLO |

### Vì sao chọn kết hợp nhiều phương pháp?

1. **Không có silver bullet** — EWMA/STL bắt deviation theo baseline; Isolation Forest corroborate nhiều metric; hard threshold bảo vệ SLO/error-budget. Kết hợp giúp bao phủ cả adaptive và policy guard.

2. **Giảm false alarm** — khi nhiều detector đồng ý (corroboration), confidence tăng. Correlator trong pipeline group events cùng (flow, service) và chọn candidate có confidence cao nhất.

3. **Explainable** — mỗi finding chứa signal, service, timestamp và score; incident notification thêm value, unit, window, threshold, contributing signals và error-budget impact.

4. **Phạm vi multivariate hiện tại** — Isolation Forest chỉ kết hợp metric trong cùng service. Correlation/RCA cross-service dựa trên topology; BARO/BOCPD không được triển khai hoặc tuyên bố.

---

## 5. ADR ký tên

ADR file: `docs/aiops/adr/ADR-DETECT-001.md`

### Tóm tắt quyết định

| Hạng mục | Quyết định |
|---|---|
| **Anomaly detection approach** | EWMA+STL (univariate) + Isolation Forest (multivariate trong service) + robust-score RCA |
| **Baseline strategy** | Per-service × per-metric. EWMA rolling baseline thích nghi, không dùng static threshold cho detection (chỉ dùng static cho SLO guard) |
| **Metrics selection** | 3 metrics × 3 services × 3 signal types: checkout p95 (latency), cart 5xx (error), catalog CPU (saturation) |
| **Anti-spam** | Hai mẫu bất thường liên tiếp, warm-up `min_points=30`, incident fingerprint deduplication |
| **Mode mặc định** | dry-run — detector chạy + ghi log + gửi alert nhưng không tự động remediate |
| **Trade-off** | Ưu tiên recall (bắt được sự cố) hơn precision (ít false alarm). Lý do: miss sự cố = mất doanh thu, false alarm = oncall kiểm tra 1 lần |

### Người ký

| Vai trò | Tên | Ngày |
|---|---|---|
| Owner | ___________ | ___/07/2026 |
| Reviewer | ___________ | ___/07/2026 |

> **Điều kiện revisit:** Khi có dữ liệu thật từ EKS ≥ 1 tuần, tune lại α/threshold dựa trên precision/recall thực đo → cập nhật ADR-DETECT-001 revision 2.

---

## 6. Cách chạy lại (Repro)

### Chạy unit tests (local)

```bash
cd tf2-corp-platform/src/aio
conda run -n capstone python -m pytest tests/ -v
```

### Chạy anomaly detection test

```bash
conda run -n capstone python -m pytest tests/test_v001_anomaly_rca.py -v
```

Test `test_v001_pipeline_ranks_top_root_cause_service_and_metrics` chạy end-to-end:
1. Tạo 3 metric series (checkout latency, payment latency, payment error) với hai điểm bất thường liên tiếp ở payment
2. Chạy V001AnomalyEngine → verify `ewma_stl` và `isolation_forest` tạo finding đã xác nhận
3. Chạy V001RcaEngine → verify RCA rank payment là root cause #1

### Chạy evaluation (trên dataset có nhãn)

```bash
conda run -n capstone python -B evaluate/e2e_pipeline.py --labels path/to/reviewer-labels.json --out evaluate/report.json
```

Output: JSON report với precision/recall/F1 cho incident detection + RCA top-K.

### Chạy pipeline qua API (local)

```bash
# Start server
conda run -n capstone uvicorn aiops.api:create_app --factory --port 8090

# Send test request
curl -X POST http://localhost:8090/api/v1/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{
    "observations": [{
      "signal_id": "checkout_bad_ratio_24h",
      "value": 0.02,
      "unit": "ratio",
      "window": "24h",
      "quality": "verified"
    }]
  }'
```

---

## 7. Việc cần làm cho #7b (hạn 25/07)

| # | Task | Trạng thái |
|---|---|---|
| 1 | Kết nối live Prometheus qua port-forward, endpoint lấy từ process environment | DONE |
| 2 | Thêm 3 signals mới (checkout_p95, cart_error_rate, catalog_cpu) vào `runtime.json` | DONE |
| 3 | Build `PrometheusCollector` — pull metrics tự động từ Prometheus | DONE |
| 4 | Scheduler source có sẵn; production enablement thuộc quyết định deployment | PARTIAL |
| 5 | Chạy e2e với incident thật — bơm sự cố qua flagd → chụp screenshot alert | TODO |
| 6 | Đo precision/recall/lead-time trên bộ sự cố có nhãn từ mentor | TODO |
| 7 | Thêm multi-window burn-rate alerting cho checkout (5m/1h và 30m/6h) | DONE |
| 8 | Mở rộng adaptive signal/detector tới checkout, payment, cart và product-catalog trong query budget giới hạn | DONE |

---

*Tài liệu này phục vụ cho Jira ticket `AI MANDATE #7a Detection · implement + phân tích`.*  
*Chặng sau (#7b) sẽ bổ sung bằng chứng chạy thật, screenshot alert, và số precision/recall.*
