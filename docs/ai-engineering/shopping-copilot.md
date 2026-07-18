# Build a Trustworthy Single-Request Shopping Copilot

## Motivation

Ask AI hiện chỉ hỗ trợ hỏi đáp trong phạm vi một sản phẩm đang mở. Shopping Copilot cần giúp người dùng mô tả nhu cầu bằng ngôn ngữ tự nhiên, tìm sản phẩm thật từ catalog và nhận giải thích có bằng chứng từ catalog hoặc review nguồn.

Phiên bản đầu tiên chỉ xử lý một request độc lập. Mục tiêu là hoàn thiện search, grounding, guardrails, fallback và eval trước khi mở rộng sang hội thoại nhiều lượt hoặc hành động ghi dữ liệu.

## Goal

- Tìm sản phẩm theo từ khóa, category, mức giá và đặc tính trong câu người dùng.
- Chỉ trả sản phẩm có `product_id` thật từ catalog.
- Trả lời hoặc giải thích đề xuất bằng claim có source hợp lệ.
- Chặn prompt injection, lọc PII và không làm lộ system prompt.
- Fallback an toàn khi model hoặc downstream service lỗi/chậm.
- Chứng minh độ trung thực và khả năng chặn injection bằng bộ eval tối thiểu, tái tạo được.

## Scope

### Included

- Natural-language product search trong một request.
- Structured intent gồm query, category, price và features.
- Catalog search, hard filtering và ranking.
- Review-grounded Q&A cho sản phẩm được xác định trong request hiện tại.
- Trang UI riêng hiển thị điều kiện đã hiểu, product results, claims và citations.
- Các trạng thái `GROUNDED`, `NO_RESULTS`, `ABSTAINED`, `BLOCKED` và `FALLBACK`.

### Excluded

- Message history, `conversation_id` và reference resolution giữa nhiều lượt.
- Agent loop mở không giới hạn.
- Pending cart action và confirmation flow.
- AI tự gọi `cart.add`, checkout, empty cart, payment hoặc refund.

## Feature Flow

```text
User request
  -> Input guardrail
  -> Structured intent parsing
  -> Read-only tool execution
  -> Result sanitization
  -> Grounded response generation
  -> Claim/source validation
  -> Output guardrail
  -> Response or safe fallback
```

Một request có thể gọi model và read tool qua nhiều bước nội bộ, nhưng phải có deadline, giới hạn số tool call và fallback rõ ràng.

## Backend Implementation

### Intent and Search

- Dùng model thật với structured output để bóc tách `intent`, `query`, `category`, `max_price`, `features` và nhu cầu đọc review.
- Backend kiểm tra schema và chuẩn hóa dữ liệu trước khi gọi tool.
- Gọi Product Catalog service để lấy candidate products.
- Backend áp dụng các điều kiện quan trọng như giá, category và product ID bằng code.
- Nếu không có kết quả phù hợp, trả `NO_RESULTS`; không để model tạo sản phẩm thay thế.

### Tool Policy

Chỉ đăng ký các read tool cần thiết:

- `catalog.search`
- `catalog.get`
- `reviews.get`

Backend phải kiểm tra tool name và arguments. Product ID dùng ở bước sau phải thuộc kết quả catalog của chính request đó. Không đăng ký bất kỳ write tool nào.

### Grounding and Safety

- Tái sử dụng input/output guardrails, review sanitization, grounded claims, citation validation và abstention từ Product Reviews.
- Catalog facts phải trỏ tới catalog source; review claims phải trỏ tới đúng review và đúng product.
- Claim không đủ bằng chứng hoặc dùng source không hợp lệ phải bị loại.
- Nếu không còn claim hợp lệ, trả `ABSTAINED`; không trả model output chưa qua validation.
- Xem câu người dùng, catalog text và review là untrusted input.
- Scan prompt injection, PII và system-prompt leakage ở các boundary phù hợp.
- Đặt timeout cho model và downstream tools; lỗi ở bất kỳ bước nào phải trả fallback an toàn.
- Log/trace chỉ chứa safe metadata, không chứa raw prompt, raw review, PII hoặc secrets.

### Response Contract

Response cần đủ dữ liệu để UI render mà không parse text tự do:

```text
status
interpreted_criteria
products[]: product_id, name, price
claims[]: text, sources[]
sources[]: source_type, source_id, product_id
reason
```

## Frontend Implementation

Tạo trang Shopping Copilot riêng, không dùng UI Ask AI trong product detail làm entry point chính.

UI gồm:

- Query input và một số câu hỏi mẫu.
- Interpreted criteria để người dùng thấy Copilot hiểu điều kiện nào.
- Product cards lấy từ catalog thật và link tới product detail.
- Grounded claims với citation có thể mở review nguồn.
- Loading, no-results, abstained, blocked và fallback states.

Không cần chat history hoặc conversation sidebar. Lỗi AI không được làm treo trang hoặc ngăn người dùng tiếp tục duyệt sản phẩm.

## Reproducible Eval

Commit một bộ eval tối thiểu gồm data và script chạy lại được:

- Ít nhất 5 ca faithfulness, gồm câu hỏi có câu trả lời trong review và câu hỏi không có đủ thông tin trong review.
- Ít nhất 5 ca prompt injection, đặt trong câu hỏi người dùng hoặc nội dung review.
- Mỗi ca có input và expected outcome rõ ràng để script tự kiểm tra.

Script phải in kết quả từng ca và hai số tổng hợp:

```text
Faithfulness rate = số ca faithfulness đạt / tổng ca faithfulness
Injection blocking rate = số ca injection bị chặn / tổng ca injection
```

Ca faithfulness chỉ đạt khi câu trả lời bám review nguồn hoặc abstain đúng lúc thiếu bằng chứng. Ca injection chỉ đạt khi nội dung độc không điều khiển model, không làm lộ system prompt và không kích hoạt tool ngoài phạm vi.

## Acceptance Criteria

- Query tự nhiên trả về sản phẩm có thật và đúng các hard constraint.
- No-results không sinh sản phẩm giả.
- Claim có citation đúng source và đúng product; thiếu evidence thì abstain.
- Prompt injection, PII và yêu cầu lộ system prompt được chặn hoặc làm sạch.
- Tool ngoài allow-list hoặc argument ngoài phạm vi bị từ chối.
- Model/tool lỗi hoặc timeout trả fallback trong giới hạn thời gian và không làm treo UI.
- UI hiển thị interpreted criteria, product results, citations và các response states.
- Tool registry không có cart write, checkout hoặc empty-cart capability.
- Có ít nhất 5 ca faithfulness và 5 ca injection chạy được từ data/script đã commit.
- Script xuất được faithfulness rate và injection blocking rate dưới dạng số.

## Deliverables

- Backend single-request Shopping Copilot và service integrations.
- Structured API contract cùng generated client code liên quan.
- Trang UI Shopping Copilot.
- Unit/integration tests và bộ eval chạy model thật.
- Hướng dẫn chạy local và chạy eval.
