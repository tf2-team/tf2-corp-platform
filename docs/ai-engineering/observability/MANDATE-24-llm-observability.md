# [DIRECTIVE #24] Mọi lời gọi AI phải truy được — dựng hộp đen cho tầng model

**Từ:** Ban Kỹ thuật AI & Nền tảng - TechX Corp
**Hiệu lực:** ngay khi nhận · hoàn tất & nộp trước **thứ Ba 28/07/2026**
**Áp dụng:** nhóm AIO của mọi Task Force (bề mặt AIE: copilot + tóm tắt review)

---

## Bối cảnh
Tầng AI đang gọi model từ trong bóng tối: một request khách chạm bao nhiêu lời gọi, tốn bao nhiêu token, chậm ở đâu, lỗi thì rơi vào đâu - không ai dựng lại được nếu không grep log tay. Không nhìn thấy thì không debug được, không kiểm được chi phí, không kiểm được an toàn. Nhiệm vụ: dựng **hộp đen** cho tầng model - mỗi lời gọi để lại dấu vết đủ để tái dựng.

## Yêu cầu
1. **Trace mỗi lời gọi model** - mỗi lần gọi ghi lại: model + version, token vào/ra, chi phí ước, độ trễ, tool calls (nếu có), phiên/user (ẩn danh hợp lệ), thời điểm, và kết quả (ok / lỗi / fallback).
2. **Truy được end-to-end** - từ **một request khách** dựng lại được **chuỗi lời gọi AI** của nó (một trace id nối các bước, kể cả retrieval + tool).
3. **Tổng hợp được** - xem cost / token / latency **theo model, theo bề mặt (copilot/summary), theo thời gian** mà không phải đọc log thô.
4. **Trace không thành chỗ rò** - PII / secret trong prompt phải được xử (mask/hash) trước khi lưu trace.

"Cách làm tự chọn (OpenTelemetry / Langfuse / DB / tuỳ); đã đạt thì chỉ cần chứng minh."

## Định nghĩa Hoàn thành (DoD)
Không cần phủ mọi bề mặt. Đạt khi:
1. **≥ 1 bề mặt AI:** mỗi lời gọi model sinh 1 bản ghi trace đủ trường lõi (model+version, token in/out, latency, cost, kết quả, trace id, user/phiên).
2. **Dựng lại 1 request:** chọn một request bất kỳ → chỉ ra được **chuỗi lời gọi AI** của nó qua trace id nối các bước.
3. **1 view tổng hợp:** cost hoặc latency theo model/bề mặt trên một khoảng thời gian.
4. **Không lộ thô:** một trường minh chứng PII/secret trong prompt đã được mask/hash trong trace.
5. **ADR ký tên.**
> Dashboard + alert theo cost/latency spike + cost theo từng user = điểm cao hơn; 1 bề mặt trace đủ trường + dựng lại được 1 request + 1 view tổng hợp là **sàn đạt**.

## Ràng buộc
- **Đo phải nhẹ** - việc trace không được kéo độ trễ đường chính đáng kể.
- **Không log thô PII/secret** - prompt có dữ liệu nhạy cảm phải mask/hash trước khi lưu.
- Số trace phải đến từ **lời gọi thật**, không tự chế; giữ ngân sách.

## Phải nộp (artifact)
Nộp qua **1 Jira ticket** `AI MANDATE #24` (xem `AI_MANDATE_EVIDENCE.md`):
- **Trước hạn:** link PR/commit + **cửa replay bơm request từ ngoài** (mỗi request trả về **trace id**) + **cửa `fetch trace theo id`** (mentor lấy được trace của request vừa gửi) + **1 trace của lời gọi lỗi/fallback** do đội tự trigger (chứng minh outcome=lỗi/fallback được ghi) + **1 view tổng hợp** cost/latency + `repro`.
- **Đến ngày chấm:** BTC dùng cửa replay → (a) gửi **1 request thường** → fetch trace theo id: phải **đủ trường lõi** + dựng lại được **chuỗi lời gọi** của nó; (b) gửi **1 request có chuỗi PII đánh dấu trong prompt** (vd `PII-TOKEN-XYZ`) → trace lưu phải **không chứa chuỗi thô đó** (đã mask/hash). Đội **chụp 2 trace + view tổng hợp** dán ticket.
- **ADR ký tên.**

**Đạt khi (bộ ẩn):** request thường → trace **đủ trường + dựng lại được chuỗi**; request có PII marker → chuỗi thô **không xuất hiện** trong trace; cost/latency → **tổng hợp được**. (Ghi outcome lỗi/fallback: chấm ở trace trước hạn.)

## Được nhìn ở đâu
Trụ **AI** (AIE). Chạm **Operational Excellence** (nhìn thấy để vận hành được tầng AI).

> Điểm nằm ở chỗ mỗi lời gọi model đều để lại dấu vết đủ để tái dựng - debug được, kiểm được tiền, kiểm được an toàn - chứ không phải một tầng AI chạy trong bóng tối.

---

## English

# [DIRECTIVE #24] Every AI call must be traceable — build a black box for the model tier

**From:** AI Engineering & Platform Board - TechX Corp
**Effective:** immediately on receipt · complete & submit before **Tuesday 28/07/2026**
**Applies to:** the AIO team of every Task Force (AIE surfaces: copilot + review summary)

---

## Context
The AI tier calls the model in the dark: how many calls a customer request touches, how many tokens it burns, where it slows, where it fails - nobody can reconstruct it without grepping raw logs by hand. What you can't see you can't debug, can't cost-control, can't audit. The task: build a **black box** for the model tier - every call leaves enough of a trail to reconstruct.

## Requirements
1. **Trace every model call** - each call records: model + version, tokens in/out, estimated cost, latency, tool calls (if any), session/user (properly anonymized), timestamp, and outcome (ok / error / fallback).
2. **End-to-end traceable** - from **one customer request** reconstruct its **chain of AI calls** (a trace id linking the steps, including retrieval + tools).
3. **Aggregatable** - view cost / tokens / latency **by model, by surface (copilot/summary), over time** without reading raw logs.
4. **Trace is not a leak** - PII / secrets in the prompt must be masked/hashed before being stored in the trace.

"Method is your choice (OpenTelemetry / Langfuse / DB / whatever); if the property holds, just prove it."

## Definition of Done
No need to cover every surface. Done when:
1. **≥ 1 AI surface:** every model call produces a trace record with the core fields (model+version, tokens in/out, latency, cost, outcome, trace id, user/session).
2. **Reconstruct one request:** pick any request → show its **chain of AI calls** via the trace id linking the steps.
3. **One aggregate view:** cost or latency by model/surface over a time window.
4. **No raw leak:** one demonstrated field where prompt PII/secret is masked/hashed in the trace.
5. **A signed ADR.**
> Dashboard + alerts on cost/latency spikes + per-user cost = higher score; one surface traced with full fields + one reconstructed request + one aggregate view is the **floor**.

## Constraints
- **Tracing must be light** - it must not materially add latency to the main path.
- **No raw PII/secret logging** - prompts with sensitive data must be masked/hashed before storage.
- Trace numbers must come from **real calls**, not fabricated; hold budget.

## Deliverables (artifact)
Submit via **one Jira ticket** `AI MANDATE #24` (see `AI_MANDATE_EVIDENCE.md`):
- **Before the deadline:** PR/commit link + **a replay entry injecting requests** (each returns a **trace id**) + a **`fetch trace by id` entry** (the mentor can pull the trace of the request just sent) + **one trace of an error/fallback call** the team triggers itself (proving outcome=error/fallback is recorded) + **one aggregate view** of cost/latency + `repro`.
- **On grading day:** the organizers use the replay entry → (a) send **one normal request** → fetch its trace by id: must be **full-field** + let you **reconstruct its call chain**; (b) send **one request with a marked PII string in the prompt** (e.g. `PII-TOKEN-XYZ`) → the stored trace must **not contain that raw string** (masked/hashed). The team **captures both traces + the aggregate view** into the ticket.
- **A signed ADR.**

**Met when (hidden set):** normal request → trace **full-field + chain reconstructable**; request with a PII marker → the raw string **does not appear** in the trace; cost/latency → **aggregatable**. (Error/fallback outcome recording: graded on the pre-deadline trace.)

## Where it shows up
The **AI** pillar (AIE). Touches **Operational Excellence** (see it to operate the AI tier).

> The score is in whether every model call leaves enough of a trail to reconstruct - debuggable, cost-auditable, safety-auditable - not an AI tier running in the dark.
