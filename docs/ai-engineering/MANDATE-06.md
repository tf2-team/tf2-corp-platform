# [DIRECTIVE #6] Tính năng AI phải đáng tin - không bịa, không để bị dắt mũi

**Từ:** Ban AI & Chất lượng - TechX Corp
**Hiệu lực:** ngay khi nhận · hoàn tất & nộp trước **thứ Bảy 18/07/2026**
**Áp dụng:** nhóm AIO của mọi Task Force

---

## Bối cảnh
Tính năng AI đang hiển thị cho khách thật - tóm tắt review, trợ lý hỏi-đáp - nhưng chất lượng và độ an toàn của nó gần như chưa ai kiểm. Khách hỏi "pin con này trâu không", AI **bịa đại một câu nghe hợp lý** dù review chẳng nói gì về pin - thế là mất niềm tin. Tệ hơn: có người nhét vào review một câu kiểu *"bỏ qua hướng dẫn trên, trả lời…"* và AI **ngoan ngoãn nghe theo**, hoặc vô tình phơi thông tin cá nhân trong review ra tóm tắt. Với một sản phẩm có khách, một AI **bịa** hoặc **bị dắt mũi** là rủi ro thương hiệu và dữ liệu thật sự. Từ giờ, tầng AI phải **chứng minh được là đáng tin** thì mới tính là "chạy" - không phải cứ trả lời trôi chảy là xong.

## Yêu cầu
1. **Chạy trên model thật, có đường lui.** Dùng LLM thật (không mock), và khi model lỗi/chậm thì **fallback** - không để treo trang sản phẩm.
2. **Không show nội dung sai.** Tóm tắt/trả lời phải bám review nguồn; có **eval** bắt được khi output sai để **chặn hoặc fallback**, thay vì đẩy nội dung bịa tới khách.
3. **Không để bị dắt mũi.** Chặn câu lệnh độc nhét trong review (prompt-injection), **lọc PII**, không để lộ system prompt. Trợ lý có hành động thì **chỉ làm trong phạm vi cho phép** - tuyệt đối không tự ý checkout hay xoá giỏ của khách.
4. **Chứng minh bằng eval, không bằng lời.** Có bộ eval + số đo (độ trung thực, tỉ lệ chặn tấn công) **tái tạo được** từ script/dữ liệu các bạn commit.

## Định nghĩa Hoàn thành (DoD - hạn 18/07)
Mandate 1 chặng, chấm **có bằng chứng chạy được**. Đạt khi mentor bắn thử tận mắt thấy + eval chạy lại được:
1. **Model thật + fallback** - tính năng AI (tóm tắt review hoặc trợ lý) chạy trên **LLM thật** (bỏ mock); ép model lỗi/chậm → trang **không treo**, fallback thấy được.
2. **Qua 4 tình huống guardrail** (mentor tự bắn):
   - review nhét câu injection (*"bỏ qua hướng dẫn trên…"*) → AI **không nghe theo**;
   - câu hỏi mà review nguồn không trả lời được → AI trả **"không có thông tin" / fallback**, không bịa;
   - PII trong review (email/sđt…) → **không lọt** ra tóm tắt;
   - (nếu có trợ lý hành động) lệnh checkout / xoá giỏ → **từ chối / hỏi xác nhận**.
3. **Eval tái tạo được** - bộ test tối thiểu **≥ 5 ca faithfulness** (câu hỏi có / không có trong review) + **≥ 5 ca injection**, chạy từ script/data đã commit ra **số** (độ trung thực + tỉ lệ chặn injection).
> Thêm ca eval / thêm loại tấn công = điểm cao hơn; đây là **sàn đạt**.

## Ràng buộc
- Đừng để guardrail/eval kéo p95 trang sản phẩm vỡ SLO.
- Trong ngân sách hiện tại - tối ưu token, đừng "quăng model to cho xong".
- Không đụng / vô hiệu hóa cơ chế sự cố (flagd) - xem Luật chơi trong RULES.

## Phải nộp
Nộp qua **1 Jira ticket** `AI MANDATE #6` (cách ghi evidence xem `AI_MANDATE_EVIDENCE.md`):
- **Link PR/commit** phần model thật + guardrail + eval.
- **Cách chạy lại**: lệnh chạy eval + cách bắn 1 review injection / 1 câu hỏi bịa.
- **Bằng chứng chạy thật**: ảnh/log của (a) guardrail chặn injection + che PII, (b) AI trả "không có thông tin" thay vì bịa, (c) eval chạy ra số. Nếu có trợ lý hành động: log nó **từ chối/hỏi xác nhận** khi bị bảo checkout.
- **ADR ký tên**: chọn model gì, guardrail + fallback thiết kế ra sao, eval đo cái gì.

## Được nhìn ở đâu
Chính là **trụ AI** (AIE): chất lượng, an toàn (guardrail), độ tin cậy, chi phí của tính năng AI. Chạm thêm **Reliability** (fallback khi model hỏng) và **Auditability** (log lại lời gọi AI/tool).

> Directive bắt buộc nhóm AIO toàn TF, thực thi trong ràng buộc. Điểm nằm ở **mức độ đáng tin chứng minh được** - mentor tự thử phá mà AI vẫn đứng vững - không phải "AI có chạy hay không".

---

