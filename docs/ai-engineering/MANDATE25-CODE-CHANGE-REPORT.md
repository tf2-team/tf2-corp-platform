# MANDATE25 — Báo cáo thay đổi code

## 1. Bedrock adapter dùng chung

| File | Hàm/thành phần | Vì sao sửa | Task phục vụ | Kết quả |
|---|---|---|---|---|
| `src/ai-common/techx_ai_common/bedrock.py` | `_load_config`, `reload_config` | Đọc và kiểm tra timeout, retry, backoff, schema retry, breaker, deadline. | 1, 2, 3 | Cấu hình sai fail-fast; mọi request có giới hạn thời gian. |
|  | `_CircuitBreaker.before_call`, `on_success`, `on_failure` | Ngăn gọi provider khi lỗi kéo dài và cho probe phục hồi. | 3 | `CLOSED → OPEN → HALF_OPEN → CLOSED`; failure threshold và recovery có cấu hình. |
|  | `_invoke_once` | Tạo một lần gọi boto3 với connect/read timeout; hỗ trợ fault mode để replay. | 1, 2 | Không có retry ẩn thứ hai trong boto3; fault mode gồm timeout, throttling, 5xx, malformed JSON, schema mismatch. |
|  | `_backoff_seconds` | Thêm exponential backoff có jitter và trần. | 2 | Backoff không vượt `BEDROCK_BACKOFF_MAX_SECONDS`. |
|  | `converse_text` | Sở hữu vòng retry provider duy nhất và deadline chung. | 1, 2, 3 | Retry lỗi tạm thời có giới hạn; hết retry trả exception ổn định; breaker ghi nhận logical failure. |
|  | `converse_json` | Validate output bằng `model_validate_json`; chỉ retry lỗi schema. | 4, 5 | JSON sai hoặc sai schema bị chặn; không trả blob lỗi cho business logic. |

Các exception public được dùng ở biên: `BedrockUnavailableError`, `CircuitBreakerOpenError`, `InvalidModelOutputError`, `BedrockDeadlineExceededError`.

## 2. Product Reviews — Bedrock

| File | Hàm/thành phần | Vì sao sửa | Task | Kết quả |
|---|---|---|---|---|
| `src/product-reviews/product_reviews_server.py` | `get_product_reviews` | Lấy dữ liệu theo `request_product_id` trước khi gọi model. | 5 | Model không tự chọn product hoặc tool. |
|  | `_get_bedrock_response` | Đưa review đã sanitize vào `converse_json(GroundedDraft)` rồi validate grounding. | 4, 5 | Chỉ dùng draft hợp lệ và có source evidence. |
|  | `_fallback_response` | Chuẩn hóa phản hồi khi provider, schema hoặc deadline lỗi. | 1, 4 | Trả `FALLBACK`, không crash, không trả raw exception/malformed blob. |
|  | `get_ai_assistant_response` | Chọn Bedrock path và bắt lỗi reliability ở handler. | 1, 4 | Provider lỗi chuyển sang degrade an toàn. |
| `src/ai-common/techx_ai_common/grounding.py` | `generate_grounded_summary`, `validate_grounded_summary` | Tách nội dung model khỏi bằng chứng review. | 4, 5 | Thiếu evidence trả `ABSTAINED`; claim không có source bị loại. |
| `src/product-reviews/tests/test_mandate25_bedrock_mock.py` | deadline, breaker recovery, malformed JSON tests | Kiểm tra adapter không gọi AWS thật. | 2, 3, 5 | `3 passed`. |

Giới hạn của luồng này:

- Nhánh OpenAI cũ vẫn có model-generated tool-call; kết luận “không chạy args rác” chỉ đúng cho Bedrock path.
- Product Reviews còn ghi sanitized question vào span/log; cần bỏ content để đáp ứng đầy đủ yêu cầu không log prompt.
- Chưa có bộ test đầy đủ cho fallback handler, 429/5xx, access denied và concurrent half-open.

## 3. Shopping Copilot

| File | Hàm/thành phần | Vì sao sửa | Task | Kết quả |
|---|---|---|---|---|
| `src/shopping-copilot/bedrock_runtime.py` | re-export exception và `get_breaker_state` | Dùng shared adapter, tránh retry/breaker thứ hai trong Copilot. | 2, 3 | Một nơi duy nhất quản lý retry và breaker. |
| `src/shopping-copilot/intent_parser.py` | `parse_intent` | Parse intent qua `converse_json(ShoppingIntent)`. | 5 | Output model bị validate trước catalog. |
| `src/shopping-copilot/copilot_contracts.py` | `ShoppingIntent`, `PendingCartAction`, `CopilotContractModel` | Khóa field thừa, category, boolean và quantity dùng cho side effect. | 4, 5 | Sai schema/category/field thừa bị reject. |
| `src/shopping-copilot/copilot_graph.py` | `_ExecutionGuard`, `stop_if_expired`, các node intent/catalog/review/cart, `run_graph_with_timeout` | Chặn downstream work sau timeout; biến lỗi model thành fallback ổn định. | 1, 2, 4, 5 | Fallback không tạo product, review answer hoặc pending action; guard ngăn tool sau deadline caller. |
| `src/shopping-copilot/cart_tool.py` | `create_pending_token`, `confirm_cart_action` | Validate payload Valkey trước `AddItem`. | 5 | JSON sai, user sai, product ID rỗng, quantity sai hoặc field thừa không được ghi cart. |
| `src/shopping-copilot/tests/test_bedrock_runtime.py` | fault mode, breaker sustained failure/recovery | Replay lỗi provider và kiểm tra breaker. | 2, 3 | Có bằng chứng bounded retry và auto-recovery. |
| `src/shopping-copilot/tests/test_copilot_graph.py` | malformed output, timeout downstream blocking | Chứng minh lỗi không chạy catalog/review/cart. | 1, 4, 5 | Downstream side effect bị chặn. |
| `src/shopping-copilot/tests/test_intent_parser.py` | strict type/category/extra-field tests | Kiểm tra schema ở biên. | 5 | Intent không hợp lệ bị từ chối. |
| `src/shopping-copilot/tests/test_cart_tool.py` | malformed pending payload tests | Kiểm tra payload trước `AddItem`. | 5 | Payload hỏng không gây crash hoặc side effect. |
| `src/shopping-copilot/tests/test_catalog_tool.py` | cập nhật fixture category | Đồng bộ fixture với allowlist mới. | 5 | Test dùng contract hợp lệ. |

Fallback cố định:

```text
Shopping assistance is temporarily unavailable. Please try again shortly.
```

## 4. Cấu hình triển khai

| File | Thay đổi | Mục đích |
|---|---|---|
| `.env` | Khai báo 9 biến Bedrock reliability, `BEDROCK_FAULT_MODE`, `COPILOT_GRAPH_TIMEOUT_SECONDS`. | Có giá trị mặc định rõ ràng khi chạy local. |
| `docker-compose.yml` | Truyền các biến trên vào Product Reviews và Shopping Copilot. | Container dùng đúng cấu hình runtime. |
| `.env.override` | Đang có thay đổi local ngoài commit; không coi là bằng chứng triển khai. | Cần kiểm tra riêng trước khi commit/deploy. |

Giá trị hiện tại đáng chú ý:

```text
BEDROCK_MAX_ATTEMPTS=3
BEDROCK_SCHEMA_MAX_ATTEMPTS=2
BEDROCK_BREAKER_FAILURE_THRESHOLD=3
BEDROCK_BREAKER_RECOVERY_SECONDS=30
COPILOT_GRAPH_TIMEOUT_SECONDS=15
BEDROCK_TOTAL_DEADLINE_SECONDS=98
```

`30` giây là thời gian breaker ở trạng thái `OPEN` trước khi cho một probe `HALF_OPEN`.

## 5. Đánh giá theo MANDATE25

| Yêu cầu | Product Reviews/Bedrock | Shopping Copilot |
|---|---|---|
| 1. Có đường lui khi model lỗi | Đạt trong code; coverage fallback handler còn thiếu. | Đạt code + test; trả `FALLBACK`. |
| 2. Retry giới hạn, backoff có trần | Đạt shared adapter. | Đạt; không có retry thứ hai. |
| 3. Circuit-breaker và tự phục hồi | Đạt code + test recovery. | Đạt code + test sustained failure/recovery. |
| 4. Degrade an toàn, trung thực | Đạt `FALLBACK`/`ABSTAINED`; còn log content cần dọn. | Đạt; không tạo downstream result/pending action khi lỗi. |
| 5. Output hợp lệ mới được dùng | Đạt Bedrock `GroundedDraft`; OpenAI tool-call là phạm vi khác. | Đạt intent và pending-cart validation + test. |
