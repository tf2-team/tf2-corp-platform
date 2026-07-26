# Runbook: dựng bộ sự cố có nhãn THẬT cho AI MANDATE #15

> Thay thế bộ demo giả ở `evaluate/dataset/mandate15/`. Dùng chính cụm EKS `techx-corp-prod`
> mà team đã có quyền truy cập (xem `docs/test_environment_note.md`), cộng `flagd` (bơm lỗi) và
> Locust (loadgen) bạn đang có sẵn.

## 0. Chuẩn bị (làm 1 lần)

```powershell
cd tf2-corp-platform/src/aio
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Điền AIOPS_PROMETHEUS_BASE_URL=http://localhost:9090 trong .env (nếu chưa có)
```

Mở terminal 1 — bật port-forward tới cụm thật:

```powershell
powershell -File scripts/port_forward.ps1
```

Để terminal này chạy xuyên suốt cả buổi capture. Giữ nguyên các terminal khác cho các bước dưới.

## 1. Case "normal" (tùy chọn nhưng nên có — làm mốc MTTD before)

Terminal 2 — đảm bảo traffic bình thường đang chạy (Locust ở mức tải thường ngày, KHÔNG bơm lỗi), rồi:

```powershell
python -m aiops.cli capture --out evaluate/dataset/mandate15_live/normal_baseline `
  --scenario-type normal --expected-incident false `
  --notes "Locust muc tai thuong ngay, khong bom loi qua flagd"
```

## 2. Case "real_incident" — sự cố thật

1. Ghi lại **giờ chính xác (unix timestamp)** ngay lúc bạn bật flag lỗi trong flagd. Cách lấy nhanh: `[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()` (PowerShell) ngay trước khi bấm bật flag.
2. Bật 1 flag lỗi thật trong flagd (ví dụ flag từng gây INC-1/INC-2/INC-3 trong `INCIDENT_HISTORY.md` — vd lỗi DB connection pool, lỗi valkey-cart...).
3. Để lỗi chạy **ít nhất 3-5 phút** (để lọt vào cửa sổ metric).
4. Chạy:

```powershell
python -m aiops.cli capture --out evaluate/dataset/mandate15_live/real_incident_<ten-loi> `
  --scenario-type real_incident --expected-incident true `
  --incident-start-ts <unix_ts_ban_ghi_o_buoc_1> `
  --notes "flagd flag=<ten-flag> service=<service> mo ta loi that"
```

5. **Tắt flag lỗi** trong flagd ngay sau khi chạy xong lệnh capture.

## 3. Case "masking" — nhiễu + sự cố nhẹ

1. Bật **2 flag cùng lúc**: 1 flag gây nhiễu vô hại/thoáng qua (ví dụ 1 lỗi tự hồi phục nhanh), 1 flag gây sự cố thật nhưng nhẹ (ảnh hưởng 1 metric khác/service khác). Ghi lại timestamp lúc bật flag gây sự cố thật (không phải flag nhiễu).
2. Để chạy vài phút, rồi:

```powershell
python -m aiops.cli capture --out evaluate/dataset/mandate15_live/masking_<ten> `
  --scenario-type masking --expected-incident true `
  --incident-start-ts <unix_ts_luc_bat_flag_that> `
  --notes "flag nhieu=<A> (khong tinh la incident), flag that=<B> service=<service>"
```

3. Tắt cả 2 flag.

## 4. Case "high_load_healthy" — tải cao nhưng khỏe

1. Dùng Locust **tăng dần số user** lên mức cao (không bật bất kỳ flag lỗi nào trong flagd).
2. Theo dõi Grafana/log để chắc chắn hệ thống vẫn khỏe (error rate ~0%, không timeout).
3. Khi tải đã ổn định ở mức cao vài phút:

```powershell
python -m aiops.cli capture --out evaluate/dataset/mandate15_live/high_load_healthy_<ten> `
  --scenario-type high_load_healthy --expected-incident false `
  --notes "Locust ramp len <N> user, khong bom loi, error rate quan sat = 0"
```

4. Hạ tải Locust về mức bình thường.

## 5. Chấm bộ vừa capture

```powershell
python -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json
```

Kỳ vọng: case `real_incident_*` và `masking_*` → `FIRED`; case `high_load_healthy_*` và `normal_baseline` → `no-fire`. Nếu sai (vd case sự cố thật không kêu, hoặc case healthy bị kêu oan), đó là dữ liệu quý để:
- Tinh chỉnh `--threshold` của lệnh replay (mặc định 3.0), hoặc
- Ghi nhận đây là hạn chế thật của detector — báo cáo trung thực trong ADR/ticket còn tốt hơn là giấu đi.

## 6. Dùng kết quả này ở đâu

- Copy output console + `evaluate/mandate15_live_report.json` (đổi tên tránh nhầm với báo cáo demo) dán vào Jira mục "Evidence ngày chấm" / "precision/recall/lead-time".
- Cập nhật `docs/mandates/15/MTTD-before-after.md` bằng lead-time thật đo được ở đây (thay số 30s của bộ demo).
- Commit các folder `evaluate/dataset/mandate15_live/*` vào repo (nhớ thêm exception trong `.gitignore` giống `mandate15/` — xem mục dưới).
- Xóa/không trích dẫn `evaluate/dataset/mandate15/` (bộ demo giả) trong bằng chứng nộp.

## 7. Cập nhật `.gitignore` cho bộ live

`.gitignore` hiện chỉ mở ngoại lệ cho `src/aio/evaluate/dataset/mandate15/`. Sau khi capture xong `mandate15_live/`, thêm 2 dòng tương tự:

```gitignore
!src/aio/evaluate/dataset/mandate15_live/
!src/aio/evaluate/dataset/mandate15_live/**
```

## Lưu ý an toàn

- Không đụng/vô hiệu hóa **cấu hình** flagd — chỉ toggle flag lỗi đã có sẵn để demo, xong việc thì trả lại trạng thái ban đầu ngay.
- Đo bằng `aiops.cli capture` là read-only (chỉ query Prometheus), không tác động tải/độ trễ hệ thống.
- Nếu `capture` báo "0 verified series" hoặc danh sách skip dài — kiểm tra lại port-forward và `.env` trước khi nghi ngờ code.
