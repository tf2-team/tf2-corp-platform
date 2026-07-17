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
   - [Metric 2: Cart Request Error Rate](#metric-2-cart-service--request-error-rate)
   - [Metric 3: Product Catalog CPU Usage](#metric-3-product-catalog-service--cpu-usage-resource-pressure-indicator)
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
| 2 | **Request Error Rate** | `cart` | Error rate | Cart → checkout path, valkey SPOF risk, SLO ≥ 99.5% |
| 3 | **CPU Usage** | `product-catalog` | Resource pressure | Leading indicator, 4 services phụ thuộc |

Ba metrics bao phủ 3 loại tín hiệu vận hành khác nhau: **Latency**, **Error**, và **Resource pressure** — trên 3 service cùng nằm trong luồng checkout. CPU được ghi là usage/resource pressure, không gọi là utilization percentage hoặc saturation vì deployment hiện không có CPU limit.

---

## 2. Link PR / Commit — Bằng chứng implement

### Codebase structure

```
tf2-corp-platform/src/aio/
├── aiops/
│   ├── anomaly/          ← V001 anomaly engine (EWMA residual, robust service score, BARO BOCPD)
│   │   ├── v001.py       ← 3 detector paths
│   │   └── stats.py      ← Statistical utilities (mean, stdev, median, IQR, robust_score)
│   ├── detectors/        ← Rule-based detectors (threshold, dependency, no-data)
│   │   ├── threshold.py  ← Hard threshold SLO detector
│   │   ├── dependency.py ← Dependency error detector
│   │   └── no_data.py    ← Missing/stale signal detector
│   ├── pipeline/         ← Full detection → incident → remediation pipeline
│   │   └── runtime.py    ← Orchestrates: collect → qualify → detect → correlate → incident → notify → verify
│   ├── rca/              ← Root Cause Analysis (graph + robust scorer)
│   │   ├── engine.py     ← V001RcaEngine (combines graph traversal + BARO robust score)
│   │   ├── graph.py      ← Topology-based graph traversal RCA
│   │   └── robust_score.py ← BARO robust scorer for statistical ranking
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
├── tests/                ← Unit + integration/smoke tests (12 Python files)
└── config/
    └── runtime.json      ← Topology, signals, detectors, thresholds
```

### Key implementation files

| Component | File | Lines |
|---|---|---|
| EWMA residual detector | `src/aio/aiops/anomaly/v001.py` (class `EwmaStlDetector`) | ~45 lines |
| Service-level robust-score detector | `src/aio/aiops/anomaly/v001.py` (class `ServiceIsolationForestDetector`) | ~35 lines |
| BARO BOCPD detector | `src/aio/aiops/anomaly/v001.py` (class `BaroBocpdDetector`) | ~40 lines |
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

> **Tất cả code là code thật**, không dùng `unittest.mock` trong core pipeline. Các hyperparameter chính được externalize qua `.env` + `runtime.json` + Pydantic Settings; một số fallback nội bộ vẫn là hằng số trong code và được mô tả rõ ở phần phương pháp.

### Commit evidence

- Detector paths (EWMA residual, robust service score, BARO BOCPD): [`d475fd7`](https://github.com/tf2-team/tf2-corp-platform/commit/d475fd7baf05491b4433d69cfa203d7e7a162f43)
- Kết nối hybrid detector vào E2E RCA: [`240bc05`](https://github.com/tf2-team/tf2-corp-platform/commit/240bc05991b81aaebd5af224b7c0826224a6a9e1)
- ADR chi tiết cho Mandate #7a: [`f1c1f00`](https://github.com/tf2-team/tf2-corp-platform/commit/f1c1f0097caab3df68a18bec270d22b56f0a321d)

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

3. **Lịch sử sự cố INC-1** (INCIDENT_HISTORY.md): *"vào giờ cao điểm, p95 latency checkout vọt lên vài giây. Nguyên nhân gốc: DB connection pool cạn."* → p95 latency đã là **triệu chứng quan sát được** trong sự cố thật và có giá trị cảnh báo sớm; incident history không khẳng định latency tăng trước success-rate drop.

4. **SLO.md** quy định storefront p95 < 1s. Dù checkout latency là diagnostic (không phải official SLO), nó là **early warning** cho checkout success rate.

#### Baseline "bình thường" hiện tại

> **Đo thực tế trên TF2 EKS cluster** (`techx-corp-prod`) lúc 2026-07-15T23:00 UTC+7. Checkout dùng **gRPC** (không phải HTTP).

| Điều kiện | Dải baseline p95 | Ghi chú |
|---|---|---|
| Tải bình thường (load-generator mặc định) | **62 – 87 ms** | Đo thực tế qua `rpc_server_duration_milliseconds_bucket`, range query 1h |
| Idle / tải rất thấp | **4.5 – 5 ms** | Load-generator dừng → chỉ còn health check, p95 giảm xuống ~4.75ms |
| Chuyển tiếp (load on/off) | **5 – 62 ms** | Giai đoạn warm-up khi traffic bắt đầu hoặc dừng |

**PromQL query đã dùng để đo baseline** (service-wide checkout gRPC, metric đơn vị milliseconds):

```promql
histogram_quantile(0.95,
  sum(rate(rpc_server_duration_milliseconds_bucket{
    service_name="checkout"
  }[5m])) by (le)
)
```

> **Ghi chú:** Checkout KHÔNG có `http_server_request_duration_seconds_bucket` — phải dùng `rpc_server_duration_milliseconds_bucket`. Đơn vị: **milliseconds** (không phải seconds).
>
> Query trên đo toàn bộ RPC server của `checkout`, đúng với baseline point-in-time đã ghi nhận. Khi tạo detector riêng cho API đặt hàng ở #7b, sẽ thêm `rpc_method="PlaceOrder"` và đo lại baseline cho riêng method đó để tránh health check/RPC khác làm loãng tín hiệu.

#### Ngưỡng bất thường

| Mức | Điều kiện trigger | Severity | Hành động |
|---|---|---|---|
| **Warning** | p95 > **200 ms** (~2.5× baseline 80ms) liên tục ≥ 3 chu kỳ (3 × 30s = 90s) | SEV3 | Log warning, bắt đầu theo dõi correlation |
| **Critical** | p95 > **500 ms** liên tục ≥ 2 chu kỳ (60s) | SEV1 | Mở incident, gửi alert, kích hoạt RCA tự động |
| **Statistical anomaly** | EWMA residual z-score ≥ **3.0** | SEV2 | Spike bất thường → correlation check với metrics khác |

**Thiết kế chống false-alarm:**

- Yêu cầu **consecutive cycles** (liên tục 2-3 chu kỳ), không kêu khi chỉ có 1 spike đơn lẻ
- Loại bỏ giai đoạn warm-up (< `min_points` = 8 samples) để tránh kêu nhầm khi mới khởi động
- Kết hợp hard threshold đã phân tích (warning 200ms, critical 500ms) VÀ statistical anomaly (z-score) để bắt cả vi phạm mức ảnh hưởng lẫn deviation so với baseline
- p95 latency là **diagnostic**, không tạo official SLO incident — chỉ tạo early warning

#### Phương pháp phát hiện

**EWMA residual Z-score (Exponentially Weighted Moving Average)**

**Cách hoạt động:**

1. Tính EWMA smoothing (α = 0.3) trên chuỗi latency → tạo trend line
2. Tính residual = actual − EWMA trend
3. Tính z-score của residual cuối cùng so với các residual trước đó
4. Nếu |z-score| ≥ threshold → đánh dấu bất thường

**Ưu điểm:**

- Thích nghi với trend thay đổi dần (drift) — EWMA tự điều chỉnh baseline
- Không quá nhạy với spike ngắn hạn nhờ EWMA dampening
- Explainable: có thể output "z-score = X, vượt threshold Y"

**Tham số cấu hình:**

| Parameter | Giá trị | Lý do |
|---|---|---|
| `ewma_alpha` | 0.3 | Cân bằng giữa phản ứng nhanh (α cao) và ổn định (α thấp). Với α=0.3, khoảng 88% tổng trọng số EWMA nằm ở 6 quan sát gần nhất |
| `ewma_z_threshold` | 3.0 | 3-sigma heuristic; chỉ tương ứng ~0.27% tail probability nếu residual gần phân phối chuẩn |
| `min_points` | 8 | Cần tối thiểu 8 samples (= 4 phút ở chu kỳ 30s) để baseline ổn |
| `seasonal_period` | 1 | Tắt seasonal adjustment trong cấu hình hiện tại; chỉ bật/tune sau khi có đủ dữ liệu chứng minh chu kỳ |

**Implementation:** Class hiện có tên `EwmaStlDetector` trong `src/aio/aiops/anomaly/v001.py`, nhưng với `seasonal_period=1` hành vi hiện tại là **EWMA residual Z-score**, không phải full STL decomposition.

---

### METRIC 2: Cart Service — Request Error Rate

#### Vì sao chọn metric này?

1. **Cart nằm trên đường tới checkout** — mọi đơn hàng đều đi qua cart (add to cart → view cart → checkout). Cart lỗi = khách không thể mua hàng.

2. **SLO giỏ hàng ≥ 99.5%** (tỉ lệ thao tác thành công) — error budget chỉ cho phép **0.5%** lỗi. Nghiêm ngặt hơn checkout (99.0%).

3. **Lịch sử sự cố INC-2** (INCIDENT_HISTORY.md): *"một nhóm khách mất sạch giỏ hàng. Nguyên nhân: lớp lưu giỏ hàng chạy đơn lẻ (valkey-cart), khi pod bị reschedule thì state mất."* INC-2 chứng minh `valkey-cart` là SPOF/data-loss risk. Sự cố đó không tự chứng minh HTTP 5xx tăng, vì vậy error-rate được chọn để bắt **request failure khi cart/valkey không phục vụ được**, còn data-loss cần tín hiệu riêng.

4. **Cart → valkey-cart là critical path** — topology graph cho thấy cart (criticality: critical) phụ thuộc hoàn toàn vào `valkey-cart` (Redis-compatible, criticality: critical). Valkey là SPOF tiềm năng.

5. **Error rate là user-visible** — user thấy lỗi "cannot add to cart" / "cart unavailable" ngay lập tức, ảnh hưởng trải nghiệm mua hàng.

#### Baseline "bình thường" hiện tại

> **Đo thực tế trên TF2 EKS cluster** (`techx-corp-prod`) lúc 2026-07-15T23:00 UTC+7.

| Điều kiện | Dải baseline Error Rate | Ghi chú |
|---|---|---|
| Tải bình thường | **0.0%** | Đo thực tế: không có request error. Cart RPS hiện tại: ~0.74 req/s. Cart p95 latency: ~4.86ms |
| Sau deploy / restart | **0.0% – 1.0%** (spike ngắn dự kiến) | Giả thuyết vận hành cần xác nhận ở #7b; INC-3 xảy ra ở payment, không phải bằng chứng trực tiếp cho cart |
| Khi valkey-cart không phục vụ được | **Dự kiến spike > 5%** | Giả thuyết cần kiểm chứng bằng fault injection/replay ở #7b; INC-2 chứng minh data-loss risk, không chứng minh error-rate cụ thể |

Cart phục vụ gRPC trên ASP.NET Core. Để không bỏ sót gRPC failure được trả qua RPC status thay vì HTTP 5xx transport status, detector dùng span error status cho server-side cart request.

**PromQL query đo request error rate trong 5 phút:**

```promql
(
sum(rate(traces_span_metrics_calls_total{
  service_name="cart",
  span_kind="SPAN_KIND_SERVER",
  status_code="STATUS_CODE_ERROR"
}[5m]))
/
sum(rate(traces_span_metrics_calls_total{
  service_name="cart",
  span_kind="SPAN_KIND_SERVER"
}[5m]))
)
or
(
0 * sum(rate(traces_span_metrics_calls_total{
  service_name="cart",
  span_kind="SPAN_KIND_SERVER"
}[5m]))
)
```

> Nhánh `or (0 * total_rate)` biến trường hợp không có error series thành giá trị số 0 khi vẫn có traffic. Nếu tổng traffic bằng 0, qualification gate/min-QPS check phải đánh dấu dữ liệu không đủ thay vì kết luận service khỏe.

#### Ngưỡng bất thường

| Mức | Điều kiện trigger | Severity | Hành động |
|---|---|---|---|
| **Warning** | Error rate > **0.5%** (= SLO boundary) liên tục ≥ 2 chu kỳ (60s) | SEV2 | Ghi nhận, theo dõi error budget burn rate |
| **Critical** | Error rate > **2.0%** liên tục ≥ 2 chu kỳ (60s) | SEV1 | Mở incident, gửi alert, kiểm tra valkey-cart health |
| **Statistical anomaly** | Chỉ dùng Robust Score khi baseline có đủ điểm và IQR > 0; nếu baseline phẳng ở 0 thì ưu tiên hard threshold | SEV2 | Spike bất thường → correlation check với checkout + valkey |

**Thiết kế chống false-alarm:**

- Không kết luận error rate = 0 khi QPS = 0 → cần check `QPS > min_qps_threshold` trước khi đánh giá.
- Deploy/restart gây spike ngắn (INC-3) → yêu cầu ≥ 2 chu kỳ liên tục
- Dùng SLO hard threshold (0.5%) làm detector chính. Robust Score chỉ là detector bổ sung sau khi có baseline đủ biến thiên; baseline toàn số 0 cần xử lý riêng.

#### Phương pháp phát hiện

**Hard threshold theo SLO + minimum-traffic gate; Robust Score là bổ sung có điều kiện**

**Cách hoạt động:**

1. Tính request error rate trên cửa sổ 5 phút và kiểm tra traffic đủ lớn.
2. Fire warning khi error rate > 0.5% trong 2 chu kỳ; fire critical khi > 2.0% trong 2 chu kỳ.
3. Khi baseline có đủ biến thiên, tính Median/IQR trên lịch sử và dùng Robust Score để bổ sung khả năng bắt outlier.
4. Khi IQR = 0, không dùng fallback theo đơn vị chung để quyết định anomaly; giữ hard threshold làm nguồn quyết định.

**Ưu điểm:**

- Hard threshold bám trực tiếp SLO cart và vẫn hoạt động khi baseline bình thường bằng 0.
- Minimum-traffic gate tránh diễn giải no-traffic/no-data thành 0% lỗi.
- Median/IQR, khi dữ liệu có spread, không bị kéo lệch bởi một vài spike cũ.

**Tham số cấu hình:**

| Parameter | Giá trị | Lý do |
|---|---|---|
| Warning threshold | 0.5% | Khớp error-budget boundary của SLO cart 99.5% |
| Critical threshold | 2.0% | Mức lỗi user-visible rõ ràng, cần mở incident |
| Consecutive cycles | 2 | Tránh page vì một spike ngắn |
| `min_points` cho robust score | 8 | Chỉ đánh giá thống kê sau warm-up; cần thêm điều kiện IQR > 0 |

**Implementation mapping:** `ThresholdDetector` trong `src/aio/aiops/detectors/threshold.py` cung cấp hard-threshold primitive. `robust_score()` trong `src/aio/aiops/anomaly/stats.py` cung cấp scoring bổ sung. Consecutive-cycle state, min-QPS gate, và signal cart cụ thể vẫn phải được nối vào runtime ở #7b.

> Class `ServiceIsolationForestDetector` hiện tại thực chất tổng hợp Robust Score của **ít nhất 2 metric cùng service**; nó không phải sklearn Isolation Forest và không được dùng làm bằng chứng cho univariate cart error-rate trong tài liệu này.

---

### METRIC 3: Product Catalog Service — CPU Usage (Resource Pressure Indicator)

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

3. **Resource pressure là leading indicator** — CPU usage tăng bất thường có thể xuất hiện **trước** khi latency tăng và error xảy ra. Phát hiện sớm giúp cảnh báo trước khi user bị ảnh hưởng.

4. **Lịch sử sự cố INC-1** (INCIDENT_HISTORY.md): *"Nguyên nhân gốc: DB connection pool cạn khi tải tăng đột biến."* INC-1 không xác nhận CPU product-catalog là root cause. CPU usage được chọn như tín hiệu resource pressure bổ sung; connection-pool usage/wait vẫn là tín hiệu trực tiếp hơn cho kịch bản INC-1.

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

> **Lưu ý:** Vì không có CPU limits, không thể tính % utilization hoặc saturation ratio. Dùng absolute millicores như một resource-pressure indicator. Đây là deviation so với baseline ~4mc, không phải phần trăm saturation.

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

- CPU spike ngắn (< 30s) do GC hoặc batch job là bình thường → yêu cầu consecutive cycles
- Nếu QPS tăng tương ứng (load tăng tự nhiên), CPU cao là **mong đợi** → cần kiểm tra CPU/QPS ratio, không chỉ CPU tuyệt đối
- Chỉ kêu khi CPU cao **bất thường so với trend** (z-score) HOẶC vượt hard threshold đã phân tích (20/50 millicores)

#### Phương pháp phát hiện

**EWMA residual Z-score**

**Cách hoạt động:** Giống Metric 1 — tính EWMA smoothing → residual → z-score. Áp dụng cho CPU usage thay vì latency.

**Ưu điểm:**

- Thích nghi với trend tải thay đổi dần
- Chỉ kêu khi deviation **bất thường so với trend hiện tại** chứ không phải threshold cứng
- CPU usage thường có trend rõ ràng → EWMA bắt drift tốt hơn static threshold

**Tham số cấu hình:** Giống EWMA chung: `α=0.3`, `z_threshold=3.0`, `min_points=8`.

**Implementation:** Class `EwmaStlDetector` trong `src/aio/aiops/anomaly/v001.py` (với cấu hình hiện tại hoạt động như EWMA residual Z-score, cùng primitive dùng cho Metric 1).

**Secondary (bonus):** Multivariate correlation qua BARO BOCPD — khi CPU product-catalog spike đồng thời với checkout latency tăng → tăng confidence rằng đây là sự cố thật (corroborating signal). Implementation: Class `BaroBocpdDetector` trong `src/aio/aiops/anomaly/v001.py`.

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
                     │  │    (EWMA residual)   │   │    AnomalyFinding[]
                     │  │    • checkout p95    │   │          │
                     │  │    • catalog CPU     │   │          ▼
                     │  └──────────────────────┘   │   │  V001RcaEngine   │
                     │                             │   │  (graph +        │
                     │  ┌──────────────────────┐   │   │  robust score)   │
                     │  │ 2. Service robust    │   │   └────────┬─────────┘
                     │  │    score             │   │           │
                     │  │    • >=2 series      │   │           ▼
                     │  │      per service     │   │   RootCauseCandidate[]
                     │  └──────────────────────┘   │           │
                     │                             │           ▼
                     │  ┌──────────────────────┐   │   ┌────────────────────┐
                     │  │ 3. BaroBocpdDetector │   │   │ AiopsPipeline      │
                     │  │    (multivariate)    │   │   │ detect → correlate │
                     │  │    • ALL signals     │   │   │ → incident         │
                     │  │    • changepoint     │   │   │ → notify           │
                     │  └──────────────────────┘   │   │ → policy (dry-run) │
                     │                             │   │ → verify           │
                     └─────────────────────────────┘   └────────────────────┘
```

### Ma trận phương pháp × metric

| Phương pháp | Loại | Áp dụng cho Metric | Ưu điểm chính |
|---|---|---|---|
| **EWMA residual Z-score** | Univariate, time-series | 1 (checkout latency), 3 (catalog CPU usage) | Thích nghi trend, explainable |
| **Hard Threshold + traffic gate** | Rule-based | 2 (cart request error rate), safety guards cho 1/3 | Bám SLO/impact boundary; xử lý được baseline error = 0 |
| **Robust Score (IQR)** | Statistical, bổ sung | Chỉ khi baseline có IQR > 0; service-level path cần ≥2 series/service | Robust với outlier khi dữ liệu có spread |
| **BARO BOCPD** | Multivariate, changepoint | Tất cả 3 metrics đồng thời (bonus) | Phát hiện correlation cross-service |

### Vì sao chọn kết hợp nhiều phương pháp?

1. **Không có silver bullet** — EWMA bắt deviation so với trend; hard threshold bám trực tiếp mức ảnh hưởng/SLO; IQR bổ sung khi baseline có spread. Kết hợp = bao phủ tốt hơn.

2. **Giảm false alarm** — khi nhiều detector đồng ý (corroboration), confidence tăng. Correlator trong pipeline group events cùng (flow, service) và chọn candidate có confidence cao nhất.

3. **Explainable** — mỗi detector output reason + score cụ thể (ví dụ "z-score = 4.2 on checkout p95" hoặc "cart error rate = 0.8%, vượt warning 0.5%"). Mentor/oncall biết vì sao hệ thống kêu.

4. **Multivariate là bonus** — BARO BOCPD chạy trên tất cả series đồng thời để phát hiện changepoint ảnh hưởng nhiều service cùng lúc (vd: DB connection pool cạn → cả checkout lẫn product-catalog spike cùng lúc).

---

## 5. ADR và trạng thái ký

ADR file: `docs/aiops/adr/ADR-DETECT-001.md`

### Tóm tắt quyết định

| Hạng mục | Quyết định |
|---|---|
| **Anomaly detection approach** | EWMA residual Z-score (univariate trend), hard threshold + traffic gate, Robust Score có điều kiện, BARO BOCPD (multivariate changepoint bonus) |
| **Baseline strategy** | Per-service × per-metric. Rolling historical baseline cho statistical detector; static threshold dùng cho SLO/impact guard |
| **Metrics selection** | 3 metrics × 3 services × 3 signal types: checkout p95 (latency), cart request error rate (error), catalog CPU usage (resource pressure) |
| **Anti-spam** | `min_points` đã có; consecutive-cycle state, min-QPS gate và corroboration policy là phần phải hoàn thiện/nối runtime ở #7b |
| **Mode mặc định** | observe/dry-run — tạo kết quả/notification object, không tự động remediate production |
| **Trade-off** | Ưu tiên recall (bắt được sự cố) hơn precision (ít false alarm). Lý do: miss sự cố = mất doanh thu, false alarm = oncall kiểm tra 1 lần |

### Người ký

| Vai trò | Tên | Ngày | Trạng thái |
|---|---|---|---|
| Owner | Nguyen Quy Hung | — | Chờ xác nhận/sign-off trong ADR |
| Reviewer | — | — | Pending team review |

> **Trạng thái hiện tại:** ADR đang ở trạng thái `Proposed, pending reviewer sign-off`. Không xem mục #7a là hoàn tất cho tới khi owner/reviewer ký hoặc để lại approval có truy vết.

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
1. Tạo 3 metric series (checkout latency, payment latency, payment error) với spike ở payment
2. Chạy `V001AnomalyEngine` → verify 3 detector paths đều chạy. Output vẫn dùng legacy algorithm ids `ewma_stl`, `isolation_forest`, `baro_bocpd`; tên ids không có nghĩa implementation đang dùng full STL/sklearn Isolation Forest.
3. Chạy V001RcaEngine → verify RCA rank payment là root cause #1

### Chạy evaluation (trên dataset có nhãn)

```bash
conda run -n capstone python -B evaluate/e2e_pipeline.py --limit 10 --labels evaluate/incident_labels.csv --out evaluate/report.json
```

Output: JSON report với precision/recall/F1 cho incident detection + RCA top-K.

### Chạy rule-based pipeline qua API (local)

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

> Request trên chứng minh static observation → threshold detector → incident/notification path. Nó không chạy V001 anomaly/RCA vì không gửi `metric_series`; dùng focused anomaly/RCA test ở trên để reproduce V001 path.

---

## 7. Việc cần làm cho #7b (hạn 25/07)

| # | Task | Trạng thái |
|---|---|---|
| 1 | Kết nối live Prometheus — thay placeholder URL trong `.env` bằng endpoint thật TF2 | TODO |
| 2 | Thêm 3 signals mới (checkout_p95, cart_request_error_rate, catalog_cpu_usage) vào `runtime.json` | TODO |
| 3 | Build `PrometheusCollector` — pull metrics tự động từ Prometheus | TODO |
| 4 | Thêm scheduler — chạy pipeline liên tục mỗi 30s | TODO |
| 5 | Chạy e2e với incident thật — bơm sự cố qua flagd → chụp screenshot alert | TODO |
| 6 | Đo precision/recall/lead-time trên bộ sự cố có nhãn từ mentor | TODO |
| 7 | Thêm burn-rate alerting — tính error budget consumption rate cho SLO | TODO |
| 8 | Mở rộng thêm service (shipping, payment, currency...) | TODO |

---

*Tài liệu này phục vụ cho Jira ticket `AI MANDATE #7a Detection · implement + phân tích`.*  
*Chặng sau (#7b) sẽ bổ sung bằng chứng chạy thật, screenshot alert, và số precision/recall.*
