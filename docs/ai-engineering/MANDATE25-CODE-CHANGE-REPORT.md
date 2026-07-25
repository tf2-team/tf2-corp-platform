# BÁO CÁO THAY ĐỔI CODE — AI MANDATE #25

## 1. Thông tin chung

- **Mandate:** MANDATE #25 — Model lỗi hoặc trả output không hợp lệ, tầng AI vẫn phải hoạt động theo chế độ suy giảm có kiểm soát.
- **Bề mặt triển khai:** Product Reviews sử dụng Amazon Bedrock.
- **Commit triển khai:** `f66674cdb33969198be4646be6e6a2c18cdb3d56`
- **Phạm vi báo cáo:** Các thay đổi trong code hiện có, lý do thay đổi, kết quả đạt được và phần còn thiếu so với Definition of Done.

## 2. Lý do phải chỉnh sửa

Product Reviews phụ thuộc vào Amazon Bedrock, một dịch vụ bên ngoài có thể timeout, bị throttling, trả HTTP 5xx hoặc trả JSON sai cấu trúc. Trước thay đổi này, lỗi từ provider có thể làm request thất bại, kéo dài thời gian chờ hoặc đưa output chưa được kiểm tra vào luồng xử lý.

MANDATE #25 yêu cầu hệ thống:

1. Không trả lỗi ứng dụng hoặc treo vô hạn khi model provider gặp sự cố.
2. Giới hạn số lần retry và thời gian backoff.
3. Ngừng gọi provider khi sự cố kéo dài và tự phục hồi khi provider khỏe lại.
4. Trả trạng thái suy giảm trung thực, không tự bịa nội dung thay thế.
5. Chỉ sử dụng output có cấu trúc sau khi schema validation và grounding thành công.

Vì vậy, code cần một lớp reliability dùng chung cho Bedrock và một đường fallback an toàn trong Product Reviews.

## 3. Các file đã chỉnh sửa

| File | Thay đổi chính |
|---|---|
| `src/ai-common/techx_ai_common/bedrock.py` | Thêm timeout, retry có giới hạn, capped exponential backoff, request deadline, circuit breaker, schema validation, exception công khai, log và metrics. |
| `src/product-reviews/product_reviews_server.py` | Tích hợp luồng Bedrock an toàn, lấy review bằng ID từ request, trả `ABSTAINED` khi thiếu bằng chứng và trả `FALLBACK` khi provider/output lỗi. |
| `src/product-reviews/tests/test_mandate25_bedrock_mock.py` | Thêm ba test cho deadline, circuit breaker recovery và malformed JSON. |

Commit đã thêm 632 dòng và xóa 24 dòng trong ba file trên. Public gRPC contract không thay đổi.

## 4. Chi tiết thay đổi và kết quả

### 4.1. Cấu hình timeout và fail-fast

File `bedrock.py` bổ sung cấu hình:

- `BEDROCK_CONNECT_TIMEOUT_SECONDS`, mặc định 3 giây.
- `BEDROCK_READ_TIMEOUT_SECONDS`, mặc định 12 giây.
- `BEDROCK_MAX_ATTEMPTS`, mặc định 3 lần gọi provider.
- `BEDROCK_BACKOFF_BASE_SECONDS`, mặc định 0,25 giây.
- `BEDROCK_BACKOFF_MAX_SECONDS`, mặc định 2 giây.
- `BEDROCK_SCHEMA_MAX_ATTEMPTS`, mặc định 2 lần sinh output có cấu trúc.
- `BEDROCK_BREAKER_FAILURE_THRESHOLD`, mặc định 5 logical request lỗi liên tiếp.
- `BEDROCK_BREAKER_RECOVERY_SECONDS`, mặc định 30 giây.
- `BEDROCK_TOTAL_DEADLINE_SECONDS`, giới hạn tổng thời gian của provider retry và schema retry.

Code kiểm tra giá trị cấu hình ngay khi module được tải. Timeout phải lớn hơn 0; số lần thử và ngưỡng breaker phải từ 1 trở lên; backoff tối đa không được nhỏ hơn backoff cơ sở. Cấu hình sai làm service fail-fast thay vì chạy với trạng thái không xác định.

**Kết quả:** mỗi lần gọi Bedrock có connect/read timeout rõ ràng và toàn bộ logical request có deadline hữu hạn.

### 4.2. Retry có giới hạn và backoff có trần

`converse_text()` chỉ retry lỗi tạm thời như timeout, lỗi kết nối, throttling, HTTP 429 và HTTP 5xx. Các lỗi không được phân loại là tạm thời sẽ dừng ngay.

Backoff tăng theo cấp số nhân:

```text
min(BACKOFF_MAX, BACKOFF_BASE × 2^(attempt - 1))
```

Code thêm jitter để các request không retry đồng loạt. Giá trị cuối không vượt `BEDROCK_BACKOFF_MAX_SECONDS`.

Retry nội bộ của botocore được giới hạn còn một attempt. Vòng lặp của ứng dụng là nơi duy nhất quản lý retry, nhờ đó tổng số lần gọi không vượt `BEDROCK_MAX_ATTEMPTS`.

**Kết quả:** lỗi provider không tạo retry vô hạn hoặc hai lớp retry chồng lên nhau.

### 4.3. Circuit breaker cho sự cố kéo dài

Code bổ sung circuit breaker thread-safe với ba trạng thái:

- `CLOSED`: cho phép gọi provider.
- `OPEN`: chặn request trước khi gọi boto3.
- `HALF_OPEN`: sau thời gian recovery, chỉ cho một request thăm dò provider.

Mỗi logical request đã cạn retry chỉ làm tăng failure counter một lần. Khi counter đạt ngưỡng, breaker mở. Request đến trong lúc breaker mở nhận `CircuitBreakerOpenError` ngay, không gọi Bedrock.

Sau recovery interval, một request được phép thăm dò:

- Probe thành công đưa breaker về `CLOSED` và xóa failure counter.
- Probe thất bại đưa breaker về `OPEN` và bắt đầu recovery interval mới.

Breaker được lưu theo cặp model/region trong từng process và sử dụng lock để bảo vệ trạng thái.

**Kết quả:** hệ thống ngừng dội request vào provider đang sập và có cơ chế tự phục hồi khi provider hoạt động trở lại.

> Khi triển khai theo quyết định vận hành mới, có thể đặt `BEDROCK_BREAKER_FAILURE_THRESHOLD=3`. Khi đó ba logical request lỗi liên tiếp sẽ mở breaker. Nếu mỗi request có tối đa ba provider attempts, trường hợp xấu nhất có tối đa chín lần gọi provider trước khi breaker mở.

### 4.4. Public interface và exception ổn định

Adapter giữ các interface:

```python
converse_text(system_prompt, user_prompt)
converse_json(response_model, system_prompt, user_prompt)
get_breaker_state()
```

Adapter công khai các exception:

- `BedrockUnavailableError`
- `CircuitBreakerOpenError`
- `InvalidModelOutputError`
- `BedrockDeadlineExceededError`

Caller không cần phụ thuộc vào exception nội bộ của boto3 hoặc botocore.

**Kết quả:** Product Reviews và các task tiếp theo có thể phân loại lỗi bằng contract ổn định.

### 4.5. Validate output có cấu trúc tại biên

`converse_json()` nhận text từ Bedrock rồi gọi:

```python
response_model.model_validate_json(text)
```

Trong Product Reviews, `response_model` là `GroundedDraft`. JSON malformed, thiếu field hoặc sai kiểu không được trả về cho business logic. Code thử sinh lại output tối đa `BEDROCK_SCHEMA_MAX_ATTEMPTS`; nếu vẫn không hợp lệ, nó raise `InvalidModelOutputError`.

Luồng Bedrock không dùng model-generated tool call. Backend tự gọi cố định:

```python
fetch_product_reviews(product_id=request_product_id)
```

Model không chọn tool và không cung cấp `product_id`. Vì vậy, Bedrock không thể khiến backend thực thi tool bằng arguments do model bịa ra.

**Kết quả:** output sai schema bị chặn trước khi sử dụng; parse fail không làm gRPC handler crash; luồng Bedrock không thực thi tool với arguments do model tạo.

### 4.6. Grounding và abstention

Backend thực hiện tuần tự:

1. Nhận `request_product_id` từ gRPC request.
2. Lấy review bằng chính ID này.
3. Sanitize và retrieval review.
4. Nếu không còn review an toàn, trả `ABSTAINED` mà không gọi Bedrock.
5. Nếu có review, yêu cầu Bedrock sinh `GroundedDraft`.
6. Validate draft bằng Pydantic.
7. Chạy `validate_grounded_summary()`.
8. Chỉ giữ claim có source ID hợp lệ và có bằng chứng trong review.

Nếu không còn claim hợp lệ, hệ thống trả thông báo:

```text
The current reviews do not provide enough information.
```

**Kết quả:** hệ thống từ chối trả lời khi thiếu bằng chứng thay vì đoán hoặc bịa nội dung.

### 4.7. Fallback an toàn và trung thực

Timeout, lỗi provider, breaker mở, deadline hết hoặc output sai schema đều được bắt trong luồng Product Reviews. Service trả response có kiểm soát:

```json
{
  "status": "FALLBACK",
  "answer": "AI summary is temporarily unavailable.",
  "reason": "LLM or dependency error: <error class>",
  "claims": []
}
```

Response không chứa raw exception, prompt, AWS request body hoặc credential.

**Kết quả:** lỗi AI không thoát ra thành application error; người dùng biết rõ AI summary đang tạm thời không khả dụng; fallback không chế nội dung thay thế.

### 4.8. Observability

Code thêm các event:

- `bedrock_call_started`
- `bedrock_retry_scheduled`
- `bedrock_retry_exhausted`
- `bedrock_schema_rejected`
- `bedrock_breaker_opened`
- `bedrock_breaker_rejected`
- `bedrock_breaker_half_open`
- `bedrock_breaker_recovered`
- `bedrock_fallback_returned`

Code cũng thêm metrics cho provider calls, provider failures, retries, schema failures, deadline exceeded, breaker transitions, breaker rejections, request duration và fallback count.

**Kết quả:** đã có các tín hiệu cơ bản để theo dõi retry, breaker và fallback.

## 5. Test đã bổ sung

`test_mandate25_bedrock_mock.py` sử dụng fake client, không gọi AWS thật. Ba test hiện có chứng minh:

1. Deadline dừng nested retry trước khi backoff làm request kéo dài.
2. Chuỗi lỗi mở breaker; request khi breaker mở không gọi provider; successful probe đóng breaker.
3. Malformed JSON không được trả về và dẫn đến `InvalidModelOutputError`.

## 6. Đánh giá theo yêu cầu MANDATE #25

| Yêu cầu | Kết quả hiện tại |
|---|---|
| Provider lỗi không làm service 500/treo | Đạt ở luồng Product Reviews/Bedrock bằng `FALLBACK` và deadline. |
| Retry có giới hạn, backoff có trần | Đạt trong code. |
| Breaker mở khi lỗi kéo dài | Đạt trong code. |
| Breaker chặn provider và tự phục hồi | Đạt trong code; có một test tổng hợp. |
| Degrade trung thực, không bịa | Đạt bằng `FALLBACK` và `ABSTAINED`. |
| Structured output phải qua schema validation | Đạt trong luồng Bedrock. |
| Không chạy tool với args do model tạo | Đạt bằng thiết kế của luồng Bedrock: backend không dùng model-generated tool call. |
| Không đổi public gRPC contract | Đạt. |

## 7. Phần chưa hoàn tất

Implementation đã đáp ứng phần lõi của mandate trên một bề mặt, nhưng chưa đủ artifact để tuyên bố hoàn thành toàn bộ Definition of Done:

1. Chưa có `src/ai-common/tests/` và còn thiếu nhiều test riêng cho timeout, throttling, HTTP 5xx, access denied, backoff cap, concurrent half-open probe và Product Reviews fallback.
2. Test breaker hiện dùng `time.sleep()` thật thay vì fake clock/fake sleep.
3. Structured log chưa cung cấp đầy đủ service, provider, model ID, attempt, error category, breaker state và elapsed time trên mọi event.
4. Chưa có provider-latency metric và fallback-latency metric riêng.
5. Product Reviews vẫn ghi sanitized question vào span/log; việc này chưa phù hợp yêu cầu không log user prompt.
6. Chưa có replay entry ép lỗi từ bên ngoài, ảnh/log evidence, số đo thực tế, Jira ticket và ADR ký tên.
7. Chưa có bằng chứng toàn bộ test pass trong repository/container.
8. Nhánh OpenAI tool-call cũ vẫn dùng arguments do model cung cấp. Báo cáo này chỉ xác nhận thuộc tính “không chạy tool với args rác” cho luồng Bedrock không dùng tool-call.

## 8. Shopping Copilot

### 8.1. Kết quả rà soát ban đầu

Shopping Copilot đã có các nền tảng an toàn sau trước đợt chỉnh sửa này:

- Dùng shared Bedrock adapter để parse `ShoppingIntent`.
- Chỉ gọi catalog sau intent parsing.
- Chỉ dùng product ID từ catalog results cho review và pending-cart action.
- LangGraph không gọi trực tiếp `CartService.AddItem`.
- Cart chỉ được ghi qua `ConfirmCartAction` sau khi lấy pending token từ Valkey.
- Có Pydantic contract với `extra="forbid"`.

Tuy nhiên, luồng chưa đáp ứng đầy đủ MANDATE #25:

1. Boolean trong `ShoppingIntent` chưa strict; Pydantic có thể ép chuỗi hoặc số thành boolean.
2. Category là `str` tự do dù code đã khai báo allowlist.
3. Graph trả `FALLBACK` khi parse lỗi nhưng log và lưu raw exception.
4. `asyncio.wait_for()` bọc trực tiếp `graph.invoke()` đồng bộ nên không tạo deadline hữu hiệu cho blocking Bedrock call.
5. Chưa có execution guard ngăn background graph gọi tool sau khi caller đã nhận timeout.
6. Lỗi model trong review Q&A bị bỏ qua và có thể tạo response `GROUNDED` không trung thực.
7. Pending-cart payload được `json.loads()` nhưng chưa validate toàn bộ schema; `int(...)` có thể ném exception.
8. Chưa có fault mode điều khiển từ môi trường để replay timeout, throttling, server error và malformed output qua reliability path thật.
9. Chưa có test đồng thời chứng minh malformed output không gọi catalog, review, pending token và cart.

### 8.2. Các file đã sửa cho Shopping Copilot

| File | Lý do sửa | Kết quả |
|---|---|---|
| `src/ai-common/techx_ai_common/bedrock.py` | Cần fault injection đi qua đúng provider retry, breaker và schema retry thay vì ném lỗi bên ngoài adapter. | Thêm `BEDROCK_FAULT_MODE` với `none`, `timeout`, `throttling`, `server_error`, `malformed_json` và `schema_mismatch`. Provider fault vẫn bị bounded retry và được breaker ghi nhận; malformed output vẫn đi qua Pydantic validation. |
| `src/ai-common/techx_ai_common/guardrails.py` | Hai mẫu prompt injection có thể lọt qua khi optional ML scanner không có trong môi trường test. | Bổ sung deterministic keyword fallback cho `forget previous rules`, `jailbreak` và `disregard all safety guidelines`. |
| `src/shopping-copilot/bedrock_runtime.py` | Graph cần phân loại exception ổn định từ shared adapter. | Re-export các exception reliability và `get_breaker_state()`; không tạo retry hoặc breaker thứ hai. |
| `src/shopping-copilot/copilot_contracts.py` | Structured model output phải bị reject khi sai kiểu hoặc enum. | Dùng `StrictBool`, khóa category bằng `AllowedCategory`, giữ `extra="forbid"` và đặt quantity thành strict integer từ 1 đến 10. |
| `src/shopping-copilot/intent_parser.py` | Ví dụ prompt dùng category `flashlight`, không thuộc allowlist `flashlights`. | Sửa ví dụ để model sinh giá trị đúng schema. |
| `src/shopping-copilot/copilot_graph.py` | Deadline cũ không ngắt được synchronous blocking call; fallback còn lộ raw error và review-model failure bị bỏ qua. | Chạy graph trong worker thread, giới hạn thời gian chờ, thêm execution guard trước catalog/review/cart, dùng fallback reason ổn định, chỉ lưu error category và chuyển Bedrock/review schema failure thành `FALLBACK`. |
| `src/shopping-copilot/cart_tool.py` | Malformed pending payload có thể crash hoặc tạo cart request từ dữ liệu chưa validate. | Validate payload bằng `PendingCartAction` trước `AddItem`; reject JSON sai, field thừa, product ID rỗng, quantity sai kiểu hoặc vượt constraint; không trả raw cart exception. |
| `.env` | Cần công bố fault mode và graph deadline. | Thêm `BEDROCK_FAULT_MODE=none` và `COPILOT_GRAPH_TIMEOUT_SECONDS=15`. |
| `docker-compose.yml` | Container phải nhận cấu hình từ môi trường bên ngoài. | Truyền fault mode vào hai Bedrock surfaces và graph timeout vào Shopping Copilot. |
| `src/shopping-copilot/tests/test_bedrock_runtime.py` | Cần bằng chứng schema mismatch, sustained failure, breaker open và recovery. | Thêm test fault mode sai schema và test ba lỗi liên tiếp mở breaker, request kế tiếp bị chặn, healthy probe đóng breaker. |
| `src/shopping-copilot/tests/test_copilot_graph.py` | Cần chứng minh fallback và downstream tool blocking. | Thêm test malformed output không gọi catalog/review/pending/cart và test blocking model timeout không chạy tool sau timeout. |
| `src/shopping-copilot/tests/test_intent_parser.py` | Cần chứng minh strict schema. | Thêm test reject boolean sai kiểu, field thừa và category ngoài allowlist. |
| `src/shopping-copilot/tests/test_cart_tool.py` | Cần chứng minh malformed pending token không ghi cart. | Thêm test JSON hỏng, payload sai shape/type/constraint và field thừa đều bị từ chối. |
| `src/shopping-copilot/tests/test_catalog_tool.py` | Test fixture cũ dùng category ngoài allowlist. | Cập nhật fixture theo contract strict mới. |

### 8.3. Luồng sau chỉnh sửa

Luồng thành công:

```text
Input guardrail
  → Bedrock converse_json(ShoppingIntent)
  → Pydantic strict schema validation
  → catalog search
  → allowed_product_ids từ catalog
  → review Q&A hoặc pending cart token
  → response
```

Luồng provider hoặc schema lỗi:

```text
Bedrock timeout/throttling/5xx hoặc output sai schema
  → bounded retry trong shared adapter
  → breaker ghi nhận logical failure nếu provider lỗi
  → exception ổn định
  → CopilotStatus.FALLBACK
  → không gọi catalog/review/create_pending_token/AddItem
```

Luồng deadline:

```text
Synchronous graph chạy trong worker
  → caller chỉ chờ tối đa COPILOT_GRAPH_TIMEOUT_SECONDS
  → hết hạn: set execution guard + trả FALLBACK
  → blocking model có kết thúc sau đó cũng không được bắt đầu downstream tool
```

Luồng cart confirmation:

```text
ConfirmCartAction
  → atomic getdel token
  → parse JSON
  → validate PendingCartAction
  → kiểm tra đúng user
  → CartService.AddItem đúng một lần
```

### 8.4. Đáp ứng các yêu cầu của MANDATE #25

| Task trong mandate | Cách Shopping Copilot đáp ứng | Trạng thái |
|---|---|---|
| 1. Có đường lui khi model lỗi | Provider/schema/deadline error trả `CopilotStatus.FALLBACK` với thông báo “Shopping assistance is temporarily unavailable. Please try again shortly.” | Đạt trong code và unit test. |
| 2. Giới hạn thử lại | Copilot dùng shared Bedrock adapter với connect/read timeout, max attempts, capped backoff và total deadline; không tạo retry thứ hai. | Đạt trong code và unit test. |
| 3. Chặn khi sập kéo dài | Ba logical failure theo cấu hình mở breaker; request khi `OPEN` không gọi provider; healthy half-open probe đưa breaker về `CLOSED`. | Đạt trong code và unit test. |
| 4. Degrade an toàn và trung thực | Fallback không tạo product, review answer hoặc pending action; response không chứa raw provider error hoặc malformed blob. | Đạt trong code và unit test. |
| 5. Output phải hợp lệ mới được dùng | `ShoppingIntent` dùng strict Pydantic schema; malformed/sai type/field thừa/category sai bị reject trước catalog; pending-cart payload cũng được validate trước `AddItem`. | Đạt trong code và unit test. |

### 8.5. Kết quả kiểm thử

Lệnh:

```powershell
$env:PYTHONPATH='D:\Xbrain_BT\tf2-corp-platform\src\ai-common;D:\Xbrain_BT\tf2-corp-platform\src\shopping-copilot'
python -m pytest -q tests
```

Kết quả:

```text
54 passed, 1 warning
```

Warning đến từ dependency LangGraph về cấu hình serialization trong phiên bản tương lai; không phải test failure.

Shared Bedrock regression test:

```text
3 passed
```

Docker Compose validation:

```text
docker compose config --quiet
exit code 0
```

### 8.6. Phần Copilot chưa đủ artifact để đóng mandate

Các thuộc tính cốt lõi đã có code và unit test, nhưng các deliverable vận hành sau vẫn chưa hoàn thành:

1. Chưa có replay script/entry point chạy ba scenario từ bên ngoài container và xuất kết quả machine-readable.
2. Chưa có fallback latency và provider/tool call count đo từ một Docker Compose replay thực tế.
3. Chưa có `AI_MANDATE_25_EVIDENCE.md` chứa log/ảnh và repro hoàn chỉnh.
4. Chưa có ADR được hai người ký/review.
5. Chưa có Jira ticket, link PR/commit cuối và evidence từ ngày chấm.

Vì vậy, phần Shopping Copilot hiện **đạt yêu cầu kỹ thuật trong code và unit test**, nhưng **chưa hoàn thành các artifact vận hành/ký duyệt của Definition of Done**.

## 9. Kết luận

Commit `f66674c` đã xây dựng nền tảng reliability cho Amazon Bedrock và tích hợp đường suy giảm an toàn vào Product Reviews. Hệ thống hiện có timeout, bounded retry, capped backoff, circuit breaker tự phục hồi, schema validation, grounding, `ABSTAINED` và `FALLBACK`. Các thay đổi này giảm nguy cơ request treo, retry storm, application error và sử dụng output không đáng tin.

Tuy nhiên, trạng thái hiện tại nên được ghi nhận là **đã hoàn thành phần implementation lõi, chưa hoàn thành toàn bộ MANDATE #25**. Đội cần bổ sung cấu hình triển khai, test bắt buộc, observability còn thiếu, replay/evidence và ADR trước khi đóng mandate.
