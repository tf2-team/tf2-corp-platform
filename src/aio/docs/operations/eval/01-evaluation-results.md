# 1. Kết quả Evaluation

Báo cáo này có 2 phần tách biệt: **(1.1)** eval offline trên research dataset (không có traffic thật, không có Kubernetes/Flagd), và **(1.2)** eval trên hệ thống live (CDO/TF2 platform, có fault injection thật). Hai phần đo hai thứ khác nhau, không gộp số liệu.

---

## 1.1 Evaluation trên research dataset

**Dataset dùng: RE2-SS** (không phải NAB — Numenta Anomaly Benchmark, một benchmark time-series đơn biến khác, hệ thống hiện **chưa tích hợp**; file topology ghi rõ `nab_mapping: "N/A"`).

- Vị trí: `src/aio/evaluate/dataset/RE2-SS/<service>_<metric-family>/<case-số>/simple_metrics.csv`
- Quy mô: **120 case**, mỗi case là 1 folder time-series đã biết trước root service + metric family gây lỗi (suy ra từ tên folder, ví dụ `payment_mem` → root service `payment`, metric family `mem`).
- Không có case "bình thường" (no-incident) trong dataset → mọi case đều `expected_incident = true`. Vì vậy `TN` và `FP` ở mức incident luôn là `0` một cách cấu trúc (do thiết kế dataset, không phải do engine).

### Hai pipeline được so sánh

| Pipeline | File | Anomaly detector dùng |
| --- | --- | --- |
| Baseline (legacy) | `evaluate/e2e_pipeline.py` | `legacy_robust_score` — so 1 điểm cuối với lịch sử bằng robust z-score, ngưỡng cố định |
| Current (engine thật) | `evaluate/current_pipeline.py` | `build_v001_anomaly_engine` — engine sản xuất thật (EWMA+STL, robust drift, IsolationForest...) |

Cả hai đều dùng **cùng RCA engine** (`V001RcaEngine`, có graph ranking + weighted RRF) để xếp hạng root-cause top-K, nên phần chênh lệch kết quả RCA phản ánh đúng chất lượng *anomaly detection* đầu vào, không phải do RCA khác nhau.

### Kết quả (120/120 case)

| Metric | Baseline (legacy_robust_score) | Current (engine thật) | Ý nghĩa |
| --- | ---: | ---: | --- |
| Incident precision / recall / F1 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 | Luôn đạt 1.0 vì dataset không có case "normal" — **không dùng số này để khẳng định engine hoàn hảo** |
| RCA top-K precision | 0.078 | **0.172** | % service được đề xuất trong top-K là đúng root cause |
| RCA top-K recall | 0.392 | **0.858** | % case mà root cause thật nằm trong top-K |
| RCA top-K F1 | 0.131 | **0.286** | |
| RCA top-K hit-rate (case-level) | 30.8% | **85.0%** | % case mà top-K chứa đúng service **và** đúng metric family |

**Đọc số liệu đúng cách:**
- Chỉ số `incident precision/recall/F1 = 1.0` **không phải bằng chứng engine không có false positive** — đó là hạn chế của phương pháp gán nhãn (mọi case đều được coi là có incident), cần nói rõ trong báo cáo để không bị hỏi ngược.
- Chỉ số quan trọng để so sánh chất lượng thật của engine là **RCA top-K hit-rate**: engine hiện tại (85%) tốt hơn baseline cũ (30.8%) rất nhiều — đây là con số nên dùng khi cần chứng minh cải tiến.
- `rca_top_k.precision` thấp hơn `rca_top_k.recall` là bình thường theo thiết kế: top-K thường chứa đúng service cần tìm + vài service khác không liên quan (xem `evaluate/README.md`).

Nguồn: `src/aio/evaluate/README.md`, `src/aio/evaluate/e2e_pipeline_report.json`, `src/aio/evaluate/current_pipeline_report.json`.

---

## 1.2 Evaluation trên hệ thống live (CDO / TF2 platform)

Đo trên hệ thống chạy thật (Docker Compose, Prometheus/Jaeger/OpenSearch, fault injection bằng Flagd), theo đúng định nghĩa của Mandate #7b:

```text
recall     = số incident bị inject bắt được / K (số incident inject)
precision  = số fire đúng / tổng số fire
lead-time  = thời điểm detector fire đầu tiên - thời điểm bắt đầu fault
```

### Số liệu đã submit (v1, `docs/evidence/MANDATE-07b-api-runtime-draft.md`)

| Metric | Giá trị | Ghi chú |
| --- | ---: | --- |
| Injected incidents `K` | 2 | payment failure + cart failure |
| Recall | 100% | 2/2 bắt được cả hai |
| Conservative API-incident precision | 66.7% | 2 đúng / 3 incident tổng lộ ra qua API (1 FP là `recommendation` RCA không mong đợi) |
| Impact-alert precision | 100% | 2/2 trên tập 2 incident đã lọt vào impact-alert |
| Checkout lead-time | 205.417s | |
| Cart lead-time | 187.947s | |
| Mean / median lead-time | 196.682s | |
| Checkout recovery time | ~376.827s | |

### ⚠️ Cảnh báo quan trọng — số liệu trên đang được re-validate

Khi đối chiếu trực tiếp với **raw runtime state / audit log** (`state/7b/rca-history-*.jsonl`, `remediation_audit.jsonl`) thay vì chỉ đọc API response tại 1 thời điểm, nhóm phát hiện:

- Detector `rca_root_cause` phát sinh **rất nhiều false positive** không được tính vào mẫu số (một incident ghi nhận tới 53 occurrence), làm precision thật **thấp hơn nhiều** so với 66.7–100% đã submit (ước tính sơ bộ 8–17% khi tính đầy đủ).
- Các state store của các scenario **bị lẫn lộn** (incident của scenario checkout xuất hiện trong state file của scenario cart) — vi phạm giả định "clean isolated state" mà bản v1 đã công bố.

→ **Hệ thống đang chạy lại 4 scenario cách ly hoàn toàn (checkout, cart, burn-rate, ad-CPU saturation)** với state store riêng biệt cho từng scenario để tạo bộ số liệu sạch, chính xác. Bản draft mới đang ở `docs/evidence/new/MANDATE-07b-api-runtime-draft.md` (đang chờ số liệu, chưa hoàn chỉnh).

**Hành động:** Section này sẽ được cập nhật lại với số liệu chính xác ngay khi 4 scenario rerun hoàn tất. Không dùng số 66.7%/100% ở trên để báo cáo chính thức cho CDO nếu chưa có bản cập nhật — chỉ dùng để minh họa *cách tính* precision/recall/lead-time.

Nguồn: `src/aio/docs/evidence/MANDATE-07b-api-runtime-draft.md` (§13), `src/aio/docs/evidence/new/MANDATE-07b-api-runtime-draft.md` (đang chạy lại), `src/aio/state/7b/*.jsonl`.
