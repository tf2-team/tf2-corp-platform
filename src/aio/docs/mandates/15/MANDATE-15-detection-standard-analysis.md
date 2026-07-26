# AI MANDATE #15 — Trustworthy Incident Detection · Phân tích & Kế hoạch nộp

**Team:** AIO4 (AIOps sub-team) · **Task Force:** TF2
**Directive:** #15 — Phát hiện sự cố phải đáng tin - phân biệt "bận" với "hỏng", chứng minh bằng ca kiểm
**Hạn nộp:** Thứ Bảy 25/07/2026 (1 chặng, không chia a/b)
**Tác giả:** AIO4 AIOps Team
**Label:** `ai-mandate`, `m15`
**Nguồn mandate:** `xbrain-phase3/phase3/mandates/MANDATE-15-aiops-detection-standard.md`
**Kế thừa từ:** Mandate #7 (`docs/mandates/MANDATE-07-aiops-detection.md`, `docs/mandates/7a/`, `ADR-DETECT-001.md`)

> File này là **draft phân tích + gap-map**, dùng làm nguồn copy cho Jira ticket `AI MANDATE #15`. Ticket copy-paste sẵn nằm ở `AI-MANDATE-15-jira-draft.md` cùng thư mục. ADR ký tên nằm ở `ADR-DETECT-002.md`. MTTD before/after nằm ở `MTTD-before-after.md`.

> **Cập nhật 2026-07-25 (lần 2):** đã code xong cửa replay (`aiops/replay.py`, subcommand `python -m aiops.cli replay`). Bộ dữ liệu ở `evaluate/dataset/mandate15/` là **dữ liệu tự bịa để test code (KHÔNG PHẢI evidence)** — xem README cảnh báo trong chính thư mục đó. Bằng chứng thật phải lấy từ Prometheus sống trên cụm `techx-corp-prod` (team đã có quyền truy cập + có flagd/Locust để tự bơm sự cố). Đã thêm công cụ `python -m aiops.cli capture` + runbook từng bước `LIVE-CAPTURE-RUNBOOK.md` để làm việc này. Xem mục 7.

---

## 1. Tổng quan

Mandate #15 là **bản nâng cấp** của Mandate #7: không chỉ "có detector chạy được" mà detector phải **đáng tin** trước một bộ kịch bản ẩn do BTC bơm vào lúc chấm — gồm 3 ca: (a) 1 sự cố thật, (b) 1 ca **masking** (nhiễu + sự cố nhẹ bị che), (c) 1 cửa sổ **tải cao nhưng healthy**. Detector phải: kêu đúng ca (a), vẫn bắt được ca (b), và **không kêu oan** ở ca (c).

Engine hiện tại (`src/aio/aiops`) đã có nền tảng khá tốt từ Mandate #7 (anomaly engine, baseline robust score, RCA, notification builder), nhưng **chưa có bằng chứng trực tiếp** cho từng yêu cầu mới của #15. Bảng dưới tổng hợp hiện trạng.

## 2. Bảng chấm nhanh (Scorecard)

| # | Yêu cầu Mandate #15 | Hiện trạng | Gap lớn nhất |
|---|---|---|---|
| 1 | Bắt đúng - precision/recall/lead-time trên bộ có nhãn | **PARTIAL** | Dataset nhãn bị `.gitignore` (chưa commit); harness chưa tính lead-time; số liệu #7b live đang bị nghi cần đo lại |
| 2 | Không bị che (masking) | **PARTIAL** | Có test spike-ở-tail vs spike-ở-baseline, nhưng chưa có scenario/test đúng nghĩa "nhiễu + sự cố nhẹ cùng cửa sổ → vẫn bắt được" |
| 3 | Không kêu oan khi bận (deviation-based) | **PARTIAL** | Nhánh anomaly (EWMA/robust score) đã theo baseline riêng từng service; nhánh SLO/threshold (`detectors/threshold.py`, `hyperparameters.json`) vẫn dùng số tuyệt đối |
| 4 | Chạy liên tục + merged trunk | **PARTIAL** | Có vòng lặp `auto_run_loop` + Docker Compose standing service; **chưa có** Deployment/CronJob K8s trong repo; đang ở nhánh `feat/aio/v0.0.6`, chưa merge trunk |
| 5 | Cửa replay nhận kịch bản ngoài | **PARTIAL** | Chỉ có `/api/v1/pipeline/run` nhận metric thủ công; chưa có endpoint/CLI "replay bộ kịch bản có nhãn" đúng nghĩa |
| 6 | Tự sinh incident summary + đẩy kênh thật | **PARTIAL** | `NotificationBuilder` sinh summary tốt; adapter gửi Discord/webhook có code; **chưa có bằng chứng gửi thành công tới kênh thật** (webhook URL để trống) |
| — | MTTD before/after | **MISSING** | Chỉ có 1 lần đo lead-time (~196.7s), chưa có so sánh before vs after |

**Kết luận:** không có mục nào ở mức DONE hoàn toàn theo đúng nghĩa "chứng minh bằng bộ kịch bản ẩn" — team cần dùng những giờ còn lại để biến PARTIAL → DONE ở các mục rẻ nhất trước (xem mục 7 — Kế hoạch theo thứ tự ưu tiên).

---

## 3. Chi tiết từng yêu cầu

### 3.1 Bắt đúng (precision / recall / lead-time trên bộ có nhãn)

**Bằng chứng hiện có:**
- Harness offline: `evaluate/e2e_pipeline.py` (`score_report()`, `binary_scores()`, `prf()`), `evaluate/current_pipeline.py` (`evaluate_case()`).
- Report đã chạy: `evaluate/current_pipeline_report.json` (120 case, incident P/R/F1 = 1.0, RCA hit-rate 0.85).
- Doc kết quả: `docs/operations/eval/01-evaluation-results.md` §1.1–1.2.

**Thiếu:**
- `evaluate/dataset/` bị loại trong `.gitignore` (dòng 61) → **bộ sự cố có nhãn không nằm trong repo**, trái yêu cầu "bộ sự cố có nhãn commit trong repo".
- Harness chưa có trường lead-time (thời điểm sự cố bắt đầu → thời điểm detector kêu) — hiện chỉ có 1 số đo tay trong doc, không tái tạo được bằng script.
- Vì tất cả case trong dataset hiện tại đều `expected_incident = true` (không có case "normal"), số precision/recall = 1.0 không đáng tin theo đúng tinh thần mandate (cần cả case healthy để đo precision thật).

**Đã làm (2026-07-25):**
1. `.gitignore` cập nhật để commit được cả `evaluate/dataset/mandate15/` (fixture giả, chỉ để test code) và `evaluate/dataset/mandate15_live/` (chỗ chứa dữ liệu thật sẽ capture).
2. `aiops/replay.py` giờ đọc được 2 định dạng: `metric_series.json` (dữ liệu thật, capture trực tiếp từ Prometheus, giữ nguyên timestamp gốc từng tín hiệu) và `simple_metrics.csv` (fixture giả). Tự tính `lead_time_seconds = fire_timestamp - incident_start_ts` và precision/recall toàn bộ set, bất kể nguồn dữ liệu.
3. Viết công cụ `python -m aiops.cli capture` (`aiops/capture.py`) — kéo đúng các tín hiệu Prometheus mà detector sống đang dùng (từ `config/runtime.json` + `config/prometheus_queries.json`), ghi ra `metric_series.json` + `label.json` sẵn sàng cho `aiops.cli replay`.
4. Viết runbook từng bước để tự tạo dữ liệu thật: `docs/mandates/15/LIVE-CAPTURE-RUNBOOK.md` (dùng cụm `techx-corp-prod` + flagd + Locust team đã có).

**Còn phải làm (bạn tự chạy vì cần quyền truy cập cụm thật):**
1. Chạy theo `LIVE-CAPTURE-RUNBOOK.md`: bật port-forward, bơm 1 sự cố thật qua flagd, capture, lặp lại cho case masking và case tải-cao-healthy.
2. Chạy `aiops.cli replay --dataset evaluate/dataset/mandate15_live` để có precision/recall/lead-time **thật**, thay cho số liệu demo giả (30s) hiện tại trong `MTTD-before-after.md`.
3. `evaluate/dataset/RE2-SS/...` (bộ 120 case cũ dùng cho `evaluate/e2e_pipeline.py`) vẫn đang bị `.gitignore`/không tồn tại trong máy hiện tại — không bắt buộc cho #15 nếu bộ `mandate15_live/` capture thật đã đủ.

### 3.2 Không bị che (anti-masking)

**Bằng chứng gần nhất:**
- `tests/test_v001_anomaly_rca.py`: `test_v001_only_scores_detection_tail`, `test_v001_drops_short_infra_spike_in_tail`, `test_v001_keeps_sustained_infra_change_in_tail`.
- Cửa sổ tail: `aiops/shared/tail.py` (`fixed_baseline_and_tail`, `evaluate_tail_change`); `detection_window_seconds = 900` trong `config/hyperparameters.json`.
- `correlation/correlator.py` gộp finding theo (flow, service) — có thể giúp không dedup nhầm 2 sự cố khác nhau, nhưng chưa có test chứng minh trực tiếp.

**Đã làm (2026-07-25):** case demo giả `evaluate/dataset/mandate15/masking_cart_noise_plus_subtle/` chứng minh **cơ chế tính điểm không bị che** hoạt động đúng về mặt toán học: tín hiệu nhiễu và tín hiệu sự cố thật được chấm độc lập nên nhiễu không kéo điểm của sự cố thật xuống. Đây chỉ là bằng chứng "code đúng", không phải bằng chứng "hệ thống thật chống được masking".

**Còn phải làm:**
1. Theo `LIVE-CAPTURE-RUNBOOK.md` mục 3: bật 2 flag flagd cùng lúc (1 nhiễu + 1 sự cố nhẹ thật) trên cụm thật, capture bằng `aiops.cli capture --scenario-type masking`, rồi chạy replay để xem detector thật có còn bắt được sự cố nhẹ không — đây mới là bằng chứng thật.
2. Viết thêm 1 unit test `test_masking_noise_does_not_hide_subtle_incident` trong `tests/` để hành vi này được bảo vệ khỏi regression lâu dài.

### 3.3 Không kêu oan khi bận (deviation từ baseline riêng, không mốc tuyệt đối)

**Đúng hướng:**
- `aiops/anomaly/stats.py`: `robust_score()`, `robust_spread()` (median/IQR/MAD) — so với baseline của chính service, không phải số tuyệt đối.
- `aiops/anomaly/v001.py`: `EwmaStlDetector`, `RobustDriftDetector`, `V001AnomalyEngine._filter_normal_traffic_growth()`.
- `aiops/shared/tail.py`: `normal_traffic_growth_decision()` — nhận diện "tải tăng nhưng vẫn healthy" để không báo.

**Lệch yêu cầu:**
- `aiops/detectors/threshold.py` (`ThresholdDetector.evaluate()`) và các threshold tuyệt đối trong `config/hyperparameters.json` (`ops01_checkout_slo_burn_rate: 1.0`, `auto_*_error_rate: 0.05`) vẫn là mốc cứng, không tự thích nghi theo baseline riêng từng service.

**Việc cần làm:**
1. Chạy case "tải cao nhưng healthy" (traffic tăng đều, không lỗi) qua **cả 2 nhánh** (anomaly + threshold) để xác nhận threshold tuyệt đối không kêu nhầm ở mức tải test hiện tại. Nếu kêu nhầm, hoặc nới ngưỡng, hoặc chuyển nhánh đó qua so sánh tương đối baseline (`robust_score`) trước hạn.
2. Ghi lại kết quả case này làm evidence cho phần "Đến ngày chấm" (tải-cao-healthy → không kêu).

### 3.4 Chạy liên tục + merged trunk

**Có:**
- `aiops/api/app.py`: `auto_run_loop()` (`while True` + `run_live_pipeline` + sleep) chạy khi `AIOPS_AUTO_RUN_ENABLED=true`.
- `docker-compose.yml` service `aiops:` với `restart: unless-stopped` + healthcheck — là workload thường trực (không phải script chạy-một-lần).

**Thiếu:**
- Không có Deployment/CronJob/Helm chart nào cho AIOps trong repo (`docs/test_environment_note.md`: *"cluster chưa có Deployment/Service AIOps"*).
- Nhánh hiện tại: `feat/aio/v0.0.6` — **chưa merge** vào trunk/main.

**Việc cần làm:**
1. Tối thiểu: dùng Docker Compose service làm bằng chứng "standing workload" (chụp `docker compose ps` cho thấy `aiops` container `Up`/`healthy` liên tục nhiều giờ) — đủ để nộp nếu cụm thật chưa kịp có K8s Deployment trước deadline.
2. Nếu có thời gian: thêm 1 Deployment YAML tối thiểu trong `tf2-corp-platform` (namespace hiện có) chạy image AIOps, `replicas: 1`, liveness probe `/health/live`.
3. Mở PR merge nhánh hiện tại vào `main`/trunk **trước khi nộp ticket** — mandate yêu cầu rõ "PR/commit đã merge trunk".

### 3.5 Cửa replay nhận kịch bản từ ngoài

**Có:** `POST {api_pipeline_run_path}` (`/api/v1/pipeline/run`, `aiops/schemas/api.py: PipelineRunRequest`) nhận `observations` + `metric_series` thủ công; `evaluate/e2e_pipeline.py --dataset <path>` chạy offline trên 1 folder dataset.

**Thiếu:** chưa có endpoint/lệnh "replay" đúng nghĩa mandate — nhận **một bộ kịch bản** (nhiều case, có nhãn) từ ngoài và trả về output theo từng case (đúng định dạng để BTC bơm bộ ẩn vào ngày chấm).

**Đã làm (2026-07-25, lần 2):** lệnh `python -m aiops.cli replay --dataset <path>` (code: `aiops/replay.py`) đã hoạt động, nhận 1 thư mục nhiều case, mỗi case là `metric_series.json` (dữ liệu thật, capture từ Prometheus) **hoặc** `simple_metrics.csv` (fixture giả) + `label.json` tùy chọn. Thêm lệnh `python -m aiops.cli capture` (code: `aiops/capture.py`) để tự tạo `metric_series.json` từ Prometheus sống — đây là "cửa" thật sự nhận kịch bản từ ngoài bằng dữ liệu thật, không chỉ tay bịa số.

Chạy thử ngay (bản demo, chỉ để test code không lỗi):

```bash
cd tf2-corp-platform/src/aio
conda run -n capstone python -m aiops.cli replay --dataset evaluate/dataset/mandate15
```

Chạy thật (sau khi làm theo `LIVE-CAPTURE-RUNBOOK.md`):

```bash
conda run -n capstone python -m aiops.cli replay --dataset evaluate/dataset/mandate15_live
```

**Còn phải làm:** đây là bản MVP dùng scoring "current-vs-history" đơn giản (giống `evaluate/e2e_pipeline.py`), chưa gọi full pipeline (`AiopsPipeline.run_once`) với RCA/correlate/notify đầy đủ. Nếu có thời gian, nối thêm `--full-pipeline` để chạy qua `V001RcaEngine` + `NotificationBuilder` thật, nhưng bản hiện tại đã đủ để làm "cửa replay" theo đúng nghĩa mandate yêu cầu (nhận kịch bản ngoài, trả verdict + summary theo từng case). Quan trọng hơn: **phải chạy `capture` trên dữ liệu thật trước khi nộp** — bản demo `mandate15/` không được tính là evidence.

### 3.6 Tự sinh incident summary + đẩy kênh thật

**Có:**
- Sinh summary: `aiops/notifications/builder.py` (`NotificationBuilder._build_one()`) — title/summary/severity/runbook/dependency.
- Gửi đi: `aiops/integrations/notification.py` (`JsonWebhookNotificationAdapter`, `DiscordNotificationAdapter`, `NotificationClient.send()`), wired trong `app.py` khi có `AIOPS_NOTIFICATION_WEBHOOK_URL`.

**Thiếu:** biến môi trường webhook đang để trống trong môi trường test (`docs/test_environment_note.md`: Notification FAIL 0/1) → **chưa có bằng chứng gửi thật thành công**.

**Việc cần làm:**
1. Tạo 1 Discord webhook (hoặc Slack incoming webhook) thật, set `AIOPS_NOTIFICATION_WEBHOOK_URL` trong `.env`/Compose.
2. Bơm 1 sự cố (qua lệnh replay ở mục 3.5 hoặc qua `run-live`), chụp màn hình incident summary xuất hiện thật trong channel.
3. Lưu ảnh + timestamp làm evidence "Tự sinh tóm tắt sự cố + đẩy ra kênh thật".

### 3.7 Đo MTTD before/after

**Hiện trạng:** chưa có. Chỉ có backlog nhắc tới MTTD (`docs/planning/w1/*.md`) và 1 số lead-time đơn lẻ trong `01-evaluation-results.md`.

**Đã làm (2026-07-25):** file `MTTD-before-after.md` có sẵn công thức + lệnh tái lập; số 30s hiện ghi trong đó chỉ là **kết quả trên bộ demo giả**, phải thay bằng số đo trên `evaluate/dataset/mandate15_live/` sau khi capture.

**Còn phải làm:**
1. Làm theo `LIVE-CAPTURE-RUNBOOK.md` để có case `real_incident` thật, chạy `aiops.cli replay --dataset evaluate/dataset/mandate15_live`, lấy `avg_lead_time_seconds` thật thay cho 30s.
2. **Before:** bạn (người nộp) cần tự điền con số + nguồn giả định trong `MTTD-before-after.md` (ví dụ: quy ước theo Mandate #7, hoặc thời gian oncall phát hiện thủ công qua Grafana theo `INCIDENT_HISTORY.md`) — đây là quyết định nghiệp vụ, không thể tự suy ra từ code.
3. Sau khi có before + after thật, tính % cải thiện và dán vào ticket.

---

## 4. Ràng buộc cần tự kiểm tra trước khi nộp

- [ ] Đo đạc không thêm tải/độ trễ lên service (đo bằng batch/offline hoặc scrape nhẹ, không đổi request path).
- [ ] Không đụng / vô hiệu hoá `flagd` — xác nhận replay/case dataset không mutate `flagd` config.
- [ ] Không hạ ngưỡng/hạ chuẩn chỉ để case test tự chấm đậu (nếu chỉnh `hyperparameters.json`, ghi rõ lý do + trade-off trong ADR).

## 5. Checklist deliverable theo đúng mục "Phải nộp" của mandate

**Trước hạn (bắt buộc để đóng ticket):**
- [ ] Link PR/commit đã merge trunk. *(bạn tự làm — xem mục 7, bước A)*
- [x] Cửa replay nhận kịch bản từ ngoài (mục 3.5) — `aiops/replay.py` + `python -m aiops.cli replay`, đã chạy được (nhận cả dữ liệu thật lẫn CSV giả).
- [ ] Bằng chứng detector chạy liên tục trong cụm (mục 3.4) — screenshot/log uptime. *(bạn tự chụp — xem mục 7, bước B)*
- [ ] Bộ sự cố có nhãn **thật** commit trong repo (mục 3.1 + 3.2) — cần chạy `LIVE-CAPTURE-RUNBOOK.md` để tạo `evaluate/dataset/mandate15_live/`. Bộ `evaluate/dataset/mandate15/` hiện có **chỉ là fixture giả, không tính**. *(bạn tự làm — xem mục 7, bước A2)*
- [ ] MTTD after đo trên dữ liệu thật (mục 3.7, `MTTD-before-after.md`) — số 30s hiện tại là từ bộ demo giả, phải thay. [ ] MTTD before cần bạn điền số.
- [x] `repro` — lệnh chạy lại toàn bộ (xem mục 6).

**Đến ngày chấm (BTC bơm bộ kịch bản ẩn):**
- [ ] Chạy 3 ca (sự cố thật / masking / tải-cao-healthy) qua cửa replay, chụp output detector + incident summary từng ca, dán vào ticket.

**ADR:**
- [ ] `ADR-DETECT-002.md` ký tên — baseline/ngưỡng dùng gì, incident summary sinh thế nào (xem file cùng thư mục).

---

## 6. Cách chạy lại (Repro)

```bash
cd tf2-corp-platform/src/aio

# Unit tests hiện có (bao gồm anti-mask / anomaly / RCA)
conda run -n capstone python -B -m unittest discover -s tests

# Đánh giá trên bộ dataset cũ (nếu tải/tái tạo lại được RE2-SS)
conda run -n capstone python -B evaluate/e2e_pipeline.py --limit 10 --out evaluate/report.json

# Chạy pipeline sống 1 lần
conda run -n capstone python -m aiops.cli run-live

# Cửa replay nhận bộ kịch bản ngoài (ĐÃ CODE XONG — chạy được ngay)
conda run -n capstone python -m aiops.cli replay --dataset evaluate/dataset/mandate15 --out evaluate/mandate15_replay_report.json

# Standing workload local
docker compose up -d aiops
docker compose ps aiops   # xác nhận "Up"/"healthy" liên tục
```

## 7. Việc còn lại — theo thứ tự, ghi rõ ai làm

Phần code (cửa replay, cửa capture, công thức MTTD) **đã làm xong** trong repo. Việc còn lại đều cần **quyền truy cập cụm thật/Jira/git remote/Discord** mà chỉ bạn mới có. Làm đúng thứ tự A → F, vì A2 (dữ liệu thật) là điều kiện để B/C/D có số liệu để điền.

| Bước | Việc | Ai làm | Thao tác cụ thể |
|---|---|---|---|
| A1 | Commit + mở PR + merge vào trunk | Bạn | `git add -A && git commit -m "AI MANDATE #15: replay/capture entrypoint"`, push, mở PR, merge vào `main` |
| A2 | Capture dữ liệu thật | Bạn | Làm theo `LIVE-CAPTURE-RUNBOOK.md`: port-forward → bơm lỗi qua flagd → `aiops.cli capture` → lặp lại 3-4 case → `aiops.cli replay --dataset evaluate/dataset/mandate15_live` |
| B | Chụp bằng chứng chạy liên tục | Bạn | Chạy `docker compose up -d aiops`, đợi vài phút, chụp `docker compose ps aiops` cho thấy `Up`/`healthy` |
| C | Điền MTTD before/after thật | Bạn | Dùng `avg_lead_time_seconds` từ kết quả bước A2 làm "after"; tự quyết định mốc "before" (vd theo Mandate #7 hoặc `INCIDENT_HISTORY.md`), điền vào `MTTD-before-after.md` |
| D | Bật kênh thật + chụp summary | Bạn | Tạo Discord webhook → set `AIOPS_NOTIFICATION_WEBHOOK_URL` → chạy lại replay hoặc `run-live` → chụp tin nhắn xuất hiện thật trong Discord |
| E | Ký ADR-DETECT-002 | Bạn (+ 1 reviewer) | Điền tên/ngày vào mục 7 của `ADR-DETECT-002.md`, cập nhật số liệu MTTD thật |
| F | Rà threshold tuyệt đối vs case tải-cao-healthy (mục 3.3) | Tôi có thể hỗ trợ nếu bạn muốn | Nếu muốn, nhắn tôi làm tiếp |

Sau khi xong A-E, copy nội dung `AI-MANDATE-15-jira-draft.md` vào Jira, điền các link/ảnh vào chỗ TODO, gắn label `ai-mandate`, `m15`, đóng ticket trước 25/07.

---

*Tài liệu này phục vụ cho Jira ticket `AI MANDATE #15`. Nội dung sao chép sẵn cho Jira nằm ở `AI-MANDATE-15-jira-draft.md`.*
