# Day 1 ClickUp Backlog

> Nội dung được tổng hợp từ [Eight-Day Implementation Plan](./eight-day-implementation-plan.md), [AI Shopping Experience Backlog](./ai-shopping-experience-backlog.md) và [Implementation Guide](./implementation-guide.md).

## Mục tiêu Ngày 1

AI assistant hiện chỉ nhận `product_id`, `question` và trả về một đoạn văn bản. Hệ thống chưa có cấu trúc cho nguồn dẫn chứng, kết quả tìm kiếm, hội thoại nhiều lượt hoặc hành động chờ xác nhận.

Trong Ngày 1, hai developer sẽ thiết kế các cấu trúc dữ liệu và quy tắc dùng chung để bắt đầu triển khai từ Ngày 2. Phạm vi ngày này là chốt contract và kiểm tra khả năng tích hợp, chưa triển khai đầy đủ các tính năng.

## Task 1 - Thiết kế câu trả lời AI có dẫn nguồn và quy tắc an toàn

**Developer:** AI Engineer 1 - Trustworthiness

### Bối cảnh

Câu trả lời AI hiện là văn bản thuần nên người dùng không biết thông tin đến từ review nào. Hệ thống cũng chưa có quy tắc rõ ràng để từ chối câu trả lời thiếu bằng chứng hoặc xử lý review chứa chỉ dẫn độc hại và PII.

### Cần làm

- Xác định cấu trúc câu trả lời gồm nội dung trả lời, các nhận định, nguồn dẫn chứng và trạng thái kết quả.
- Xác định cách tạo mã định danh nguồn (source ID), kiểm tra mối liên kết giữa nhận định và nguồn, và điều kiện từ chối trả lời khi thiếu bằng chứng.
- Xác định cách xử lý review như dữ liệu không đáng tin cậy, giới hạn tool được gọi và loại bỏ PII khỏi model payload, log và trace.

### Kết quả cần đạt

- Có contract hoặc schema đủ rõ để triển khai A1.1 và A1.2 từ Ngày 2.
- Có một ví dụ câu trả lời có nguồn và một ví dụ từ chối trả lời.
- Các quy tắc về nguồn, tool và PII không còn điểm chưa rõ ảnh hưởng đến việc triển khai.

## Task 2 - Thiết kế contract cho tìm kiếm, hội thoại và xác nhận giỏ hàng

**Developer:** AI Engineer 2 - Shopping Workflow

### Bối cảnh

`SearchProducts` hiện chỉ nhận một chuỗi tìm kiếm. AI assistant chưa có mã hội thoại, chưa lưu thứ tự sản phẩm đã tìm thấy và chưa có trạng thái chờ người dùng xác nhận trước khi thêm sản phẩm vào giỏ.

### Cần làm

- Xác định cấu trúc tìm kiếm gồm `query`, `max_price`, `category` và danh sách product ID trả về từ catalog.
- Xác định cấu trúc cho `conversation_id`, thứ tự `product_references` và `pending_action`.
- Xác định quy tắc cart chỉ được thay đổi sau khi backend xác minh yêu cầu xác nhận (confirmation); user ID phải lấy từ phiên đăng nhập đã xác thực.
- Cập nhật `pb/demo.proto`, tạo lại client/server code được sinh từ proto và ghi nhận blocker tích hợp nếu có.

### Kết quả cần đạt

- Có shared contract đủ rõ để triển khai A2.1, A2.3 và phần conversation state của A2.4.
- Có ví dụ cho kết quả tìm kiếm, tham chiếu “sản phẩm đầu tiên” và hành động thêm vào giỏ đang chờ xác nhận.
- `pb/demo.proto` compile thành công và các luồng hiện có không bị hỏng sau khi tạo lại code.

## File kết quả cần gửi

Mỗi developer tạo một file Markdown và đính kèm file hoặc link repository vào ClickUp.

| Task | Tên file kết quả |
| --- | --- |
| Task 1 | `day-1-task-1-trustworthiness-result.md` |
| Task 2 | `day-1-task-2-shopping-workflow-result.md` |

Hai file phải giữ nguyên các heading trong mẫu dưới đây. Nếu một mục không phát sinh nội dung, ghi `Không có` thay vì xóa mục.

### Mẫu nội dung bắt buộc

~~~markdown
# Day 1 Result - [Task name]

- **Developer:** [Tên người thực hiện]
- **Task:** [Task 1 hoặc Task 2]

## 1. Kết quả

[Tóm tắt trong 2-3 câu: đã hoàn thành gì và đầu ra được dùng cho bước nào tiếp theo.]

## 2. Quyết định đã chốt

| Hạng mục | Quyết định |
| --- | --- |
| [Tên hạng mục] | [Quyết định cuối cùng] |

## 3. Contract và ví dụ

### Contract

[Liệt kê các trường dữ liệu, quy tắc hoặc link tới schema/proto.]

### Ví dụ

- **Đầu vào:** [Mô tả ngắn]
- **Đầu ra:** [Payload, trạng thái hoặc kết quả mong đợi]

## 4. Tệp và liên kết

- [File, commit hoặc PR]

## 5. Blockers

- Không có.
~~~

### Ví dụ ngắn đã điền

~~~markdown
# Day 1 Result - Grounded AI response

- **Developer:** Nguyễn Văn A
- **Task:** Task 1

## 1. Kết quả

Đã chốt cấu trúc câu trả lời có dẫn nguồn và quy tắc từ chối khi thiếu bằng chứng. Contract này có thể dùng để triển khai A1.1 từ Ngày 2.

## 2. Quyết định đã chốt

| Hạng mục | Quyết định |
| --- | --- |
| Nguồn dẫn chứng | Mỗi nhận định phải có ít nhất một source ID hợp lệ. |
| Thiếu bằng chứng | Trả trạng thái `ABSTAINED`, không suy đoán. |

## 3. Contract và ví dụ

### Contract

Response gồm `answer`, `claims`, `sources` và `status`.

### Ví dụ

- **Đầu vào:** Câu hỏi không có thông tin trong review.
- **Đầu ra:** `status = ABSTAINED` và không có claim.

## 4. Tệp và liên kết

- `<document-or-commit-link>`

## 5. Blockers

- Không có.
~~~

Task 2 dùng đúng cấu trúc trên; phần contract mô tả search, conversation và pending action, còn phần ví dụ trình bày các case tương ứng của Task 2.

## Hoàn thành Ngày 1 khi

- Shared contract được merge vào branch `aie`.
- `AskProductAIAssistant` và `SearchProducts` vẫn hoạt động sau thay đổi.
- Không còn blocker chưa có hướng xử lý cho công việc Ngày 2.
