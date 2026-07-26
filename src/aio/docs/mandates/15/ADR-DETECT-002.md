# ADR-DETECT-002 — Mandate #15 Trustworthy Incident Detection

> Status: Draft, pending owner/reviewer sign-off
> Owner: TODO (điền tên người nộp ticket)
> Reviewers: TODO
> Last updated: 2026-07-25
> Supersedes/extends: `docs/decisions/adr/ADR-DETECT-001.md` (Mandate #7a)
> Related: `docs/mandates/15/MANDATE-15-detection-standard-analysis.md`

## 1. Tóm tắt

ADR này ký duyệt cách team AIO4 chứng minh detector "đáng tin" theo Mandate #15: phân biệt được "bận" (tải cao nhưng healthy) với "hỏng" (sự cố thật), không bị nhiễu che (masking), chạy liên tục, và tự sinh incident summary. Kiến trúc phát hiện cốt lõi **kế thừa nguyên trạng** từ ADR-DETECT-001 (Mandate #7a) — ADR này chỉ bổ sung phần: (a) cách đo baseline/ngưỡng dùng cho quyết định "bận vs hỏng", (b) cách sinh incident summary, (c) cách nhận & chấm bộ kịch bản ẩn (cửa replay), (d) cách đo MTTD before/after.

## 2. Bối cảnh / Vấn đề

Mandate #7 chỉ yêu cầu detector "chạy được, có baseline, báo theo mức ảnh hưởng". Mandate #15 nâng chuẩn: detector phải sống sót qua **1 bộ kịch bản ẩn do BTC bơm lúc chấm** gồm 3 ca (sự cố thật / masking / tải-cao-healthy), phải chạy liên tục trong cụm (không phải script tay), và phải tự sinh + gửi incident summary ra kênh thật. Ràng buộc giữ nguyên: không đụng `flagd`, đo phải nhẹ, không hạ chuẩn để qua bài.

## 3. Quyết định

### 3.1 Baseline & ngưỡng ("bận" vs "hỏng")

Giữ nguyên phương pháp đã duyệt ở ADR-DETECT-001: mỗi *service × 1 signal* có baseline riêng tính bằng **median/IQR (robust score)** và **EWMA residual z-score**, không dùng mốc tuyệt đối cho nhánh anomaly. Bổ sung cho #15:

- Nhánh **SLO/threshold tuyệt đối** (`aiops/detectors/threshold.py`, `config/hyperparameters.json`) chỉ dùng làm **guard cứng cho SLO đã công bố** (ví dụ error budget), không phải cơ chế chính để phân biệt bận/hỏng. Quyết định phân biệt bận/hỏng nằm ở nhánh baseline riêng service (mục trên).
- Ca "tải cao nhưng healthy" được coi là healthy khi: (1) error rate không vượt SLO, và (2) độ lệch so với EWMA baseline của chính service nằm trong ngưỡng z-score bình thường (`ewma_z_threshold`), dù giá trị tuyệt đối (QPS, CPU, latency) cao hơn bình thường nhiều.
- Tham số cụ thể (α EWMA, z-threshold, IQR multiplier, consecutive-cycle) giữ như đã duyệt ở ADR-DETECT-001 trừ khi ghi đè + giải thích lý do ở mục 3.4 dưới.

### 3.2 Chống nhiễu che (anti-masking)

Quyết định: một finding không bị loại bỏ chỉ vì cùng cửa sổ phát hiện có một spike/nhiễu khác. Cơ chế:

- Mỗi metric-series được chấm **độc lập theo (service, signal)** trước khi vào bước correlate/dedup — nghĩa là spike nhiễu ở service/metric A không thể làm rơi finding thật ở service/metric B.
- Correlator (`aiops/correlation/correlator.py`) chỉ **gộp hiển thị** (dedupe) các finding cùng (flow, service) trong cùng cửa sổ để tránh spam, **không** được phép gộp tới mức loại bỏ finding có root-cause khác nhau. Bất kỳ thay đổi logic correlate cho #15 phải giữ invariant này và có test đi kèm (`test_masking_noise_does_not_hide_subtle_incident`, xem mục phân tích).

### 3.3 Sinh incident summary

Giữ nguyên `aiops/notifications/builder.py: NotificationBuilder._build_one()`: summary = `"{reason} on {signals}"` kèm severity, runbook liên quan, dependency nghi vấn. Không đổi format cho #15; chỉ đổi **đường ra** (mục 3.5).

### 3.4 Cửa replay nhận kịch bản ngoài

Quyết định: thêm 1 entrypoint mỏng (CLI `aiops.cli replay` hoặc endpoint `POST /api/v1/replay`) tái sử dụng logic đã có ở `evaluate/e2e_pipeline.py` để chạy detector trên **một bộ case bên ngoài** (định dạng giống `evaluate/dataset/<case>/simple_metrics.csv`) và in ra verdict + severity + summary theo từng case. Không viết pipeline detect mới — chỉ expose lại pipeline hiện có qua 1 cửa vào chuẩn.

### 3.5 Đẩy summary ra kênh thật

Dùng adapter có sẵn `aiops/integrations/notification.py` (`DiscordNotificationAdapter` hoặc `JsonWebhookNotificationAdapter`). Quyết định dùng **Discord webhook** làm kênh thật cho lần chứng minh #15 (rẻ, dựng nhanh, không cần quyền hạ tầng mới). Slack/PagerDuty có thể thay thế sau nếu team có sẵn.

### 3.6 MTTD before/after

- **Before:** mốc tham chiếu là thời gian phát hiện khi chỉ dựa vào SLO burn-rate alert tĩnh (không có baseline riêng service) — lấy từ cấu hình threshold gốc trước khi có anomaly engine, hoặc từ lịch sử incident thủ công nếu có.
- **After:** lead-time trung bình đo trực tiếp trên bộ case có nhãn (incident_start_ts → detector fire_ts) bằng harness cập nhật ở `evaluate/e2e_pipeline.py`.
- Số liệu cụ thể: điền vào bảng dưới sau khi đo (mục 5, "Bằng chứng").

## 4. Các lựa chọn đã xem xét

| Lựa chọn | Chọn? | Lý do |
|---|---|---|
| Viết detector mới hoàn toàn cho #15 | Không | Lãng phí; engine #7 đã đúng hướng (baseline riêng service), chỉ thiếu bằng chứng + 1 cửa replay |
| Chuyển toàn bộ threshold tuyệt đối sang relative | Không (chưa) | Rủi ro đổi hành vi SLO guard đang hoạt động đúng; để lại làm việc sau #15 nếu case tải-cao-healthy cho thấy cần |
| Dùng K8s CronJob thay vì standing Deployment/Compose | Không | Mandate yêu cầu "chạy liên tục" (standing), CronJob không thỏa; giữ Compose/Deployment long-running |
| Dùng Discord webhook làm kênh thật | Có | Rẻ, không cần thêm hạ tầng, adapter đã có sẵn trong code |

## 5. Bằng chứng (điền trước khi ký)

| Hạng mục | Evidence link/giá trị |
|---|---|
| PR/commit merged trunk | TODO |
| Cửa replay/capture | `aiops/replay.py` + `aiops/capture.py`, lệnh `python -m aiops.cli capture ...` rồi `python -m aiops.cli replay --dataset <path>` |
| Bộ sự cố có nhãn commit (THẬT, capture từ Prometheus sống) | TODO — `evaluate/dataset/mandate15_live/`, theo `docs/mandates/15/LIVE-CAPTURE-RUNBOOK.md`. (`evaluate/dataset/mandate15/` là fixture giả tự bịa, chỉ để test code, không tính.) |
| MTTD before | TODO |
| MTTD after (thật) | TODO — đo bằng `aiops.cli replay --dataset evaluate/dataset/mandate15_live` (`docs/mandates/15/MTTD-before-after.md`) |
| Screenshot incident summary trên kênh thật | TODO |
| Screenshot/log continuous-run | TODO |

## 6. An toàn / Ngoài phạm vi

Giữ nguyên các giới hạn đã duyệt ở ADR-DETECT-001: không auto-remediation production, không mutate K8s/`flagd`, không chạy trên request path người dùng, không dựng thêm cụm telemetry/ML nặng.

## 7. Người ký

| Vai trò | Tên | Ngày | Trạng thái |
|---|---|---|---|
| Owner | TODO | TODO | Pending |
| Reviewer | TODO | TODO | Pending sign-off |

> Điều kiện revisit: nếu bộ kịch bản ẩn ngày chấm cho thấy nhánh threshold tuyệt đối vẫn kêu oan ở ca tải-cao-healthy, phải quay lại mục 3.1 và chuyển nhánh đó sang so sánh tương đối trước khi đóng ADR revision tiếp theo.
