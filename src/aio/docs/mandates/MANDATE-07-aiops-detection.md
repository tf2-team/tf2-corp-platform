# [DIRECTIVE #7] Sự cố phải tự lộ ra - dựng mắt cho hệ thống

**Từ:** Ban Vận hành (SRE) - TechX Corp
**Hiệu lực:** ngay khi nhận · nộp qua **2 ticket**: `#7a` trước **thứ Bảy 18/07**, `#7b` trước **thứ Bảy 25/07**
**Áp dụng:** nhóm AIO của mọi Task Force

---

## Bối cảnh
Hiện muốn biết hệ thống có đang khoẻ hay không, phải có người ngồi mở Grafana soi bằng mắt - nghĩa là sự cố chỉ lộ ra khi khách đã kêu. Với một service có SLA, như vậy là quá muộn. Các bạn có sẵn cả kho telemetry (metric/log/trace) mà chưa có "đôi mắt" tự động nào đọc nó. Nhiệm vụ đợt này: dựng đôi mắt đó - hệ tự phát hiện bất thường và báo, trước khi user phản ánh.

## Yêu cầu
1. **Phát hiện bất thường trên nhiều tín hiệu** - không chỉ ngưỡng tĩnh: theo dõi latency / error rate / saturation / queue / cost… dựa trên telemetry thật. **Sàn = univariate**: mỗi *service × 1 tín hiệu* có baseline + luật bất thường riêng. Gộp nhiều tín hiệu lại thành một mô hình chung (**multivariate / tương quan**) là **bonus**, không bắt buộc.
2. **Có baseline "biết thế nào là bình thường"** - lập baseline theo từng service để không báo nhầm vào lúc tải cao bình thường.
3. **Cảnh báo có ý nghĩa, không spam** - báo theo mức độ ảnh hưởng (ưu tiên triệu chứng user-visible + burn-rate error budget), không phải mỗi cái gợn là kêu.
4. **Chạy được end-to-end** - bơm một bất thường vào là detector **kêu ra**, nhìn thấy được (alert/log/dashboard). Phần chạy thật + đo đạc nộp ở chặng sau (#7b); chặng đầu (#7a) chỉ cần implement + phân tích.

## Định nghĩa Hoàn thành cho #7a (hạn 18/07) — implement + phân tích
Không cần chạy thật tuần này. Đạt khi trong Jira thể hiện được:
1. **Đã bắt tay implement** detector + baseline (link PR/commit cho thấy code có thật).
2. **Phân tích (dạng doc trong ticket):** chọn **≥ 3 metrics** từ (các) service trọng yếu (vd p95 latency của checkout, error-rate của cart, saturation của product-catalog…); với **mỗi metric**: vì sao chọn, baseline "bình thường" là khoảng nào, thế nào thì coi là bất thường; phương pháp phát hiện định dùng.
3. **ADR ký tên.**
> Chạy thật e2e + ảnh alert minh chứng + số precision/recall để chặng **#7b** (25/07).

## Ràng buộc
- Không kéo tải/độ trễ hệ thống vì việc thu thập-đo (đo phải nhẹ).
- Trong ngân sách hiện tại - đừng dựng thêm cụm nặng để "cho oách".
- Không đụng / vô hiệu hóa cơ chế sự cố (flagd) - xem Luật chơi trong RULES.

## Phải nộp
Nộp qua **2 Jira ticket** riêng (cách ghi evidence xem `AI_MANDATE_EVIDENCE.md`):

- **`AI MANDATE #7a` Detection · implement + phân tích — hạn T7 18/07** *(chấm như doc, chưa cần chạy thật)*
  - **Link PR/commit** cho thấy đã implement detector + baseline.
  - **Phân tích trong ticket:** **≥ 3 metrics** đã chọn (từ service trọng yếu) + với mỗi metric: vì sao chọn, baseline "bình thường", ngưỡng bất thường; phương pháp phát hiện.
  - **ADR ký tên.**
- **`AI MANDATE #7b` Detection · chạy thật + đo đạc — hạn T7 25/07**
  - **Ảnh/log detector kêu e2e** khi bơm 1 sự cố (mentor tự bật hoặc bơm qua flagd) + cách chạy lại.
  - **Số precision/recall/lead-time** đo trên **một bộ sự cố có nhãn** (mentor bơm K sự cố + có giai đoạn bình thường), KHÔNG phải per-service: recall = bắt được / K; precision = lần kêu đúng / tổng lần kêu; lead-time = từ lúc sự cố bắt đầu tới lúc kêu.
  - **Cảnh báo theo mức ảnh hưởng** (burn-rate, không spam) + mở rộng thêm service.

> Đội đã có detection chạy sẵn thì làm gọn `#7a` và tập trung vào `#7b`.

## Được nhìn ở đâu
Trụ **AI** (AIOps): dùng AI/thống kê để vận hành. Chạm **Reliability** (phát hiện sớm giữ SLO) và **Operational Excellence** (giảm thời gian tới lúc biết có sự cố - MTTD).

> Directive bắt buộc nhóm AIO toàn TF. Điểm nằm ở chỗ: sau đợt này, sự cố **tự lộ ra qua cảnh báo** chứ không đợi người soi - và chứng minh bằng một lần bơm sự cố thấy nó kêu đúng.

---

## English

# [DIRECTIVE #7] Incidents must surface themselves — build eyes for the system

**From:** Operations (SRE) — TechX Corp
**Effective:** immediately · submit via **2 tickets**: `#7a` by **Sat 18/07**, `#7b` by **Sat 25/07**
**Applies to:** the AIO team of every Task Force

### Context
Right now, knowing whether the system is healthy means a human staring at Grafana — i.e. incidents only surface once customers already complain. For an SLA-bound service that is too late. You already have a full store of telemetry (metrics/logs/traces) but no automated "eyes" reading it. This directive: build those eyes — the system detects anomalies and alerts on its own, before users report.

### Requirements
1. **Anomaly detection across multiple signals** — not just static thresholds: watch latency / error rate / saturation / queue / cost… on live telemetry. **Floor = univariate**: each *service × 1 signal* has its own baseline + anomaly rule. Combining signals into one joint model (**multivariate / correlation**) is a **bonus**, not required.
2. **A baseline of "what normal looks like"** — per-service baseline so you don't false-alarm during normal high load.
3. **Meaningful, non-spammy alerts** — alert by impact (prioritize user-visible symptoms + error-budget burn-rate), not every little ripple.
4. **Runs end-to-end** — inject an anomaly and the detector **fires**, visibly (alert/log/dashboard). The live run + measurement land in the later stage (#7b); the first stage (#7a) only needs implementation + analysis.

### Definition of Done for #7a (due 18/07) — implement + analysis
No live run required this week. Done when the Jira ticket shows:
1. **Implementation started** — detector + baseline (PR/commit link proving real code).
2. **Analysis (as a doc in the ticket):** pick **≥ 3 metrics** from key service(s) (e.g. checkout p95 latency, cart error-rate, product-catalog saturation…); for **each metric**: why chosen, what the "normal" baseline range is, what counts as anomalous; the detection method you'll use.
3. **Signed ADR.**
> Live e2e run + alert screenshot + precision/recall numbers belong to stage **#7b** (25/07).

### Constraints
- Don't add load/latency to the system through collection/measurement (measurement must be lightweight).
- Within the current budget — don't spin up a heavy cluster "for show".
- Do not touch / disable the incident mechanism (flagd) — see the Rules in RULES.

### Deliverables
Submit via **2 separate Jira tickets** (evidence format in `AI_MANDATE_EVIDENCE.md`):

- **`AI MANDATE #7a` Detection · implement + analysis — due Sat 18/07** *(graded as a doc, no live run yet)*
  - **PR/commit link** showing detector + baseline implemented.
  - **Analysis in the ticket:** the **≥ 3 metrics** chosen (from key services) + per metric: why chosen, "normal" baseline, anomaly threshold; detection method.
  - **Signed ADR.**
- **`AI MANDATE #7b` Detection · live run + measurement — due Sat 25/07**
  - **Screenshot/log of the detector firing e2e** when an incident is injected (mentor turns it on or injects via flagd) + how to reproduce.
  - **Precision/recall/lead-time** measured over a **labeled incident set** (mentor injects K incidents + a normal period), NOT per-service: recall = caught / K; precision = correct fires / total fires; lead-time = from incident start to fire.
  - **Impact-based alerting** (burn-rate, no spam) + expand to more services.

> Teams that already have detection running can keep `#7a` light and focus on `#7b`.

### Where it shows up
The **AI** pillar (AIOps): using AI/statistics to operate. Touches **Reliability** (early detection protects SLO) and **Operational Excellence** (lower time-to-know — MTTD).

> Mandatory for the AIO team across all TFs. The point: after this, incidents **surface via alerts** instead of waiting for a human — proven by one injected incident that the detector catches.
