# MTTD Before/After — AI MANDATE #15

## Định nghĩa

- **MTTD before:** thời gian trung bình để biết có sự cố **nếu không có detector baseline riêng service** — tức chỉ dựa vào cảnh báo SLO/threshold tuyệt đối đã có từ trước (hoặc phát hiện thủ công qua Grafana). Vì team không có log MTTD thủ công lịch sử đáng tin, dùng quy ước: MTTD before = thời gian một chu kỳ giám sát thủ công điển hình đã thống nhất với mentor ở Mandate #7 — **ghi rõ con số + nguồn giả định** trước khi điền bảng dưới.
- **MTTD after:** lead-time đo được bằng `aiops.cli replay` trên bộ case có nhãn = thời điểm detector kêu (`fire_timestamp`) trừ thời điểm sự cố thật sự bắt đầu (`incident_start_ts` trong `label.json`).

## After — bản demo (chỉ để chứng minh công thức đo chạy đúng, KHÔNG PHẢI evidence)

```bash
cd tf2-corp-platform/src/aio
conda run -n capstone python -m aiops.cli replay --dataset evaluate/dataset/mandate15
```

Trên bộ demo **tự bịa** (`evaluate/dataset/mandate15/`, xem cảnh báo trong `_SYNTHETIC_DEMO_KHONG_PHAI_BANG_CHUNG.md`):

| case_id | scenario_type | fired | lead_time_seconds |
|---|---|---|---|
| `real_incident_checkout_latency` | real_incident | true | 30 |
| `masking_cart_noise_plus_subtle` | masking | true | 30 |
| `high_load_healthy_product_catalog` | high_load_healthy | false | — (đúng, không được kêu) |

Precision = 1.0, Recall = 1.0, avg lead-time = 30s — **con số này chỉ chứng minh code chạy đúng công thức, không đại diện hệ thống thật, không được dùng làm evidence nộp ticket.**

## After — bản THẬT (bắt buộc trước khi nộp)

Làm theo `LIVE-CAPTURE-RUNBOOK.md` (dùng cụm `techx-corp-prod` + flagd + Locust) rồi chạy:

```bash
cd tf2-corp-platform/src/aio
conda run -n capstone python -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json
```

Điền bảng dưới bằng số đo thật (thay TODO):

| case_id | scenario_type | fired | lead_time_seconds |
|---|---|---|---|
| TODO | real_incident | TODO | TODO |
| TODO | masking | TODO | TODO |
| TODO | high_load_healthy | TODO | — |

**MTTD after (thật) = TODO giây** (lấy từ `avg_lead_time_seconds` trong output).

## Before — cần điền trước khi nộp

| Mốc | Giá trị | Nguồn |
|---|---|---|
| MTTD before (không có detector baseline riêng service) | TODO | TODO — vd: SLO burn-rate alert cũ, hoặc thời gian trung bình oncall phát hiện qua Grafana theo `INCIDENT_HISTORY.md` |

## Kết luận (điền sau khi có số before + after thật)

MTTD giảm từ **TODO giây/phút** xuống **TODO giây** (đo thật trên `mandate15_live/`) — cải thiện TODO%.
