# [DIRECTIVE #25] Model hỏng hoặc trả rác, tầng AI vẫn không gục — degrade có kiểm soát

**Từ:** Ban Kỹ thuật AI & Nền tảng - TechX Corp
**Hiệu lực:** ngay khi nhận · hoàn tất & nộp trước **thứ Ba 28/07/2026**
**Áp dụng:** nhóm AIO của mọi Task Force (bề mặt AIE: copilot + tóm tắt review)

---

## Bối cảnh
Tính năng AI phụ thuộc một dịch vụ ngoài tầm kiểm soát: model provider có lúc timeout, rate-limit, sập - hoặc **trả về output không dùng được** (JSON hỏng, sai schema). Nếu tầng AI cứ thế trả 500, treo, hay **thực thi tool với tham số rác** mỗi khi model trục trặc thì khách gánh trọn. Một tầng AI trưởng thành phải **degrade có kiểm soát** khi model lỗi *hoặc trả rác* - có đường lui an toàn, không dội cho chết, không hành động bậy, tự hồi khi provider khỏe.

## Yêu cầu
1. **Có đường lui khi model lỗi** - provider timeout / rate-limit / 5xx → hệ **không trả 500, không treo**: chuyển fallback model, trả kết quả từ cache, hạ chế độ suy giảm, hoặc **abstain an toàn + báo rõ**.
2. **Giới hạn thử lại** - có timeout + retry backoff **có trần**, không thử vô hạn làm bão chính mình.
3. **Chặn khi sập kéo dài** - provider lỗi liên tục → **circuit-breaker mở**, ngừng dội, chuyển đường lui; provider khỏe lại → **tự phục hồi**.
4. **Degrade an toàn + trung thực** - thiếu model **không được bịa nội dung**; nếu chất lượng bị ảnh hưởng thì nói rõ đang ở chế độ suy giảm.
5. **Output model phải hợp lệ mới được dùng** - tool-call / kết quả có cấu trúc phải **validate theo schema ở biên**; parse fail / sai schema → **chặn/sửa/retry**, **không crash**, **không thực thi tool với args rác**.

"Cách làm tự chọn (fallback model / cache / hàng đợi / circuit-breaker lib / JSON-schema validate / tuỳ); đã đạt thì chỉ cần chứng minh."

## Định nghĩa Hoàn thành (DoD)
Không cần phủ mọi loại lỗi. Đạt khi:
1. **Ép 1 lỗi provider** (timeout / 5xx / rate-limit giả) trên ≥ 1 bề mặt → hệ **không 500**, đi **đường lui thấy được** (fallback / cache / abstain), người dùng nhận phản hồi có kiểm soát.
2. **Giới hạn thử lại:** chỉ ra timeout + retry backoff có trần trong code/config; ép lỗi không làm hệ **treo vô hạn**.
3. **Circuit-breaker:** ép **chuỗi lỗi kéo dài** → breaker **mở, ngừng dội**; cho provider "khỏe" lại → hệ **tự phục hồi**.
4. **Output rác bị chặn:** tiêm **1 output model hỏng** (blob sai schema) trên bề mặt có tool-call → hệ **không crash, không gọi tool với args rác**, đi đường lui (reject/repair/abstain).
5. **ADR ký tên.**
> Đo % request giữ được khi provider lỗi + độ trễ đường lui + phủ nhiều bề mặt = điểm cao hơn; 1 bề mặt có fallback + retry có trần + breaker tự hồi + chặn output rác là **sàn đạt**.

## Ràng buộc
- **Fallback không được bịa** - hạ chế độ nghĩa là suy giảm/abstain trung thực, **không phải chế nội dung** để lấp chỗ model thiếu.
- **Không né bằng cách vô hiệu cơ chế lỗi** - phải chịu được lỗi thật bơm vào, không tắt inject để qua bài.
- Giữ ngân sách; đo bằng số thật.

## Phải nộp (artifact)
Nộp qua **1 Jira ticket** `AI MANDATE #25` (xem `AI_MANDATE_EVIDENCE.md`):
- **Trước hạn:** link PR/commit + **cửa replay ép lỗi từ ngoài** cho cả 2 loại: (i) lỗi provider (flag/inject timeout/5xx/rate-limit) và (ii) **output model hỏng** (nạp 1 blob sai schema) + log/ảnh **đường lui** + `repro`.
- **Đến ngày chấm:** BTC ép (a) **1 lỗi provider đơn** (kiểm fallback) + (b) **chuỗi lỗi kéo dài** (kiểm circuit-breaker + tự hồi) + (c) **1 output model hỏng** trên bề mặt có tool-call (kiểm chặn args rác). Đội chụp: **hệ không gục** + **đường lui** + **phục hồi** + **tool không chạy args rác** dán ticket.
- **ADR ký tên.**

**Đạt khi (bộ ẩn):** lỗi provider đơn → **không 500**, đi đường lui an toàn; lỗi kéo dài → **breaker mở + ngừng dội**; provider hồi → **tự phục hồi**; output hỏng → **không crash + không exec args rác**; degrade → **không bịa**.

## Được nhìn ở đâu
Trụ **AI** (AIE). Chạm **Reliability** (chịu lỗi phụ thuộc ngoài). Nối #17 nhưng cho tầng model.

> Điểm nằm ở chỗ khi model provider trục trặc, khách vẫn nhận phản hồi có kiểm soát - đường lui an toàn, không dội cho chết, tự hồi - chứ không phải cả tính năng AI gục theo.

---

## English

# [DIRECTIVE #25] The model fails or returns garbage, the AI tier still holds — controlled degradation

**From:** AI Engineering & Platform Board - TechX Corp
**Effective:** immediately on receipt · complete & submit before **Tuesday 28/07/2026**
**Applies to:** the AIO team of every Task Force (AIE surfaces: copilot + review summary)

---

## Context
The AI feature depends on a service outside your control: the model provider will sometimes time out, rate-limit, go down - or **return unusable output** (malformed JSON, wrong schema). If the AI tier just returns 500, hangs, or **executes a tool with garbage arguments** whenever the model misbehaves, the customer eats it. A mature AI tier must **degrade in a controlled way** when the model fails *or returns garbage* - a safe fallback path, no hammering to death, no reckless action, self-recovery when the provider is healthy again.

## Requirements
1. **A fallback path on model failure** - provider timeout / rate-limit / 5xx → the system **does not return 500, does not hang**: switch to a fallback model, serve a cached result, drop to a degraded mode, or **abstain safely + say so clearly**.
2. **Bounded retries** - timeout + retry with **capped** backoff, never infinite retries that storm yourself.
3. **Contain sustained outages** - continuous provider errors → **circuit-breaker opens**, stops hammering, switches to the fallback path; provider healthy again → **self-recovers**.
4. **Safe + honest degradation** - a missing model **must not fabricate content**; if quality is affected, state clearly that it's in degraded mode.
5. **Model output must be valid before use** - tool-calls / structured results must be **schema-validated at the boundary**; parse fail / schema mismatch → **reject/repair/retry**, **no crash**, **never execute a tool with garbage args**.

"Method is your choice (fallback model / cache / queue / circuit-breaker lib / JSON-schema validation / whatever); if the property holds, just prove it."

## Definition of Done
No need to cover every failure type. Done when:
1. **Force one provider failure** (timeout / 5xx / simulated rate-limit) on ≥ 1 surface → the system **does not 500**, takes a **visible fallback path** (fallback / cache / abstain), the user gets a controlled response.
2. **Bounded retries:** show timeout + capped retry backoff in code/config; forcing errors does not **hang indefinitely**.
3. **Circuit-breaker:** force a **sustained error streak** → breaker **opens, stops hammering**; let the provider "recover" → the system **self-recovers**.
4. **Garbage output blocked:** inject **one malformed model output** (schema-mismatched blob) on a tool-calling surface → the system **does not crash, does not call the tool with garbage args**, takes a fallback path (reject/repair/abstain).
5. **A signed ADR.**
> Measuring % of requests preserved during provider failure + fallback latency + covering more surfaces = higher score; one surface with a fallback + capped retries + a self-recovering breaker + garbage-output blocking is the **floor**.

## Constraints
- **Fallback must not fabricate** - degrading means honest degradation/abstention, **not inventing content** to paper over the missing model.
- **No dodging by disabling fault injection** - must withstand real injected failures, don't turn off injection to pass.
- Hold budget; measure with real numbers.

## Deliverables (artifact)
Submit via **one Jira ticket** `AI MANDATE #25` (see `AI_MANDATE_EVIDENCE.md`):
- **Before the deadline:** PR/commit link + **a replay entry that forces failures externally** for both kinds: (i) provider failures (flag/inject timeout/5xx/rate-limit) and (ii) **malformed model output** (feed a schema-mismatched blob) + log/image of the **fallback path** + `repro`.
- **On grading day:** the organizers force (a) **one single provider failure** (fallback check) + (b) a **sustained error streak** (circuit-breaker + self-recovery check) + (c) **one malformed model output** on a tool-calling surface (garbage-args-blocking check). The team captures: **system holds** + **fallback path** + **recovery** + **tool did not run garbage args** into the ticket.
- **A signed ADR.**

**Met when (hidden set):** single provider failure → **no 500**, safe fallback path; sustained failure → **breaker opens + stops hammering**; provider recovers → **self-recovers**; malformed output → **no crash + no garbage-arg execution**; degradation → **no fabrication**.

## Where it shows up
The **AI** pillar (AIE). Touches **Reliability** (withstanding an external dependency's failure). Builds on #17 but for the model tier.

> The score is in whether, when the model hiccups or returns garbage, the customer still gets a controlled response - safe fallback, no hammering to death, no reckless action, self-recovery - rather than the whole AI feature going down with it.