# Ghi nhận hệ thống (Findings) - Lớp AI (Dành cho AIOps)

Tài liệu này tổng hợp các phát hiện từ việc phân tích mã nguồn của hai dịch vụ `product-reviews` và `llm`, nhằm cung cấp thông tin cho đội AIOps biết cần phải giám sát (monitor) những gì và các điểm yếu hệ thống ở đâu.

## 1. Cách `product-reviews` gọi `llm` để tóm tắt AI

Luồng tóm tắt AI được triển khai trong hàm `get_ai_assistant_response` (`product_reviews_server.py`). Dịch vụ này sử dụng bộ SDK Python chính thức của OpenAI (`openai` module) để gọi đến LLM (hoặc dịch vụ LLM giả lập - mock LLM).
- **Gọi 2 nhịp (Two-turn generation):**
  - **Nhịp 1:** Gửi câu hỏi của người dùng và danh sách các "tools" (bao gồm `fetch_product_reviews` và `fetch_product_info`). LLM sẽ phân tích và trả về yêu cầu gọi tool (`tool_choice="auto"`).
  - **Xử lý Tool:** Dịch vụ nhận danh sách `tool_calls`, thực thi các hàm tương ứng (truy vấn DB hoặc gọi gRPC sang `product-catalog`), sau đó gom kết quả phản hồi của tool nối vào mảng `messages`.
  - **Nhịp 2:** Gọi LLM lần nữa kèm theo kết quả của tool, và yêu cầu LLM tổng hợp ra câu trả lời cuối cùng để trả về cho người dùng.

## 2. Telemetry & Spans (OpenTelemetry Instrumentation)

Dịch vụ đã được cấu hình OpenTelemetry đầy đủ (Traces, Metrics, Logs):
- **Traces (Spans):**
  - Khởi tạo các spans bằng `tracer.start_as_current_span`.
  - Có các span chính: `get_product_reviews`, `get_average_product_review_score`, `get_ai_assistant_response`.
  - Các thuộc tính (attributes) đang được gắn vào trace: `app.product.id`, `app.product_reviews.count`, `app.product_reviews.average_score`, và đặc biệt là `app.product.question` (nơi đang ghi nhận nguyên văn câu hỏi của user - **cẩn thận nguy cơ lộ PII**).
  - Khi gặp lỗi trong nhánh mock, span sử dụng `span.record_exception(e)` và `span.set_status(Status(StatusCode.ERROR))`.
- **Metrics:**
  - `app_product_review_counter`: Đếm tổng số review được trả về (gắn tag `product.id`).
  - `app_ai_assistant_counter`: Đếm tổng số lượt yêu cầu AI Assistant (gắn tag `product.id`).
  - **Khoảng trống giám sát:** Hiện chưa có metric nào đo thời gian phản hồi (latency) của LLM, số lượng token sử dụng, tỉ lệ lỗi, hay bộ đếm cache.
- **Logs:** Sử dụng `OTLPLogExporter` để đẩy log có cấu trúc về backend giám sát (chứa nguyên văn `messages` gửi cho LLM - **nguy cơ lộ PII cao**).

## 3. Các điểm kết nối Feature Flags (Flagd Hooks)

Dịch vụ sử dụng OpenFeature SDK với `FlagdProvider` kết nối tới `flagd` (port 8013). Các cờ tính năng đang được dùng:
- **`llmRateLimitError`:** Kích hoạt xác suất 50% giả lập lỗi 429 (Rate Limit). Khi bật, request sẽ đi qua nhánh mock LLM (`techx-llm-rate-limit`) và cố tình quăng lỗi.
- **`llmInaccurateResponse`:** 
  - Trong `product_reviews_server.py`: Khi bật và `product_id` là `L9ECAV7KIM`, prompt sẽ bị sửa thành "make the answer inaccurate" (cố tình bắt LLM trả lời sai).
  - Trong `llm/app.py` (Mock LLM): Lấy một câu trả lời sai đã được hardcode từ file JSON `inaccurate-product-review-summaries.json` để trả về.
  *(Lưu ý: Không can thiệp vào các logic này vì chúng phục vụ cho việc kiểm thử của hệ thống).*

## 4. Xử lý lỗi & Fallback khi LLM gặp sự cố / chậm

- **Ở nhánh giả lập lỗi (Mock error branch):** Đã có cơ chế `try...except`, ghi nhận lỗi vào trace và có fallback thân thiện trả về: *"The system is unable to process your response. Please try again later."*
- **Ở nhánh chạy thực tế (Real LLM branch - dòng 218 & 292):** **KHÔNG CÓ** cơ chế `try...except` và **KHÔNG CÓ** timeout.
  - *Hậu quả:* Nếu LLM thực sự bị chậm hoặc bị lỗi (500, 429), exception sẽ bị ném thẳng lên tầng gRPC. Điều này sẽ làm toàn bộ request bị "chết", không có fallback nào được kích hoạt. Từ góc độ AIOps, điều này rất nguy hiểm vì tính năng AI (best-effort) có thể làm sập luồng hiển thị chính của trang sản phẩm.

## 5. Cấu trúc Database & Mẫu kết nối (Connection Patterns)

- **Thư viện kết nối:** Dùng `psycopg2` để kết nối đến PostgreSQL qua biến môi trường `DB_CONNECTION_STRING`.
- **Mẫu kết nối (Pattern):** Đang sử dụng kết nối đơn lẻ (mở - truy vấn - đóng) cho **mỗi một request** (tạo mới `psycopg2.connect` liên tục). 
  - *Đánh giá rủi ro AIOps:* Không sử dụng Connection Pool (như `psycopg2.pool`). Khi có lượng truy cập đột biến (spike load), việc khởi tạo kết nối liên tục sẽ làm cạn kiệt tài nguyên của Database rất nhanh (liên quan trực tiếp tới sự cố INC-1 trong lịch sử).
- **Cấu trúc bảng (Schema):**
  - Truy vấn từ bảng `reviews.productreviews`.
  - Các cột lấy ra: `username`, `description`, `score`, và truy vấn lọc qua `product_id`.

---
**Tóm tắt hành động cho AIOps:**
1. Cần thêm biểu đồ giám sát LLM Latency và Error Rate (chưa có trong `metrics.py`).
2. Giám sát lượng connection mở tới PostgreSQL (nguy cơ sập do thiếu connection pool).
3. Đề xuất team Dev bổ sung ngay khối `try...except` và `timeout` cho nhánh gọi LLM thực tế, tránh để lỗi gRPC làm vỡ UI.
4. Cảnh báo rò rỉ dữ liệu cá nhân (PII) trên hệ thống Log và Trace OpenTelemetry.


