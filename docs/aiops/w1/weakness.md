# Báo cáo đánh giá điểm yếu hệ thống — Góc nhìn AIOps

**Dự án:** TechX Corp Platform — Phase 3 Capstone  
**Nhóm / Track:** AIO04 — AIOps  
**Người thực hiện:** Nguyễn Quý Hưng  
**Ngày báo cáo:** 09/07/2026  
**Môi trường đánh giá:** AWS EKS `techx-tf2` (`us-west-2`) qua `kubectl port-forward`  
**Tài liệu tham chiếu:** `INCIDENT_HISTORY.md`, `ARCHITECTURE.md`, `SLO.md`, `techx-corp-chart/values.yaml`

---

## Tóm tắt điều hành (Executive Summary)

Sau khi tiếp quản hệ thống TechX Corp Platform, nhóm AIOps đã thực hiện đánh giá baseline bằng ba nguồn: **lịch sử sự cố (INCIDENT_HISTORY)**, **metrics/traces thời gian thực (Grafana/Jaeger)**, và **rà soát source code / Helm config**.

**Kết luận chính:**

1. **Hệ thống có observability tốt** — OpenTelemetry pipeline hoạt động ổn định (collector 0% drop/error), đủ dữ liệu để xây AIOps.
2. **Luồng checkout vẫn là điểm yếu chính về độ trễ** — baseline EKS ghi nhận `PlaceOrder` error 0% nhưng p95 ~4.55s; hệ thống chưa vi phạm SLO theo success rate, nhưng còn latency risk khi tải tăng.
3. **Ba pattern lịch sử (INC-1/2/3) vẫn còn nguy cơ tái diễn** — pool DB dưới peak load, SPOF do single-replica, và readiness/dependency gating chưa đủ chặt.
4. **Tầng AI có khoảng trống quan sát** — service `llm` không có OpenTelemetry; Jaeger không hiển thị `llm` như một service riêng.
5. **flagd là kênh incident injection quan trọng** — 14+ failure paths cần được map vào detection + runbook matching (không được vô hiệu hóa theo RULES).

**Khuyến nghị ưu tiên (P0):** alert checkout SLO, alert DB connection saturation, dependency failure detection, Kafka consumer error alert, flag inventory, và LLM observability qua `product-reviews`.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu

Xác định các điểm yếu vận hành của hệ thống từ góc nhìn AIOps, làm cơ sở xây dựng backlog tự động hóa phát hiện – chẩn đoán – xử lý sự cố.

### 1.2 Phạm vi


| Trong phạm vi                          | Ngoài phạm vi                                   |
| -------------------------------------- | ----------------------------------------------- |
| Đánh giá observability hiện có         | Triển khai fix production trên EKS              |
| Baseline metrics/traces trên EKS stack | Phát triển tính năng AIE (copilot, LLM product) |
| Rà soát 6 nhóm rủi ro vận hành         | Tắt hoặc redirect flagd incident path           |
| Đề xuất backlog AIOps P0/P1            | Load test quy mô production                     |


### 1.3 Phương pháp

```text
INCIDENT_HISTORY (quá khứ)
        +
Grafana / Jaeger / Prometheus (hiện tại)
        +
Source code + Helm values (cấu hình)
        ↓
Findings có evidence
        ↓
Backlog AIOps ưu tiên
```

**Công cụ sử dụng:** Grafana (APM, PostgreSQL, OTel Collector, Spanmetrics), Jaeger, Prometheus, `kubectl`, rà soát mã nguồn.

---

## 2. Bối cảnh hệ thống

TechX Corp Platform là hệ thống microservice polyglot (~18 services) với luồng chính:

- **Browse:** frontend → product-catalog / recommendation  
- **AI:** product-reviews → llm (HTTP, mock mặc định)  
- **Checkout:** frontend → checkout → cart, catalog, currency, shipping, payment, kafka  
- **Async:** kafka → accounting, fraud-detection

**SLO liên quan:**


| Luồng        | SLO                                     |
| ------------ | --------------------------------------- |
| Browse       | ≥ 99.5% success, p95 < 1s               |
| Cart         | ≥ 99.5% success                         |
| **Checkout** | **≥ 99.0% success** (ưu tiên cao nhất)  |
| AI summary   | Best-effort, không hiển thị summary sai |


Telemetry đi qua OpenTelemetry Collector → Prometheus / Jaeger / OpenSearch / Grafana.

---

## 3. Kết quả quan sát baseline (Grafana)

**Thời gian:** 09/07/2026, cửa sổ 15–30 phút  
**Nguồn:** APM Dashboard, PostgreSQL, OTel Collector, Spanmetrics

### 3.1 Tổng quan


| Chỉ số                 | Giá trị                                                      | Đánh giá                  |
| ---------------------- | ------------------------------------------------------------ | ------------------------- |
| Error rate cao nhất    | `checkout` ~0% (khung thời gian chụp)                        | Ổn theo success rate      |
| p95 latency đáng chú ý | `PlaceOrder` ~4.55s; `frontend-web` ~15s (long-poll pattern) | Cần tối ưu / tuning alert |
| PostgreSQL             | QPS ~52, connections 2–5, deadlocks 0, cache hit ~100%       | Ổn tại baseline EKS       |
| OTel Collector         | Spans ~~314 ops/s, metrics ~174 ops/s, drop thấp (<~~1.5%)   | Pipeline ổn               |
| Host memory            | Không thấy tín hiệu bất thường rõ rệt trong khung chụp       | Theo dõi định kỳ          |


### 3.2 Checkout (APM — service `checkout`)


| Signal                           | Value                              | Nhận xét                                     |
| -------------------------------- | ---------------------------------- | -------------------------------------------- |
| `PlaceOrder` error rate          | **~0%**                            | Chưa vi phạm SLO success                     |
| `PlaceOrder` p95                 | **~4.55s**                         | Cao hơn mục tiêu vận hành mong muốn          |
| Outbound `shipping POST` latency | ~10.8ms                            | Không phải bottleneck chính trong khung chụp |
| Outbound cart/catalog/currency   | ~10–25ms                           | Bình thường                                  |
| Nhận định                        | Checkout thành công nhưng còn chậm | Cần theo dõi latency regression              |


### 3.3 Các service khác (Spanmetrics)


| Service         | p95 latency                                            | Error rate                                           |
| --------------- | ------------------------------------------------------ | ---------------------------------------------------- |
| frontend-web    | 15s                                                    | Phù hợp long-poll / streaming pattern                |
| checkout        | ~1.05s (service-level), ~3.7–4.6s ở span checkout path | Thấp trong panel tổng quan, cao ở operation critical |
| frontend-proxy  | ~149ms                                                 | Ổn                                                   |
| product-reviews | ~93.6ms                                                | Ổn                                                   |
| fraud-detection | ~90.9ms                                                | Ổn                                                   |


**Nhận định:** Telemetry pipeline ổn trên EKS; vấn đề chính hiện tại là **độ trễ checkout path** và **nhiễu alert do long-poll spans**, hơn là lỗi collector/export.

---

## 4. Phân tích distributed tracing (Jaeger)

### 4.1 Luồng Browse — ổn định


| Trace                                          | Duration                                  | Path                                                                                               |
| ---------------------------------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `frontend-proxy: GET` (browse/recommendations) | ~29.6ms *(incomplete, 10 spans, depth 4)* | frontend-proxy → frontend (`/api/recommendations`) → recommendation → product-catalog (GetProduct) |


**Kết luận:** Browse path healthy tại baseline; latency thấp, không có error.

### 4.2 Luồng AI — quan sát qua `product-reviews`


| Operation               | Duration                                                            | Ghi chú                                                                 |
| ----------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `GetProductReviews`     | Quan sát trong trace AI path, không phải operation chính ở mẫu chụp | Vẫn là DB-centric path                                                  |
| `AskProductAIAssistant` | ~63.35ms *(trace detail EKS: 15 spans, depth 12)*                   | Gọi LLM qua HTTP từ `product-reviews`; không thấy error trong trace mẫu |


**Vì sao không thấy service `llm` trong Jaeger?**

Đây là hành vi **đúng với kiến trúc hiện tại**, không phải lỗi cấu hình Jaeger:

1. `GetProductReviews` không invoke LLM.
2. LLM chỉ được gọi qua `AskProductAIAssistant`.
3. Service `llm` (`app.py`) **không được instrument OpenTelemetry** → không xuất hiện như service riêng trong Jaeger.
4. Quan sát AI path phải dùng span `get_ai_assistant_response` trong `product-reviews`, metrics `app_ai_assistant_counter`, và logs.

**Finding:** LLM observability gap — blind spot ở tầng model service.

### 4.3 Luồng Checkout — điểm yếu chính

**Baseline EKS (checkout success traces):**


| Field    | Value                                                                                                                  |
| -------- | ---------------------------------------------------------------------------------------------------------------------- |
| Trace    | `load-generator: user_checkout_single`                                                                                 |
| Duration | **~863.7ms** (mẫu trong danh sách traces)                                                                              |
| Trace    | `load-generator: user_checkout_multi`                                                                                  |
| Duration | **~1.6s** *(54 spans, depth 12 — ảnh trace detail)*                                                                    |
| Errors   | Không thấy lỗi trong khung chụp                                                                                        |
| Path     | frontend-proxy → frontend → checkout → cart → product-catalog → currency → **shipping POST** → quote → payment → flagd |


**Kết luận:** Checkout path trên EKS đang **thành công** nhưng còn độ trễ đáng kể (≈0.86–1.6s theo trace). Dù không thấy error trong khung chụp, checkout vẫn **phụ thuộc chặt vào chuỗi dependency** (shipping/payment/quote…), nên rủi ro blast-radius khi một dependency xuống vẫn cao (map với INC-2/INC-3).

### 4.4 Luồng Kafka (sơ bộ)

Drill-down log `kubectl -n techx-tf2 logs deploy/accounting --tail=50` cho thấy `Accounting.Consumer` đang **consume liên tục** và in `Order details` cho nhiều order liên tiếp, chưa thấy error trong mẫu log hiện tại.

**Kết luận tạm thời:** chưa có bằng chứng lỗi ổn định ở accounting consumer tại thời điểm đo EKS; rủi ro Kafka path nên theo dõi theo hướng **intermittent/transient** bằng alert lag + error rate. Producer path vẫn là `checkout` → kafka → `accounting` / `fraud-detection`.

---

## 5. Findings — Điểm yếu hệ thống

### 5.1 Bảng tổng hợp


| ID   | Finding                                                                  | Severity | SLO / Business impact                                           | Evidence                                                |
| ---- | ------------------------------------------------------------------------ | -------- | --------------------------------------------------------------- | ------------------------------------------------------- |
| F-01 | DB connection pool chưa tune; `product-reviews` dùng per-request connect | High     | Checkout latency risk at peak (INC-1)                           | `product-catalog/main.go`, `database.py`, Grafana PG    |
| F-02 | Toàn bộ services mặc định `replicas: 1`                                  | High     | SPOF — một pod chết kéo luồng chính (INC-2)                     | `values.yaml`                                           |
| F-03 | gRPC health check luôn trả SERVING, không phản ánh dependency            | Medium   | Deploy-time errors (INC-3)                                      | payment, checkout, catalog source                       |
| F-04 | Kafka consumer path có tín hiệu lỗi gián đoạn (intermittent)             | Medium   | Async order processing có nguy cơ nhiễu theo thời điểm tải/flag | Jaeger `order-consumed` (lịch sử) + accounting logs EKS |
| F-05 | LLM service không có OTel instrumentation                                | Medium   | AI path blind spot trong Jaeger                                 | `llm/app.py`                                            |
| F-06 | 14+ flagd-controlled failure paths chưa map alert/runbook                | High     | Incident injection không được detect kịp                        | `demo.flagd.json`                                       |
| F-07 | Checkout hard-depends on shipping, no fallback                           | **High** | Rủi ro vi phạm SLO khi dependency down                          | Jaeger checkout trace + kiến trúc phụ thuộc             |
| F-08 | Log severity chưa chuẩn hóa giữa metric/log                              | Medium   | MTTD chậm, khó triage khi incident                              | APM panel + log review                                  |
| F-09 | flagd EventStream latency cao (p95 15s) — long-poll                      | Low–Med  | False positive alert risk                                       | Spanmetrics                                             |


### 5.2 Phân tích theo 6 nhóm đánh giá

#### (1) DB connection pool saturation

- **Hiện trạng baseline EKS:** PostgreSQL QPS ~52, connections 2–5, deadlocks 0, cache hit ~100% — **chưa saturated**.
- **Rủi ro từ code:** `product-catalog` không set `SetMaxOpenConns`; `product-reviews` mở connection mới mỗi request.
- **Liên hệ INC-1:** Pool cạn lúc peak đã từng xảy ra; pattern vẫn tồn tại trong code.

#### (2) Single-replica services (SPOF)

- Helm `default.replicas: 1` cho tất cả components.
- Critical path: `frontend-proxy`, `checkout`, `cart`+`valkey-cart`, `payment`, `postgresql`, `kafka`, `flagd`.
- **Liên hệ INC-2:** Mất node → mất state/availability.

#### (3) Readiness probes

- Đa số service: gRPC health = SERVING vĩnh viễn.
- Chỉ `cart` có readiness logic thật (và bị flagd `failedReadinessProbe` control).
- **Liên hệ INC-3:** Traffic có thể vào instance chưa sẵn sàng.

#### (4) Kafka consumer lag

- Architecture: checkout produce → accounting/fraud-detection consume.
- Flag `kafkaQueueProblems` có thể inject lag (producer overload + consumer delay).
- Evidence EKS hiện tại: accounting consumer xử lý order bình thường trong mẫu log; vẫn cần alert lag + consumer error rate để bắt lỗi gián đoạn.

#### (5) LLM latency/error baseline


| Metric                  | Baseline                      |
| ----------------------- | ----------------------------- |
| `GetProductReviews`     | ~13–15ms (DB only)            |
| `AskProductAIAssistant` | ~63.35ms (EKS trace mẫu)      |
| `llm` in Jaeger         | Không có (expected — no OTel) |


Flag paths: `llmInaccurateResponse`, `llmRateLimitError` — cần monitor qua `product-reviews` spans và flagd state.

#### (6) flagd-controlled failure paths

14 flags trong `demo.flagd.json` covering payment, cart, kafka, llm, ad, load flood, readiness, v.v.  
Checkout trace xác nhận `flagd` tham gia luồng (`EmptyCart` → `flagd.ResolveBoolean`).

**Nguyên tắc AIOps:** Detect và contain — **không disable flagd** (RULES.md).

---

## 6. Đối chiếu INCIDENT_HISTORY


| Incident quá khứ                      | Triệu chứng lịch sử        | Evidence hiện tại                                                             | Trạng thái                         |
| ------------------------------------- | -------------------------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| **INC-1** DB pool cạn lúc peak        | Checkout chậm, timeout     | PG baseline EKS ổn (QPS ~52, conn 2–5, deadlocks 0) nhưng code chưa tune pool | **Risk còn** — chưa reproduce peak |
| **INC-2** Mất giỏ khi node reschedule | Cart/valkey SPOF           | replicas=1; valkey in-cluster                                                 | **Risk còn**                       |
| **INC-3** Payment lỗi lúc deploy      | Traffic vào pod chưa ready | gRPC health always SERVING; checkout không gate dependency                    | **Risk còn**                       |


**Insight:** Hệ thống chạy tốt ở điều kiện bình thường nhưng **yếu khi có áp lực** (peak load, mất node, dependency unavailable). Đây là trọng tâm AIOps cần cover.

---

## 7. Đánh giá rủi ro và ưu tiên


| Ưu tiên | Hạng mục                                    | Lý do                           |
| ------- | ------------------------------------------- | ------------------------------- |
| **P0**  | Checkout dependency failure alert           | Ảnh hưởng trực tiếp SLO 99%     |
| **P0**  | DB connection saturation alert              | INC-1 có thể tái diễn           |
| **P0**  | Flag inventory + incident signature mapping | BTC inject incident qua flagd   |
| **P0**  | Kafka consumer error/lag alert              | Async path unreliable           |
| **P0**  | LLM observability via product-reviews       | Blind spot tầng AI              |
| **P0**  | Service topology / blast-radius map         | Cần cho RCA và runbook matching |
| **P1**  | Readiness probe audit                       | INC-3 pattern                   |
| **P1**  | Log severity standardization                | MTTD improvement                |
| **P1**  | flagd EventStream alert tuning              | Tránh false positive long-poll  |


---

## 8. Đề xuất backlog AIOps (đầu vào sprint tiếp theo)

### 8.1 P0 — Tuần 1–2

1. **Alert: checkout p95 + error rate vs SLO** — threshold map SLO 99%.
2. **Alert: DB connection saturation** — `go_sql_connections_in_use`, PG active connections.
3. **Dependency failure detection** — checkout → shipping/payment/cart unavailable.
4. **Kafka consumer lag + accounting error alert.**
5. **Flag inventory document** — map 14 flags → symptom → runbook.
6. **LLM baseline dashboard** — `product-reviews` AskProductAIAssistant latency/error.
7. **Service topology map v1** — blast-radius cho checkout path.

### 8.2 P1 — Tuần 2–3

1. Readiness probe audit (payment, checkout, catalog, cart).
2. Runbook: checkout dependency failure.
3. Runbook: Kafka lag spike.
4. Runbook: LLM rate limit / inaccurate response (flagd paths).
5. Log severity alignment (metric error ↔ log level).

---

## 9. Kết luận

Hệ thống TechX Corp Platform **đã có nền observability đủ tốt** để bắt đầu xây AIOps (detect → correlate → alert → runbook). Tuy nhiên, đánh giá baseline cho thấy **luồng checkout cực kỳ fragile** khi bất kỳ dependency nào unavailable, và **các pattern sự cố lịch sử (INC-1/2/3) vẫn chưa được mitigate ở tầng cấu hình/code**.

Điểm đáng chú ý khác: **tầng LLM thiếu visibility trực tiếp trong Jaeger**, và **flagd tạo ra nhiều incident path** mà AIOps cần map trước khi vận hành dưới áp lực thật.

**Khuyến nghị cho mentor:** approve backlog P0 tập trung vào checkout SLO protection, DB pool alerting, flagd incident mapping, và topology map — đây là nền cho vòng AIOps tự động (detect → match runbook → remediate → verify) trong các sprint tiếp theo.

---

## Phụ lục A — Evidence tham chiếu


| Loại                         | Nguồn                                                                                         | Thời điểm         |
| ---------------------------- | --------------------------------------------------------------------------------------------- | ----------------- |
| Grafana APM (checkout)       | Dashboard Demo (EKS)                                                                          | 09/07/2026 ~14:00 |
| Grafana PostgreSQL           | Dashboard Demo (EKS)                                                                          | 09/07/2026 ~14:00 |
| Grafana OTel Collector       | Dashboard Demo (EKS)                                                                          | 09/07/2026 ~14:00 |
| Grafana Spanmetrics          | Dashboard Demo (EKS)                                                                          | 09/07/2026 ~14:00 |
| Jaeger browse/recommendation | `frontend-proxy: GET` (~29.6ms, 10 spans, depth 4)                                            | 09/07/2026 ~14:19 |
| Jaeger checkout success      | `load-generator: user_checkout_single` (~~863.7ms) / `user_checkout_multi` (~~1.6s, 54 spans) | 09/07/2026 ~14:21 |
| Jaeger AI                    | `load-generator: user_ask_product_ai_assistant` (~63.35ms, 15 spans, depth 12)                | 09/07/2026 ~14:24 |
| Accounting logs              | `Accounting.Consumer` consume order liên tục, không thấy error trong tail log                 | 09/07/2026 ~14:24 |
| Source code                  | `product-catalog/main.go`, `database.py`, `demo.flagd.json`                                   | Static review     |
| Helm config                  | `techx-corp-chart/values.yaml`                                                                | Static review     |


## Phụ lục B — Giới hạn đánh giá

- Đánh giá trên **EKS namespace `techx-tf2`** qua `kubectl port-forward`; chưa có ingress/public endpoint riêng cho observability.  
- Chưa thực hiện load test peak — INC-1 chưa được reproduce.  
- Đánh giá Kafka consumer mới ở mức spot-check (tail log + trace history), chưa có bài test lag chuyên biệt theo tải cao.  
- Một số metric flagd EventStream có latency cao do **long-polling** — cần alert rule riêng, không coi là incident mặc định.

---

*Báo cáo này là deliverable Week 1 — AIOps System Weak Points Assessment. File làm việc chi tiết: `AIOPS-W1-WEAK-POINTS-ASSESSMENT.md`.*

