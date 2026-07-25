# 4. Báo cáo Engine: Kiến trúc & Thuật toán

Mục tiêu phần này: mô tả **ngắn nhưng đủ thông tin thuật ngữ** để bất kỳ ai đọc cũng hiểu được engine hoạt động thế nào, không cần hỏi lại "EWMA/IQR/RRF là gì".

## 4.1 Kiến trúc tổng thể — 12 khối xử lý tuần tự

```text
1. Thu thập/nhận tín hiệu (Prometheus polling + Grafana webhook)
2. Signal qualification gate (verified/missing/stale/invalid/fallback-only)
3. Normalize dữ liệu (unit, label, window, naming)
4. Feature builder (SLO 24h, diagnostic 5m/15m, baseline robust, freshness)
5. Detector engine (SLO / no-data / dependency / DB / anomaly) -> Candidate event
6. Correlation + likely dependency ranking -> gom nhiều candidate thành 1 vụ hợp lý
7. On-demand enrichment (Jaeger / OpenSearch / Kubernetes API, bounded, sau khi có candidate)
8. Incident manager (tạo/dedup/update timeline/occurrence_count/state/audit)
9. Deduplicate, attach runbook, notification outbox -> TF2 on-call
10. Policy + remediation engine (dry-run / blocked / optional live executor)
11. Verification (query lại để resolve/escalate, không dùng cảm tính)
12. SQLite WAL/PVC (persist toàn bộ: incidents, events, observations, notification_outbox, actions, approvals, audit_events)
```

Nguồn: `src/aio/docs/blocks/1..12.md`, `src/aio/docs/Infra.md`, `src/aio/docs/mandates/7a/ADR-DETECT-001.md`.

Input contract chuẩn hoá thành `MetricSeries { service, metric, signal_id, points }` — mọi detector phía sau chỉ làm việc với object này, không quan tâm dữ liệu gốc từ Prometheus/CSV dataset hay nguồn nào.

## 4.2 Baseline & Anomaly scoring — các thuật toán đang dùng

Code: `src/aio/aiops/anomaly/stats.py` (helper thống kê), `src/aio/aiops/anomaly/v001.py` (detector thật, class `V001AnomalyEngine`).

| Thuật toán | Là gì | Dùng để làm gì trong engine |
| --- | --- | --- |
| **Median / IQR (Interquartile Range)** | `median` = giá trị trung vị; `IQR` = khoảng giữa quartile 75% và 25% (đo độ phân tán, không bị outlier kéo lệch như độ lệch chuẩn) | Baseline chính: `score = |giá_trị_hiện_tại - median(lịch_sử)| / IQR(lịch_sử)`. Nếu IQR = 0 thì dùng fallback khác 0 để tránh chia 0 |
| **Robust score / robust z-score** | Điểm bất thường tính theo công thức trên (dùng median/IQR thay vì mean/stddev) | Là baseline "nhẹ", không cần train model, dùng được ngay trên dataset offline hoặc telemetry thật |
| **EWMA (Exponentially Weighted Moving Average)** | Trung bình trượt có trọng số giảm dần theo thời gian — điểm gần hiện tại có trọng số cao hơn điểm cũ | Làm mượt (smoothing) time series trước khi tính residual, giảm nhiễu ngắn hạn |
| **STL-style residual (Seasonal-Trend decomposition)** | Tách time series thành 3 phần: trend (xu hướng), seasonal (chu kỳ), residual (phần dư) | Sau khi tách, phần **residual** mới được dùng để phát hiện bất thường thật — tránh báo động giả do biến động chu kỳ bình thường (ví dụ giờ cao điểm) |
| **`EwmaStlDetector`** (class trong `v001.py`) | Kết hợp EWMA + STL residual thành 1 detector | Detector chính cho các metric có tính chu kỳ (latency, error rate theo giờ) |
| **`RobustDriftDetector`** (class trong `v001.py`) | Phát hiện "trôi" (drift) khỏi baseline robust theo thời gian, không chỉ so 1 điểm | Bắt các trường hợp lệch dần (gradual degradation), không chỉ spike tức thời |
| **`ServiceIsolationForestDetector`** | IsolationForest — thuật toán ML không giám sát, cô lập điểm bất thường bằng cách đếm số lần "cắt" cần để tách điểm đó ra khỏi phần còn lại của dữ liệu | Gộp nhiều metric của **cùng 1 service** thành 1 điểm bất thường tổng hợp (service-level scoring), bắt các bất thường không lộ rõ trên từng metric riêng lẻ |
| **BARO / BOCPD (Bayesian Online Change Point Detection)** | Thuật toán phát hiện "điểm đổi" (changepoint) trong dữ liệu theo thời gian thực, dựa trên xác suất Bayes | Tín hiệu **hỗ trợ đa biến** (corroborating signal) để xác nhận thêm — **không** phải trigger chính, không dùng để tự động remediation |
| **Drain3 (log template mining)** | Thuật toán clustering log theo template (nhóm các log giống cấu trúc, khác giá trị) | Rút log thành template để so sánh nhanh, tránh phải đọc log thô khi enrich bằng OpenSearch |

**Detector theo loại rule** (không phải thống kê, mà theo luật cố định):

| Detector | Rule |
| --- | --- |
| Official SLO detector | Ví dụ `checkout_bad_ratio_24h > 1%` → fire ngay, **không chờ** anomaly/correlation |
| No-data detector | Phát hiện Prometheus query fail, series mất, sample cũ, scheduler bị stall |
| Dependency detector | Tìm lỗi của 1 service do downstream (ví dụ checkout lỗi do payment) |
| DB detector | Phát hiện PostgreSQL backend pressure (connection pool, v.v.) |

Tất cả detector **không tạo incident trực tiếp** — chúng chỉ sinh ra **Candidate event** (đề xuất sự kiện đáng chú ý, có đầy đủ metadata: detector ID, signal, severity, value, threshold, window, quality, runbook suggestion).

## 4.3 Correlation & RCA ranking

Candidate event → **Correlation + likely dependency ranking**, mục tiêu: gom nhiều tín hiệu liên quan thành **1 incident hợp lý**, tránh "alert storm" (nhiều alert rời rạc cho cùng 1 vấn đề gốc).

Trọng số ranking hiện tại (`config/hyperparameters.json → correlation.weights`):

| Yếu tố | Trọng số | Ý nghĩa |
| --- | ---: | --- |
| `verified_primary_signal` | 0.25 | Signal chính đã qua qualification gate (verified) |
| `temporal_precedence` | 0.20 | Thứ tự thời gian — cái nào xảy ra trước có khả năng là nguyên nhân |
| `topology_path` | 0.25 | Dependency có nằm trên đường gọi (topology path) của service bị ảnh hưởng không |
| `operation_specificity` | 0.10 | Lỗi có cụ thể theo operation/method không |
| `trace_log_kubernetes_corroboration` | 0.20 | Có được trace/log/K8s xác nhận thêm không |
| `stale_or_missing_evidence_penalty` | −0.30 | Trừ điểm nếu bằng chứng thiếu/cũ |

Ngưỡng liên quan: `confidence_threshold = 0.5` (dưới ngưỡng này không kết luận `likely_dependency`, trả về `unknown`), `topology_max_hops = 1` (chỉ xét dependency cách 1 hop trên topology).

**RCA ranking (root-cause top-K)** — code: `src/aio/aiops/rca/engine.py` (`V001RcaEngine`). Kết hợp:

| Thành phần | Tham số (`hyperparameters.json → rca`) | Ý nghĩa |
| --- | --- | --- |
| Graph/PageRank | `damping = 0.85`, `pagerank_weight = 0.7` | Dùng thuật toán PageRank trên graph topology để tính "trọng số trung tâm" của mỗi service — service càng nằm giữa nhiều đường gọi càng dễ bị nghi là root cause |
| Earliest drift | trọng số `0.5` trong `combined.weights` | Service nào có dấu hiệu bất thường (drift) **sớm nhất về thời gian** được ưu tiên là root cause |
| Correlation score | trọng số `0.1` trong `combined.weights` | Điểm correlation ở mục 4.3 trên |
| Graph score | trọng số `0.3` trong `combined.weights` | Điểm graph/PageRank ở trên |
| **RRF (Reciprocal Rank Fusion)** | `rrf_k = 20` | Kỹ thuật gộp nhiều bảng xếp hạng (ranking) khác nhau thành 1 bảng xếp hạng cuối, bằng cách lấy nghịch đảo hạng (`1 / (k + rank)`) rồi cộng lại — tránh 1 phương pháp đơn lẻ áp đảo kết quả |
| `top_k = 5` | Số lượng root-cause candidate trả ra tối đa |

Kết quả RCA **không bao giờ tuyên bố "chắc chắn root cause"** nếu chưa đủ bằng chứng — chỉ trả về `likely_dependency = <service>` kèm `confidence`, hoặc `unknown` nếu dưới ngưỡng.

## 4.4 Vòng đời Incident: dedup → runbook → notify → policy → verify

| Bước | Cơ chế | Chi tiết |
| --- | --- | --- |
| **Fingerprint / dedup** | `environment + detector_id + customer_flow + primary_service + likely_dependency` | Không dùng timestamp/metric value/pod name/trace ID (các giá trị đổi liên tục) → cùng 1 vấn đề chỉ tạo 1 incident, các lần fire sau chỉ tăng `occurrence_count` |
| **Cooldown/dedup window** | `notification_cooldown_seconds = 300`, `rca_dedup_seconds = 300`, `slo_dedup_seconds = 300`, `count_reset_seconds = 300` | Tránh spam alert trong vòng 5 phút cho cùng 1 incident |
| **Attach runbook** | Runbook cố định theo `detector_id` (ví dụ `RB-CHECKOUT-DEPENDENCY`, `RB-CHECKOUT-SLO`) từ `src/aiops/runbooks/` | Không tự sinh runbook bằng LLM/tự do |
| **Notification outbox** | Ghi intent gửi notification **cùng transaction** với incident, worker gửi sau | Đảm bảo không mất alert nếu crash giữa chừng |
| **Policy + remediation engine** | 3 nhánh: (1) **dry-run** (mặc định — chỉ ghi đề xuất, không mutate gì); (2) **blocked** (nếu target là DB, chỉ 1 replica, thiếu approval/rollback, hoặc là đường protected flagd → block + escalate); (3) **optional live executor** (chỉ bật khi có ADR riêng `ADR-LIVE-001`, RBAC hẹp, có rollback rõ ràng — không phải mặc định) | Runtime bình thường **luôn read-only** |
| **Verification** | Query lại theo điều kiện định trước, cần **đủ số lần pass liên tiếp** mới resolve | Nếu telemetry missing/stale/fail → không được claim "recovered", phải escalate hoặc rollback (nếu đã định nghĩa trước) |
| **Persist / audit** | SQLite WAL + PVC: `incidents`, `incident_events`, `observations`, `notification_outbox`, `actions`, `approvals`, `audit_events`, `scheduler_checkpoints` | Sống sót qua pod restart, là evidence cho Ops Review/COE |

## 4.5 Ví dụ luồng thật (payment lỗi → checkout fail)

```text
1. Prometheus thấy checkout error tăng + payment span error tăng.
2. Qualification gate xác nhận signal verified/fresh.
3. Feature builder tính checkout error ratio 5m, checkout SLO 24h, payment error rate.
4. Dependency detector tạo candidate event.
5. Correlation thấy payment nằm trên checkout path, lỗi cùng thời điểm -> likely_dependency=payment.
6. Enrichment: query Jaeger/OpenSearch/K8s (on-demand).
7. Incident manager tạo incident: checkout, likely_dependency=payment.
8. Gắn runbook RB-CHECKOUT-DEPENDENCY.
9. Gửi notification cho TF2 on-call qua outbox.
10. Policy engine: dry-run, không restart gì.
11. Verification tiếp tục theo dõi checkout/payment.
12. Đủ số lần pass liên tiếp -> resolve; nếu không -> escalate.
```

## 4.6 Auto-detector-generation

Ngoài các detector khai báo tay (`ops01_checkout_slo`, `ops03_checkout_payment_dependency`...), runtime còn có **`auto_detector_generation_enabled = true`** (`aiops/config/runtime.py`) — tự sinh detector `auto_<service>_error_rate` / `auto_<service>_latency_p95` / `auto_<service>_latency_p99` cho từng service trong registry, dùng threshold mặc định (`default_error_rate = 0.05`, `default_latency_slo` theo override từng service, ví dụ `checkout=2s`, `currency=0.3s`, `llm=5s`). Đây là lý do một số service (`recommendation`, `product-catalog`...) có thể tự phát sinh incident dù không có detector khai báo tay riêng cho chúng.

## 4.7 Glossary — thuật ngữ hay bị hỏi lại

| Thuật ngữ | Giải thích ngắn |
| --- | --- |
| **SLO (Service Level Objective)** | Mục tiêu chất lượng dịch vụ chính thức, ví dụ "checkout success ≥ 99%" |
| **Error budget / burn-rate** | Error budget = phần "lỗi được phép" trong 1 khoảng thời gian trước khi vi phạm SLO. Burn-rate = tốc độ tiêu error budget đó, càng cao càng sắp vi phạm SLO |
| **Hard-rule** | Rule định lượng rõ ràng (ví dụ `bad_ratio_24h > 1%`), không cần AI/anomaly để quyết định fire |
| **Candidate event** | Đề xuất sự kiện đáng chú ý do detector sinh ra, chưa phải incident chính thức |
| **Likely_dependency** | Service bị nghi là nguyên nhân gốc, kèm điểm `confidence` — không phải tuyên bố chắc chắn |
| **Fingerprint** | Khóa dùng để nhận diện "đây là cùng 1 vấn đề" khi dedup incident |
| **Occurrence_count** | Số lần 1 incident (đã dedup) tiếp tục được detector xác nhận lại |
| **Dry-run** | Chế độ chỉ ghi đề xuất hành động, không thực thi mutate thật |
| **RRF (Reciprocal Rank Fusion)** | Kỹ thuật gộp nhiều bảng xếp hạng khác nhau thành 1 bảng cuối bằng nghịch đảo hạng |
| **PageRank / damping factor** | Thuật toán tính "độ trung tâm" của node trong graph; `damping` là hệ số xác suất "đi tiếp theo cạnh graph" thay vì nhảy ngẫu nhiên |
| **EWMA** | Trung bình trượt trọng số giảm dần theo thời gian, dùng để làm mượt dữ liệu |
| **STL decomposition** | Tách time series thành trend + seasonal + residual |
| **Median / IQR** | Trung vị và khoảng phân vị (75%–25%) — đo trung tâm/độ phân tán bền với outlier |
| **IsolationForest** | Thuật toán ML không giám sát phát hiện outlier bằng cách đếm số phép cắt cần để cô lập 1 điểm |
| **BOCPD (Bayesian Online Change Point Detection)** | Thuật toán phát hiện điểm đổi trong time series theo xác suất Bayes, chạy online |
| **Drain3** | Thuật toán clustering log thành template |
| **Signal qualification gate** | Bước phân loại tín hiệu verified/missing/stale/invalid trước khi đưa vào detector |
| **On-demand enrichment** | Chỉ truy vấn Jaeger/OpenSearch/K8s **sau khi** có candidate, để giảm cost và rủi ro dữ liệu nhạy cảm |
| **Blast radius** | Phạm vi ảnh hưởng lan truyền nếu 1 service/store bị lỗi, suy ra từ topology graph |
| **Protected path** | Đường không được AIOps mutate (ví dụ `flagd`/`OpenFeature`) dù có quan sát được |

Nguồn: `src/aio/docs/mandates/7a/ADR-DETECT-001.md`, `src/aio/docs/blocks/1..12.md`, `src/aio/config/hyperparameters.json`, `src/aio/aiops/anomaly/v001.py`, `src/aio/aiops/rca/engine.py`, `src/aio/aiops/config/runtime.py`.
