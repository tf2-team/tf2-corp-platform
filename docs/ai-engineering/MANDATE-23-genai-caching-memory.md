# [DIRECTIVE #23] Tầng AI phải chạy như sản phẩm thật — có cache, có trí nhớ

> Khung report/evidence để hoàn thiện Mandate: [mandate23.md](./mandate23.md)

**Từ:** Ban Kỹ thuật AI & Nền tảng - TechX Corp
**Hiệu lực:** ngay khi nhận · hoàn tất & nộp trước **thứ Ba 28/07/2026**
**Áp dụng:** nhóm AIO của mọi Task Force (bề mặt AIE: copilot + tóm tắt review)

---

## Bối cảnh
Tính năng AI đang phục vụ khách thật, nhưng vẫn chạy như bản demo: mỗi yêu cầu là một lần gọi model từ đầu, hỏi lại câu vừa hỏi vẫn tính tiền lần nữa, và quay lại phiên sau thì hệ quên sạch người dùng là ai. Một tầng AI trưởng thành phải **không đốt token cho việc lặp**, **nhớ được ngữ cảnh** trong một phiên và xuyên phiên - mà vẫn **không nhớ nhầm sang người khác**.

## Yêu cầu
1. **Cache** - không gọi lại model cho cùng một yêu cầu: có tầng cache (khớp chính xác và/hoặc ngữ nghĩa) với hit/miss đo được, có TTL + cơ chế vô hiệu khi nguồn đổi, và cache **đúng ranh giới người dùng** (không phục vụ kết quả của người này cho người khác).
2. **Bộ nhớ ngắn hạn (trong phiên)** - trong một phiên hội thoại, hệ giữ ngữ cảnh qua nhiều lượt: lượt sau hiểu được cái đã nói ở lượt trước, người dùng không phải lặp lại.
3. **Bộ nhớ dài hạn (xuyên phiên)** - hệ lưu và truy hồi được thông tin bền (sở thích / lịch sử người dùng) qua các phiên khác nhau, có **cô lập theo người dùng** và xử lý PII đúng.
4. **Đo được lợi ích** - chứng minh bằng số thật: cache hit-rate + độ trễ/chi phí trước-sau trên một bộ yêu cầu có lặp; bộ nhớ truy hồi đúng qua các lượt/phiên.

"Cách làm tự chọn (Redis / vector cache / DB / tuỳ); đã đạt thì chỉ cần chứng minh."

## Định nghĩa Hoàn thành (DoD)
Không cần phủ mọi bề mặt. Đạt khi:
1. **Cache thật trên ≥ 1 bề mặt AI:** chạy một bộ yêu cầu có lặp → báo **hit-rate + độ trễ/chi phí trước-sau** (số đo thật).
2. **Ngắn hạn:** một phiên copilot **≥ 3 lượt** phụ thuộc ngữ cảnh - lượt sau tham chiếu đúng lượt trước, không bắt người dùng nhắc lại.
3. **Dài hạn:** lưu ≥ 1 loại thông tin người dùng ở phiên A → phiên B (mới) **truy hồi lại đúng**; và một người dùng khác **không** thấy được thông tin đó.
4. **ADR ký tên.**
> Nhiều bề mặt + semantic cache + invalidation theo sự kiện + số tiết kiệm rõ = điểm cao hơn; 1 bề mặt có cache đo được + ngắn & dài hạn chạy được + cô lập user là **sàn đạt**.

## Ràng buộc
- **Cấm giả hit:** không hardcode / seed sẵn câu trả lời để cache "trúng"; hit phải đến từ yêu cầu thật lặp lại.
- **Không rò chéo người dùng:** cache + bộ nhớ phải cô lập theo user (nối #6); PII trong bộ nhớ không được lộ.
- **Không trả cũ sai:** nguồn đã đổi mà cache vẫn trả kết quả cũ = fail; phải có TTL/invalidation.
- Giữ ngân sách; đo bằng số thật, không hạ chuẩn để qua bài.

## Phải nộp (artifact)
Nộp qua **1 Jira ticket** `AI MANDATE #23` (xem `AI_MANDATE_EVIDENCE.md`):
- **Trước hạn:** link PR/commit + **cửa replay nhận từ ngoài** `{yêu cầu, user_id, session_id}` và **trả kèm cờ `cache: hit|miss`** cho mỗi lời gọi (để mentor verify được hit thật, không chỉ "nhanh hơn"); **chỉ ra 1 bản ghi nguồn mentor có thể đổi** để test invalidation; + **bảng số** hit-rate / latency / cost trước-sau + `repro`.
- **Đến ngày chấm:** BTC dùng cửa replay bơm **bộ ca ẩn** - (a) gửi **cùng 1 yêu cầu 2 lần** → lần 2 phải `cache: hit`; rồi **đổi bản ghi nguồn** → hỏi lại phải `miss` + trả số mới (invalidation); (b) hội thoại **≥3 lượt cùng session_id** phụ thuộc ngữ cảnh (ngắn hạn); (c) **session_id mới, cùng user_id** hỏi lại thứ đã cung phiên trước (dài hạn); (d) **user_id khác** hỏi cùng câu → không thấy dữ liệu người kia (cross-user). Đội **chụp per-case (kèm cờ hit/miss) + số tổng** dán ticket.
- **ADR ký tên.**

**Đạt khi (bộ ẩn):** yêu cầu lặp → **cache hit** (đo được) + nguồn đổi → **không trả cũ sai**; đa lượt → **giữ ngữ cảnh**; phiên mới → **nhớ lại đúng**; cross-user → **không rò**.

## Được nhìn ở đâu
Trụ **AI** (AIE). Chạm **Cost Optimization** (không đốt token lặp) + **Performance Efficiency** (giảm độ trễ).

> Điểm nằm ở chỗ tầng AI chạy như sản phẩm thật - không đốt token cho việc lặp, nhớ được ngữ cảnh trong và xuyên phiên, và không nhớ nhầm sang người khác - chứng minh bằng số, không phải lời.

---

## English

# [DIRECTIVE #23] The AI tier must run like a real product — with caching and memory

**From:** AI Engineering & Platform Board - TechX Corp
**Effective:** immediately on receipt · complete & submit before **Tuesday 28/07/2026**
**Applies to:** the AIO team of every Task Force (AIE surfaces: copilot + review summary)

---

## Context
The AI features serve real customers but still run like a demo: every request is a fresh model call, asking the same question again is billed again, and coming back in a later session the system forgets who the user is. A mature AI tier must **not burn tokens on repeats**, must **remember context** within a session and across sessions - while **never remembering one user's data into another's**.

## Requirements
1. **Caching** - no repeated model call for the same request: a cache layer (exact and/or semantic) with measurable hit/miss, TTL + invalidation when the source changes, and cached **within the correct user boundary** (never serve one user's result to another).
2. **Short-term memory (in-session)** - within a conversation the system keeps context across turns: a later turn understands what an earlier turn said, the user need not repeat.
3. **Long-term memory (cross-session)** - the system stores and retrieves durable info (user preferences / history) across separate sessions, with **per-user isolation** and correct PII handling.
4. **Measured benefit** - prove with real numbers: cache hit-rate + latency/cost before-after on a repeating request set; memory retrieved correctly across turns/sessions.

"Method is your choice (Redis / vector cache / DB / whatever); if the property holds, just prove it."

## Definition of Done
No need to cover every surface. Done when:
1. **Real cache on ≥ 1 AI surface:** run a repeating request set → report **hit-rate + latency/cost before-after** (real measured numbers).
2. **Short-term:** one copilot session of **≥ 3 context-dependent turns** - later turns correctly reference earlier ones, no user repetition.
3. **Long-term:** store ≥ 1 user info item in session A → a new session B **retrieves it correctly**; and a different user **cannot** see it.
4. **A signed ADR.**
> More surfaces + semantic cache + event-based invalidation + clear savings numbers = higher score; one surface with a measured cache + working short & long-term memory + user isolation is the **floor**.

## Constraints
- **No faked hits:** do not hardcode / pre-seed answers to make the cache "hit"; hits must come from genuinely repeated requests.
- **No cross-user leakage:** cache + memory must be per-user isolated (builds on #6); PII in memory must not leak.
- **No stale-wrong serving:** if the source changed and the cache still returns the old result = fail; TTL/invalidation required.
- Hold budget; measure with real numbers, do not lower the bar to pass.

## Deliverables (artifact)
Submit via **one Jira ticket** `AI MANDATE #23` (see `AI_MANDATE_EVIDENCE.md`):
- **Before the deadline:** PR/commit link + **a replay entry accepting** `{request, user_id, session_id}` from outside that **returns a `cache: hit|miss` flag** per call (so the mentor can verify a real hit, not just "faster"); **point to one source record the mentor can change** to test invalidation; + a **numbers table** of hit-rate / latency / cost before-after + `repro`.
- **On grading day:** the organizers use the replay entry to inject a **hidden case set** - (a) send **the same request twice** → 2nd must be `cache: hit`; then **change the source record** → ask again must be `miss` + return the new value (invalidation); (b) a **≥3-turn same-session_id** context-dependent chat (short-term); (c) a **new session_id, same user_id** asking back something from the prior session (long-term); (d) a **different user_id** asking the same question → must not see the other's data (cross-user). The team **captures per-case (with the hit/miss flag) + aggregate numbers** into the ticket.
- **A signed ADR.**

**Met when (hidden set):** repeated request → **cache hit** (measurable) + source changed → **no stale-wrong**; multi-turn → **context held**; new session → **remembered correctly**; cross-user → **no leak**.

## Where it shows up
The **AI** pillar (AIE). Touches **Cost Optimization** (no token burn on repeats) + **Performance Efficiency** (lower latency).

> The score is in whether the AI tier runs like a real product - no token burn on repeats, remembers context within and across sessions, and never remembers one user into another - proven by numbers, not words.
