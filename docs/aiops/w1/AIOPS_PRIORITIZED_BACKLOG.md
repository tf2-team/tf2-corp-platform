# AIOps Backlog Ưu Tiên — Tổng Hợp Đa Nguồn

**Công thức xếp hạng:** Ưu tiên = Rủi ro (Khả năng xảy ra × Mức nghiêm trọng) × Tác động Business  
**Nguồn dữ liệu:**
- **Phúc** — [signal_for_anomoly.md] (Danh mục tín hiệu telemetry)
- **Hưng** — [weakness.md] (Điểm yếu hệ thống, findings F-01 → F-09)
- **Khánh** — [AI_FINDINGS_AIOPS.md] (Khoảng trống quan sát tầng AI từ phân tích mã nguồn)

**Tài liệu tham chiếu:** [SLO.md] · [BUDGET.md] · [INCIDENT_HISTORY.md] · [ARCHITECTURE.md]

---

## Bảng tổng hợp xếp hạng

| Hạng | ID | Tên hạng mục | Ưu tiên | Rủi ro (L×S) | Business Impact | Nguồn phát hiện |
|---|---|---|---|---|---|---|
| 1 | OPS-01 | Alert checkout SLO (p95 + error rate) | **P0** | Cao×Cao | Rất Cao | Hưng (F-07), Phúc (§1,§2) |
| 2 | OPS-02 | Alert DB connection saturation | **P0** | Cao×Cao | Cao | Hưng (F-01), Khánh (§5), Phúc (§3) |
| 3 | OPS-03 | Checkout dependency failure detection | **P0** | Cao×Cao | Rất Cao | Hưng (F-07, F-02), Phúc (§2) |
| 4 | OPS-04 | Flag inventory + incident signature mapping | **P0** | Cao×Trung bình | Cao | Hưng (F-06), Khánh (§3) |
| 5 | OPS-05 | LLM observability dashboard & alerting | **P0** | Trung bình×Cao | Trung bình | Hưng (F-05), Khánh (§2,§4), Phúc (§5) |
| 6 | OPS-06 | Kafka consumer lag + error alert | **P0** | Trung bình×Trung bình | Trung bình | Hưng (F-04), Phúc (§4) |
| 7 | OPS-07 | Service topology / blast-radius map | **P0** | — | Cao (nền tảng) | Hưng (§8.1) |
| 8 | OPS-08 | Readiness probe audit | **P1** | Trung bình×Trung bình | Trung bình | Hưng (F-03) |
| 9 | OPS-09 | Log severity chuẩn hóa | **P1** | Thấp×Trung bình | Thấp–Trung bình | Hưng (F-08), Phúc (§2.C) |
| 10 | OPS-10 | flagd EventStream alert tuning | **P1** | Thấp×Thấp | Thấp | Hưng (F-09) |

---

## Chi tiết từng hạng mục

### 1. [P0] OPS-01 — Alert checkout SLO (p95 latency + error rate)

**Nguồn:** Hưng (F-07: checkout hard-depends on shipping, no fallback) · Phúc (§1: `rpc_server_duration_milliseconds_bucket`, §2: `rpc_server_duration_milliseconds_count`)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Cao** — Baseline EKS ghi nhận `PlaceOrder` p95 ~4.55s, đã rất gần ngưỡng gây ảnh hưởng trải nghiệm. Khi tải tăng (flash sale, BTC inject incident), latency sẽ vượt ngưỡng.
  - *Mức nghiêm trọng:* **Cao** — Checkout là luồng ra tiền, vi phạm SLO ≥ 99.0% = mất doanh thu trực tiếp.
- **Tác động Business:**
  - *SLO:* SLO checkout ≥ 99.0% success (quan trọng nhất). p95 browse < 1s cũng bị ảnh hưởng nếu checkout chậm.
  - *Ngân sách:* Không tốn thêm chi phí hạ tầng — chỉ dựng alert rule trên Prometheus/Grafana đã có.
  - *Khách hàng:* Checkout chậm/lỗi → khách bỏ giỏ, mất đơn, giảm uy tín.
- **Hướng tiếp cận:**
  - Dùng metric `rpc_server_duration_milliseconds_bucket` (Phúc §1) để tạo recording rule p95/p99 cho `PlaceOrder`.
  - Dùng `rpc_server_duration_milliseconds_count` với filter `rpc_grpc_status_code!="0"` (Phúc §2) để tính error ratio.
  - Đặt alert khi error ratio > 1% (đã ăn vào error budget) hoặc p95 > ngưỡng (ví dụ 3s).
  - Gắn vào Grafana dashboard + kênh Slack/PagerDuty.
- **Ước lượng công sức:** Nhỏ (1–2 ngày). Chỉ cần viết PromQL rule + Grafana alert contact point.

---

### 2. [P0] OPS-02 — Alert DB connection saturation

**Nguồn:** Hưng (F-01: DB connection pool chưa tune, `product-reviews` dùng per-request connect) · Khánh (§5: `psycopg2` không dùng pool, mở/đóng connection mỗi request) · Phúc (§3: `postgresql_backends`, `db_client_connections_usage`)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Cao** — Đã từng xảy ra (INC-1). Code `product-reviews` tạo connection mới mỗi lần gọi DB (Khánh §5). `product-catalog` (Go) cũng không set `SetMaxOpenConns` (Hưng F-01).
  - *Mức nghiêm trọng:* **Cao** — Pool cạn kéo theo checkout bị timeout (INC-1: tỷ lệ checkout tụt xuống ~95%).
- **Tác động Business:**
  - *SLO:* Vi phạm SLO checkout ≥ 99.0% và browse ≥ 99.5%.
  - *Ngân sách:* Alert không tốn thêm, nhưng fix gốc (thêm pool) cần thêm effort dev.
  - *Khách hàng:* Giống INC-1 — request xếp hàng chờ connection rồi timeout, khách bỏ giỏ.
- **Hướng tiếp cận:**
  - **Alert phía server:** Dùng `postgresql_backends` (Phúc §3) để cảnh báo khi active connections tiến gần giới hạn `max_connections` của PostgreSQL.
  - **Alert phía client (Go services):** Dùng `db_client_connections_usage / db_client_connections_max` (Phúc §3) để đo tỷ lệ bão hòa pool.
  - **Alert chờ connection:** Dùng `rate(db_client_connections_wait_total[5m])` để phát hiện request phải chờ connection.
  - Kết hợp `db.connection.wait_ms` trên Jaeger (Phúc §3.B) để drill-down khi alert bắn.
- **Ước lượng công sức:** Nhỏ (1–2 ngày) cho alert. Trung bình nếu muốn fix gốc (thêm connection pool cho `product-reviews`).

---

### 3. [P0] OPS-03 — Checkout dependency failure detection

**Nguồn:** Hưng (F-07: checkout hard-depends on shipping, no fallback; F-02: single-replica SPOF) · Phúc (§2: error rate per method)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Cao** — Checkout phụ thuộc cứng vào chuỗi: cart → product-catalog → currency → shipping → payment → email → kafka. Bất kỳ dependency nào chết đều kéo checkout theo. Tất cả đang chạy `replicas: 1` (Hưng F-02).
  - *Mức nghiêm trọng:* **Cao** — Vi phạm SLO checkout ngay lập tức khi dependency không khả dụng.
- **Tác động Business:**
  - *SLO:* Checkout ≥ 99.0%. Blast-radius rất lớn — 1 pod chết = cả luồng ra tiền dừng.
  - *Ngân sách:* Alert không tốn thêm. Tăng replica cho critical services có thể tốn thêm compute nhưng nằm trong trần $300/tuần nếu chỉ tăng cho 2–3 service (checkout, payment, cart).
  - *Khách hàng:* Không thể đặt hàng cho đến khi phục hồi. Liên quan trực tiếp INC-2 (mất giỏ khi node lên lịch lại) và INC-3 (payment lỗi lúc deploy).
- **Hướng tiếp cận:**
  - Dùng `rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}` (Phúc §2) tạo alert cho từng dependency trên checkout path (shipping, payment, cart, currency).
  - Kết hợp `traces_span_metrics_calls_total{status_code="STATUS_CODE_ERROR"}` (Phúc §2) để bắt lỗi span-level.
  - Dùng Jaeger trace attribute `service.name` + `otel.status_code="ERROR"` để xây rule tự động phát hiện dependency nào đang lỗi.
  - Xây runbook: khi dependency X lỗi → AIOps gợi ý restart pod / kiểm tra readiness / escalate.
- **Ước lượng công sức:** Trung bình (2–3 ngày). Cần viết alert rules cho mỗi dependency + xây runbook matching ban đầu.

---

### 4. [P0] OPS-04 — Flag inventory + incident signature mapping

**Nguồn:** Hưng (F-06: 14+ flagd-controlled failure paths chưa map alert/runbook) · Khánh (§3: flagd hooks trong product-reviews)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Cao** — BTC sẽ inject incident qua flagd bất cứ lúc nào. 14+ flag paths đều có thể bị bật mà team không có detection.
  - *Mức nghiêm trọng:* **Trung bình** — Nếu không detect kịp, MTTD tăng cao và team sẽ phản ứng chậm. Không trực tiếp vi phạm SLO nhưng kéo dài thời gian ảnh hưởng.
- **Tác động Business:**
  - *SLO:* Gián tiếp — flag inject có thể gây vi phạm SLO checkout, browse, AI. Nếu không detect, thời gian vi phạm kéo dài.
  - *Ngân sách:* Không tốn thêm chi phí hạ tầng.
  - *Khách hàng:* Trải nghiệm bị ảnh hưởng cho đến khi team phát hiện và contain.
- **Hướng tiếp cận:**
  - Liệt kê toàn bộ 14+ flags trong `demo.flagd.json`, document: tên flag → symptom → service bị ảnh hưởng → severity dự kiến.
  - Với flags đã biết trên AI path (`llmRateLimitError`, `llmInaccurateResponse` — Khánh §3): tạo alert dựa trên log pattern "feature flag: True" (Phúc §5.C).
  - Map mỗi flag vào một runbook stub (detect → diagnose → contain — **KHÔNG disable flag** theo RULES).
  - Dùng log query trên OpenSearch: `body.message: "feature flag"` (Phúc §5.C) để giám sát trạng thái flags theo thời gian thực.
- **Ước lượng công sức:** Trung bình (2–3 ngày). Phần lớn là đọc `demo.flagd.json` + viết tài liệu mapping + tạo alert rules.

---

### 5. [P0] OPS-05 — LLM observability dashboard & alerting

**Nguồn:** Hưng (F-05: LLM service không có OTel instrumentation) · Khánh (§2: metrics.py chỉ có 2 counter, thiếu LLM latency/token/error; §4: nhánh gọi LLM thực tế không có try/except và timeout) · Phúc (§5: `gen_ai_client_operation_duration_milliseconds_bucket`, `gen_ai_client_token_usage_total`, trace attributes `gen_ai.*`)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Trung bình** — LLM đang là mock, nhưng khi cắm model thật (yêu cầu AIE), rủi ro rate limit, timeout, và chi phí token sẽ xuất hiện ngay.
  - *Mức nghiêm trọng:* **Cao** — Không có timeout ở nhánh LLM thật (Khánh §4), exception sẽ ném thẳng lên gRPC và có thể làm hỏng trang sản phẩm (ảnh hưởng SLO browse). Không đo được latency/token → không kiểm soát được chi phí.
- **Tác động Business:**
  - *SLO:* AI summary là best-effort, nhưng SLO yêu cầu "không hiển thị tóm tắt sai lệch cho khách" và không được kéo trang sản phẩm chết theo (SLO browse p95 < 1s).
  - *Ngân sách:* Token usage không đo → không kiểm soát chi phí LLM trong trần $300/tuần.
  - *Khách hàng:* Trang sản phẩm treo/lỗi khi LLM chậm ảnh hưởng trải nghiệm mua hàng.
- **Hướng tiếp cận:**
  - **Dashboard:** Dùng các metric Phúc đã catalog: `gen_ai_client_operation_duration_milliseconds_bucket` (p95/p99 latency), `gen_ai_client_token_usage_total` (tiêu thụ token), `app_ai_assistant_counter_total` (tổng request).
  - **Alert LLM latency:** `histogram_quantile(0.99, ...) > 5000` (LLM chậm hơn 5s cần cảnh báo).
  - **Alert LLM error rate:** `gen_ai_client_operation_duration_count{status_code="error"} / total` (Phúc §5).
  - **Alert token consumption:** Rate token usage vượt ngưỡng → cảnh báo chi phí.
  - Sử dụng Jaeger trace attributes `gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens` (Phúc §5.B) để drill-down khi cần RCA.
  - Log pattern alert: `"openai.RateLimitError"`, `"openai.APITimeoutError"` (Phúc §5.C).
- **Ước lượng công sức:** Nhỏ–Trung bình (2 ngày). Metrics đã có sẵn từ OTel auto-instrumentation, chỉ cần dựng dashboard Grafana + alert rules.

---

### 6. [P0] OPS-06 — Kafka consumer lag + error alert

**Nguồn:** Hưng (F-04: Kafka consumer path có tín hiệu lỗi gián đoạn) · Phúc (§4: `kafka_consumer_group_lag`, `kafka_consumer_group_lag_sum`, `kafka_topic_partition_offset`)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Trung bình** — Baseline EKS chưa thấy lỗi ổn định (Hưng), nhưng flag `kafkaQueueProblems` có thể inject lag bất cứ lúc nào.
  - *Mức nghiêm trọng:* **Trung bình** — Ảnh hưởng luồng async (accounting, fraud-detection). Đơn hàng vẫn được đặt nhưng không được ghi sổ hoặc kiểm tra gian lận kịp thời.
- **Tác động Business:**
  - *SLO:* Không trực tiếp vi phạm SLO checkout (luồng sync vẫn thành công), nhưng ảnh hưởng tính toàn vẹn dữ liệu kế toán và phát hiện gian lận.
  - *Ngân sách:* Không tốn thêm chi phí.
  - *Khách hàng:* Gián tiếp — nếu fraud-detection bị lag, đơn hàng gian lận có thể lọt qua.
- **Hướng tiếp cận:**
  - Dùng `sum(kafka_consumer_group_lag) by (group, topic)` (Phúc §4) để đo tổng lag.
  - Dùng `rate(kafka_topic_partition_offset[5m]) - rate(kafka_consumer_group_offset[5m])` (Phúc §4) để đo consumer có đang bị tụt lại hay không.
  - Tạo alert khi lag tổng > ngưỡng (ví dụ 1000 messages) hoặc khi rate tiêu thụ < rate sản xuất kéo dài > 5 phút.
  - Log pattern alert: `"Failed to send message to Kafka"`, `"consumer lag too high"` (Phúc §4.C).
- **Ước lượng công sức:** Nhỏ (1–2 ngày). Metric đã có sẵn từ `kafkametrics` receiver.

---

### 7. [P0] OPS-07 — Service topology / blast-radius map

**Nguồn:** Hưng (§8.1: đề xuất topology map v1 cho checkout path)

- **Rủi ro:** Đây là công cụ nền tảng phục vụ RCA và runbook matching, không đánh giá rủi ro trực tiếp.
- **Tác động Business:**
  - *SLO:* Giảm MTTD/MTTR cho mọi sự cố trên luồng checkout.
  - *Ngân sách:* Không tốn thêm chi phí.
  - *Khách hàng:* Gián tiếp — phục hồi nhanh hơn = ảnh hưởng ít hơn.
- **Hướng tiếp cận:**
  - Vẽ bản đồ dependency cho checkout path: checkout → {cart, product-catalog, currency, shipping/quote, payment, email, kafka}.
  - Đánh dấu SPOF (tất cả đang `replicas: 1`).
  - Map mỗi node vào: metric để detect lỗi + runbook phản ứng + blast-radius dự kiến (nếu node này chết, ai bị ảnh hưởng).
  - Dùng Jaeger service dependency graph làm nền, bổ sung bằng phân tích mã nguồn.
- **Ước lượng công sức:** Nhỏ–Trung bình (1–2 ngày). Phần lớn là tổng hợp tài liệu + vẽ diagram.

---

### 8. [P1] OPS-08 — Readiness probe audit

**Nguồn:** Hưng (F-03: gRPC health check luôn trả SERVING, không phản ánh dependency)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Trung bình** — Xảy ra mỗi lần deploy hoặc khi pod bị reschedule.
  - *Mức nghiêm trọng:* **Trung bình** — Traffic đi vào pod chưa sẵn sàng gây lỗi tạm thời (INC-3).
- **Tác động Business:**
  - *SLO:* Ảnh hưởng nhẹ đến checkout/browse SLO trong thời gian deploy (vài phút).
  - *Ngân sách:* Không tốn thêm chi phí.
  - *Khách hàng:* Một phần request lỗi trong thời gian deploy.
- **Hướng tiếp cận:**
  - Audit readiness probe cho các service trên checkout critical path: payment, checkout, product-catalog, cart.
  - Đề xuất sửa health check để kiểm tra dependency thực sự (ví dụ: checkout chỉ trả SERVING khi kết nối được đến cart, payment, shipping).
  - Chỉ cart hiện đã có readiness logic thật (qua flagd `failedReadinessProbe`).
- **Ước lượng công sức:** Trung bình (2–3 ngày). Cần sửa code health check ở mỗi service.

---

### 9. [P1] OPS-09 — Log severity chuẩn hóa

**Nguồn:** Hưng (F-08: log severity chưa chuẩn hóa giữa metric/log) · Phúc (§2.C: `severity_text` trong OpenSearch)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Thấp** — Không gây sự cố trực tiếp.
  - *Mức nghiêm trọng:* **Trung bình** — Khó triage khi incident, MTTD chậm hơn.
- **Tác động Business:**
  - *SLO:* Gián tiếp — MTTD chậm → thời gian vi phạm SLO kéo dài.
  - *Ngân sách:* Không ảnh hưởng.
  - *Khách hàng:* Gián tiếp — phản ứng chậm khi sự cố.
- **Hướng tiếp cận:**
  - Rà soát log level giữa các service (Python dùng `logging`, Go dùng `log`, Node.js...) và chuẩn hóa mapping: ERROR → metric error, WARN → metric anomaly.
  - Dùng OpenSearch query trên field `severity_text` (Phúc §2.C) để tạo dashboard correlation giữa log severity và metric error rate.
- **Ước lượng công sức:** Nhỏ (1–2 ngày). Chủ yếu là chuẩn hóa convention, không sửa nhiều code.

---

### 10. [P1] OPS-10 — flagd EventStream alert tuning

**Nguồn:** Hưng (F-09: flagd EventStream latency cao p95 15s do long-poll)

- **Rủi ro:**
  - *Khả năng xảy ra:* **Thấp** — Không phải lỗi thật, chỉ là đặc tính long-polling.
  - *Mức nghiêm trọng:* **Thấp** — Gây false positive alert nếu không tune đúng.
- **Tác động Business:**
  - *SLO:* Không ảnh hưởng.
  - *Ngân sách:* Không ảnh hưởng.
  - *Khách hàng:* Không ảnh hưởng trực tiếp. Chỉ gây nhiễu cho đội vận hành.
- **Hướng tiếp cận:**
  - Loại trừ `flagd EventStream` span khỏi alert rule latency tổng quan.
  - Hoặc tạo rule riêng với ngưỡng cao hơn (>30s) phù hợp với hành vi long-poll.
- **Ước lượng công sức:** Rất nhỏ (nửa ngày). Chỉ thêm exclude filter vào PromQL.

---

## 🛑 Các hạng mục tạm gác lại (Deferred) & Lý do

### 1. Load test peak để reproduce INC-1
- **Lý do gác lại:** Hưng đánh giá INC-1 chưa reproduce được trên EKS vì chưa chạy load test peak. Tuy nhiên, việc chạy load test peak cần phối hợp với DevOps/CloudOps để đảm bảo không phá hệ thống đang chạy, và nằm ngoài phạm vi đánh giá Tuần 1. Alert DB saturation (OPS-02) đóng vai trò "lưới an toàn" trong khi chờ load test.

### 2. Tăng replica cho critical services (fix SPOF)
- **Lý do gác lại:** Hưng (F-02) phát hiện toàn bộ services đang `replicas: 1`, nhưng tăng replica ảnh hưởng trực tiếp đến ngân sách $300/tuần (BUDGET.md). Cần tính toán chi phí cụ thể (mỗi replica tốn bao nhiêu compute) và quyết định scale service nào trước (checkout, payment, cart là ưu tiên). Hiện tại đang focus vào detect + alert trước, fix gốc sẽ theo sau khi có số liệu.

### 3. Thêm OTel instrumentation trực tiếp vào service `llm` (app.py)
- **Lý do gác lại:** Hưng (F-05) phát hiện `llm` không có OTel, Jaeger không nhìn thấy nó như service riêng. Tuy nhiên, Phúc đã catalog được rằng OTel auto-instrumentation của OpenAI SDK trong `product-reviews` đã phát ra các metric `gen_ai_client_*` đủ để quan sát tầng LLM từ phía client. Việc instrument trực tiếp `llm/app.py` là "nice to have" nhưng không cấp bách — ưu tiên dùng signal từ `product-reviews` trước (OPS-05).

### 4. Fix gốc connection pool cho `product-reviews` (Python)
- **Lý do gác lại:** Khánh (§5) phát hiện `database.py` dùng `psycopg2.connect` mỗi request. Fix gốc cần sửa code thành `psycopg2.pool.ThreadedConnectionPool`. Đây thuộc trách nhiệm của nhóm Dev/AIE, không phải AIOps. AIOps sẽ alert khi pool cạn (OPS-02) để đảm bảo phát hiện kịp, và escalate cho Dev khi alert bắn.

### 5. PII redaction trong log/trace
- **Lý do gác lại:** Khánh (§2) phát hiện nguyên văn câu hỏi user được ghi vào trace (`app.product.question`) và log (`messages`). Đây là vấn đề bảo mật quan trọng nhưng thuộc phạm vi AIE (chống rò rỉ PII), không phải AIOps. AIOps sẽ ghi nhận và escalate cho nhóm AIE xử lý.

### 6. Runbook tự động hóa (auto-remediation)
- **Lý do gác lại:** Mục tiêu cuối cùng của AIOps là detect → diagnose → remediate → verify tự động. Tuy nhiên, trước khi tự động hóa, cần có nền tảng alert + topology map + flag inventory (OPS-01 → OPS-07) hoàn thiện. Tự động hóa sẽ được xây trong sprint 2–3 dựa trên nền tảng này.

---

## Tổng kết

**Sprint 1 (P0 — 7 items):** Tập trung vào **detect và alert** cho các rủi ro nghiêm trọng nhất: checkout SLO, DB saturation, dependency failure, flagd incident mapping, LLM observability, Kafka lag, và topology map. Đây là nền tảng bắt buộc trước khi xây bất kỳ cơ chế tự động hóa nào.

**Sprint 2 (P1 — 3 items):** Cải thiện chất lượng giám sát: readiness probe, log severity, và alert tuning. Bắt đầu viết runbook cho các kịch bản phổ biến.

**Sprint 3+:** Tự động hóa: runbook matching → auto-remediation → verification loop.
