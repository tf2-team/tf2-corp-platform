# Mandate 25 — Bedrock flow audit for Product Review and Shopping Copilot

**Ngày rà soát:** 30/07/2026  
**Nguồn yêu cầu:** [`Mandate25.md`](./Mandate25.md)  
**Phạm vi:** luồng Bedrock của Product Review AI Assistant và Shopping Copilot, các thay đổi hiện có trong working tree, test live và hồ sơ DoD.

## 1. Kết luận

### Kết luận kỹ thuật

Hai bề mặt đã có đủ cơ chế runtime cho 5 yêu cầu kỹ thuật của Mandate 25:

1. lỗi Bedrock đi vào response `FALLBACK` có kiểm soát thay vì để lộ lỗi provider;
2. timeout, số lần retry, backoff và deadline đều có trần;
3. circuit breaker có trạng thái `CLOSED → OPEN → HALF_OPEN → CLOSED`;
4. fallback xóa dữ liệu model/tool dang dở và không dựng nội dung thay thế;
5. structured output và Bedrock tool call được validate trước khi sử dụng hoặc dispatch tool.

Product Review và Shopping Copilot cùng dùng adapter Bedrock chung tại
`src/ai-common/techx_ai_common/bedrock.py`. Product Review validate
`GroundedDraft`; Shopping Copilot còn validate toàn bộ message/tool-call batch
trước khi chạy bất kỳ tool nào.

### Kết luận Definition of Done

**Chưa thể tuyên bố Mandate 25 hoàn thành.**

Runtime code đã đáp ứng thiết kế, và một file test live đã mô tả đủ các scenario
bắt buộc trên bề mặt Shopping Copilot. Tuy nhiên, các artifact sau vẫn thiếu:

- chưa có kết quả chạy live, log, ảnh, metrics và file evidence từ môi trường có
  Docker + AWS Bedrock;
- `JIRA_MANDATE_25.md` vẫn là draft có nhiều placeholder `<...>`;
- chưa có ADR riêng cho Mandate 25 ở trạng thái `Accepted` và được ký tên;
- chưa có PR/commit link và số đo thật được điền vào Jira.

ADR hiện có `ADR-AIE-06-ai-trust-safety.md` thuộc Mandate 06. Header của tài liệu
vẫn ghi `Proposed, pending mentor sign-off`, nên không thay thế rõ ràng cho signed
ADR của Mandate 25, dù cuối file có bảng sign-off.

## 2. Ma trận đối chiếu Mandate 25

| Yêu cầu | Product Review | Shopping Copilot | Evidence hiện có | Đánh giá |
|---|---|---|---|---|
| 1. Provider lỗi không 500/không treo, có fallback thấy được | Backend bắt mọi lỗi Bedrock và trả JSON `FALLBACK`; API frontend cũng chuyển lỗi gRPC thành HTTP 200 `FALLBACK` | Agent, graph, gRPC server và API frontend đều có fallback phòng thủ | Scenario 01 có trong test live nhưng chưa chạy | Code đạt; evidence chưa chốt |
| 2. Timeout + retry/backoff có trần | Deadline Bedrock 12 giây; gateway 15 giây | Deadline graph/Bedrock 15/12 giây; gateway 18 giây | Scenario 02 có trong test live nhưng chưa chạy | Code đạt; evidence chưa chốt |
| 3. Breaker mở, ngừng gọi, tự hồi phục | Dùng circuit breaker chung theo model + region | Dùng cùng breaker; lỗi ở mọi bước Bedrock đi vào fallback | Scenario 03 kiểm tra open, reject, half-open và real Bedrock recovery nhưng chưa chạy | Code đạt; evidence chưa chốt |
| 4. Degrade trung thực, không bịa | `FALLBACK` có answer cố định, `claims=[]`; chỉ cache kết quả grounded | Xóa products, claims, sources, review answer, criteria và pending cart token khi fallback | Các assert an toàn có trong scenario 01/03/04 | Code đạt |
| 5. Output hợp lệ mới được dùng | Pydantic validate JSON thành `GroundedDraft`, sau đó validate grounding theo review nguồn | Validate Bedrock envelope, content block, tool allowlist và Pydantic input trước mọi tool execution | Scenario 04 so cart trước/sau và pending token, nhưng chưa chạy | Code đạt; evidence chưa chốt |
| DoD 5. Signed ADR | Không có ADR Mandate 25 Accepted | Không có ADR Mandate 25 Accepted | ADR-AIE-06 không đúng phạm vi/trạng thái | **Chưa đạt** |

## 3. Luồng Product Review dùng Bedrock

```text
HTTP /api/product-ask-ai-assistant/:productId
  → ProductReview.gateway (gRPC deadline 15s)
  → AskProductAIAssistant
  → input guard / rate limit / cache
  → lấy review thật qua ProductReview service boundary
  → sanitize + chọn review nguồn
  → generate_grounded_summary(deadline)
  → shared Bedrock adapter
       timeout → bounded retry → breaker
       structured JSON → Pydantic GroundedDraft
  → validate_grounded_summary(review nguồn)
  → output guard
  → GROUNDED / ABSTAINED

Mọi exception trong nhánh Bedrock
  → FALLBACK cố định, không claims, không chi tiết exception
  → frontend vẫn trả HTTP 200 FALLBACK nếu gRPC hỏng
```

### Điểm đáp ứng

- `_get_bedrock_response` gọi `generate_grounded_summary` với deadline monotonic
  12 giây và usage callback.
- Shared adapter giới hạn mỗi logical Bedrock call bằng connect timeout, read
  timeout, tổng deadline và tối đa hai provider attempts.
- `converse_json` chỉ trả object sau khi
  `response_model.model_validate_json(...)` thành công.
- `validate_grounded_summary` tiếp tục đối chiếu claims với review đã sanitize;
  output không grounded không được trả như grounded.
- `_fallback_response` trả thông báo cố định:
  `AI summary is temporarily unavailable. Please try again shortly.`
- Payload fallback không chứa exception, stack trace, claim hoặc nội dung do
  model tạo ra.
- API Next.js bắt lỗi transport và trả HTTP 200 với `status=FALLBACK`,
  `claims=[]`.

### Phạm vi evidence

Test live hiện tại dùng Product Reviews thật như một dependency của Shopping
Copilot để lấy review fixture và chạy tool review khi model yêu cầu. Test chưa
gọi trực tiếp RPC `AskProductAIAssistant`, vì vậy chưa chứng minh độc lập toàn bộ
luồng Product Review AI Assistant dưới fault injection.

## 4. Luồng Shopping Copilot dùng Bedrock

```text
HTTP /api/copilot
  → ShoppingCopilot.gateway (gRPC deadline 18s)
  → ShoppingCopilot.Search
  → graph deadline 15s
  → input guard / cache / conversation
  → retrieval_hint (structured Bedrock output)
  → ReAct Bedrock round
       validate toàn bộ assistant batch
       → tool allowlist
       → Pydantic input schema
       → chỉ sau đó mới dispatch Catalog / Review / prepare-cart
  → grounded response + output guard
  → gRPC response

Bedrock unavailable / deadline / breaker open / invalid output
  → revoke pending cart token
  → xóa products, reviews, claims, sources, criteria
  → FALLBACK trung thực
```

### Các Bedrock workflow step

| Workflow step | Output boundary | Cách xử lý lỗi |
|---|---|---|
| `retrieval_hint` | `RetrievalHint` qua Pydantic JSON validation | Dừng graph và trả fallback |
| `react_round` | Bedrock assistant envelope + từng content block + tool input model | Reject toàn batch trước tool execution; trả fallback |
| `grounded_review_answer` | `GroundedDraft`, sau đó grounding validation | Không dùng câu trả lời sai schema/sai nguồn |
| `memory_extraction` | `MemoryExtraction` | Bỏ qua memory write khi hết budget hoặc lỗi |

### Biên an toàn tool-call

`_validate_bedrock_message` thực hiện validation trước khi thêm message vào state
hoặc gọi tool:

1. assistant phải là object và có `content` không rỗng;
2. mỗi content block phải có đúng một dạng `text` hoặc `toolUse`;
3. tool phải đang được phép và nằm trong allowlist;
4. `toolUseId`, `name` và `input` phải đúng kiểu;
5. input phải qua Pydantic model tương ứng;
6. toàn bộ batch phải hợp lệ trước khi tool đầu tiên chạy;
7. call trùng trong cùng batch hoặc giữa các round bị từ chối;
8. tool input được validate lại tại `_run_tool_impl`.

Fixture malformed dùng `prepare_cart_action` với `quantity=0` và thiếu product
reference. Input này bị schema chặn, không tạo pending action và không gọi
`CartService.AddItem`.

Cart write thật chỉ xảy ra ở RPC xác nhận riêng `ConfirmCartAction`. Model chỉ có
thể chuẩn bị token; mọi token dang dở bị revoke khi luồng chuyển sang fallback.

## 5. Cơ chế chung của Bedrock adapter

File trung tâm `src/ai-common/techx_ai_common/bedrock.py` không có diff trong
working tree hiện tại, nhưng là nền tảng mà cả hai bề mặt đang gọi.

### Cấu hình mặc định

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `BEDROCK_CONNECT_TIMEOUT_SECONDS` | 2 giây | Timeout kết nối mỗi attempt |
| `BEDROCK_READ_TIMEOUT_SECONDS` | 8 giây | Timeout đọc mỗi attempt |
| `BEDROCK_MAX_ATTEMPTS` | 2 | Số provider attempts tối đa cho một logical call |
| `BEDROCK_BACKOFF_BASE_SECONDS` | 0.25 giây | Backoff gốc |
| `BEDROCK_BACKOFF_MAX_SECONDS` | 1 giây | Trần backoff |
| `BEDROCK_SCHEMA_MAX_ATTEMPTS` | 2 | Số lần structured generation tối đa |
| `BEDROCK_TOTAL_DEADLINE_SECONDS` | 12 giây | Deadline tổng của logical call |
| `BEDROCK_BREAKER_FAILURE_THRESHOLD` | 3 | Logical failures để mở breaker |
| `BEDROCK_BREAKER_RECOVERY_SECONDS` | 30 giây | Thời gian trước half-open probe |

Botocore được cấu hình `total_max_attempts=1`; retry do adapter quản lý để không
nhân retry ở hai tầng. Backoff là exponential, capped và có jitter trong khoảng
50–100% của giá trị đã cap.

Các lỗi retryable gồm connect/read/network timeout, throttling/429 và các lỗi
Bedrock 5xx/transient được chọn. Lỗi không retryable không bị lặp vô hạn.

### Circuit breaker

- scope: process-local, key theo `BEDROCK_MODEL_ID:AWS_REGION`;
- `CLOSED`: cho gọi provider và đếm logical failure;
- đủ failure threshold: chuyển `OPEN`;
- `OPEN`: từ chối trước khi gọi provider;
- hết recovery interval: cho một probe `HALF_OPEN`;
- probe thành công: về `CLOSED`, reset failure count;
- probe thất bại: mở lại breaker.

### Fault injection từ ngoài process

Fault plan được truyền qua environment khi recreate container, không monkeypatch
Python và không thay service bằng mock.

| Outcome | Hiệu ứng |
|---|---|
| `timeout` | Ném lỗi timeout retryable |
| `throttle` | Ném throttling/429 giả lập |
| `server_error` | Ném provider 5xx giả lập |
| `malformed_json` | Trả structured text không parse được |
| `malformed_tool_call` | Trả Bedrock tool call có input sai schema |
| `pass` | Gọi Amazon Bedrock thật |

Fault injection chỉ được bật khi `LLM_PROVIDER=bedrock` và phải chỉ rõ workflow
step cùng sequence. Cách này phù hợp yêu cầu “ép lỗi từ ngoài” bằng flag/inject.

### Telemetry có sẵn

- `bedrock_provider_calls_total`;
- `bedrock_provider_failures_total`;
- `bedrock_retries_total`;
- `bedrock_breaker_state_transitions_total`;
- `bedrock_circuit_open_rejections_total`;
- `bedrock_schema_validation_failures_total`;
- `bedrock_deadline_exceeded_total`;
- `bedrock_request_duration_seconds`;
- `bedrock_fault_injections_total`;
- fallback counters riêng ở Product Review và Shopping Copilot.

Log có event retry scheduled, breaker opened/half-open/recovered/rejected,
schema rejected và fault injected. Nội dung public response không chứa raw
exception hoặc provider detail.

## 6. Test live trong một file Python

File:
`src/product-reviews/tests/test_mandate25_bedrock_mock.py`

Tên file còn chữ `mock`, nhưng implementation hiện tại không dùng mock. Test
recreate `shopping-copilot`, gọi các gRPC service thật và gọi Bedrock thật ở các
bước có outcome `pass`.

| Test | Fault | Kiểm tra |
|---|---|---|
| `test_01_provider_failure_falls_back` | `server_error,server_error` tại `retrieval_hint` | Hai attempts cạn; response `FALLBACK`; không products/claims/sources/pending token; latency dưới 5 giây |
| `test_02_retry_is_bounded_and_recovers` | `timeout,pass` | Retry đúng một lần rồi gọi Bedrock thật; response không fallback; tổng thời gian dưới RPC deadline |
| `test_03_sustained_failure_opens_breaker_then_recovers` | Bốn timeout rồi `pass` | Hai logical calls làm breaker mở; request kế tiếp bị reject trước provider; sau recovery interval, half-open probe dùng Bedrock thật và đóng breaker |
| `test_04_malformed_tool_call_never_executes` | malformed tool call rồi `pass` | Response fallback; cart thật trước/sau không đổi; không pending token; request sau dùng Bedrock thật |

Test dùng Product Catalog, Product Reviews, Cart, Valkey, OpenTelemetry Collector,
Shopping Copilot và Amazon Bedrock. Sau mỗi scenario, test recreate Copilot với
fault injection tắt để trả môi trường về trạng thái healthy.

### Cách chạy

Chạy từng scenario:

```powershell
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_01_provider_failure_falls_back
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_02_retry_is_bounded_and_recovers
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_03_sustained_failure_opens_breaker_then_recovers
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_04_malformed_tool_call_never_executes
```

Ghi evidence JSON:

```powershell
$env:MANDATE25_EVIDENCE_FILE = "artifacts/mandate25-evidence.json"
python src/product-reviews/tests/test_mandate25_bedrock_mock.py
```

Điều kiện trước khi chạy:

- Compose stack thật đã chạy;
- AWS profile/region/model hợp lệ trong `.env.override`;
- image Shopping Copilot chứa source mới; đặt
  `MANDATE25_REBUILD_IMAGE=true` nếu cần rebuild;
- máy chạy có Python dependencies của Shopping Copilot.

## 7. Chi tiết các file đã sửa

Danh sách dưới đây chỉ gồm các thay đổi liên quan trực tiếp đến Mandate 25 trong
working tree tại thời điểm rà soát.

### Cấu hình và code dùng chung

| File | Chức năng đã sửa |
|---|---|
| `docker-compose.yml` | Truyền timeout, retry, backoff, schema attempts, deadline, breaker và fault-injection config cho Product Reviews và Shopping Copilot |
| `docker-compose.minimal.yml` | Bổ sung cấu hình Bedrock/AWS, credential mount và tắt botocore auto-instrumentation cho Product Reviews |
| `src/ai-common/techx_ai_common/grounding.py` | Cho phép truyền deadline vào structured grounded-summary call |

### Product Review

| File | Chức năng đã sửa |
|---|---|
| `src/product-reviews/product_reviews_server.py` | Dùng shared grounded-summary path có deadline; ghi token usage; chuẩn hóa thông báo fallback |
| `src/frontend/gateways/rpc/ProductReview.gateway.ts` | Thêm gRPC deadline 15 giây |
| `src/frontend/pages/api/product-ask-ai-assistant/[productId]/index.ts` | Bắt lỗi gateway và trả HTTP 200 `FALLBACK` có `claims=[]` |

### Shopping Copilot

| File | Chức năng đã sửa |
|---|---|
| `src/shopping-copilot/bedrock_runtime.py` | Thêm wrapper `converse_raw`, export các reliability exception, truyền deadline và ghi usage |
| `src/shopping-copilot/bedrock_grounding.py` | Truyền deadline cho grounded review generation |
| `src/shopping-copilot/memory_retrieval.py` | Truyền deadline cho `retrieval_hint` |
| `src/shopping-copilot/memory_extractor.py` | Truyền deadline cho memory extraction |
| `src/shopping-copilot/review_tool.py` | Truyền deadline xuyên qua review Q&A Bedrock path |
| `src/shopping-copilot/react_agent.py` | Bỏ gọi boto3 trực tiếp; dùng shared adapter; validate toàn batch/tool input trước dispatch; chặn duplicate; scrub state và revoke pending action khi fallback |
| `src/shopping-copilot/copilot_graph.py` | Tạo graph deadline; chuyển lỗi Bedrock/invalid output thành degraded state; xóa partial results; giới hạn memory extraction theo budget |
| `src/shopping-copilot/copilot_server.py` | Scrub lần cuối mọi partial model/tool state khi status là `FALLBACK` |
| `src/shopping-copilot/cart_tool.py` | Thêm `discard_pending_token` để revoke action đã chuẩn bị |
| `src/shopping-copilot/catalog_tool.py` | Thêm future annotations; không có thay đổi resilience chức năng |
| `src/frontend/gateways/rpc/ShoppingCopilot.gateway.ts` | Thêm gRPC deadline 18 giây |

### Test

| File | Chức năng đã sửa |
|---|---|
| `src/product-reviews/tests/test_mandate25_bedrock_mock.py` | Thay test mock bằng bốn scenario độc lập, chạy Compose services thật, fault injection qua env và Bedrock thật |

### Artifact liên quan đang có trong working tree

| File | Trạng thái |
|---|---|
| `docs/ai-engineering/Mandate25.md` | Source directive; hiện là file untracked |
| `docs/ai-engineering/JIRA_MANDATE_25.md` | Draft evidence scaffold; còn placeholder và link source sai tên file |
| `docs/ai-engineering/MANDATE_25_BEDROCK_FLOW_AUDIT.md` | Báo cáo rà soát này |

Các thay đổi `.gitignore`, submodule `third-party/mem0` và
`src/shopping-copilot/SHOPPING_COPILOT_ANALYSIS.md` không được tính vào thay đổi
Mandate 25 trong báo cáo này.

## 8. File liên quan quan trọng nhưng không có diff

| File | Vai trò |
|---|---|
| `src/ai-common/techx_ai_common/bedrock.py` | Adapter timeout/retry/breaker/fault injection/schema validation dùng chung |
| `src/ai-common/techx_ai_common/contracts.py` | Pydantic contracts cho grounded và structured output |
| `src/ai-common/techx_ai_common/guardrails.py` | Input/output safety guard |
| `src/ai-common/techx_ai_common/observability.py` | Model/tool/fallback telemetry boundary |
| `src/frontend/pages/api/copilot/index.ts` | Đã có HTTP 200 fallback khi Copilot gateway lỗi |
| `src/shopping-copilot/copilot_contracts.py` | Tool input schemas và Copilot statuses |
| `src/shopping-copilot/metrics.py` | Copilot request/model/tool/cache metrics |

## 9. Khoảng trống và rủi ro còn lại

### Blocker đối với DoD

1. **Chưa có signed ADR Mandate 25.** Cần ADR riêng hoặc cập nhật một ADR đúng
   phạm vi, trạng thái `Accepted`, có owner, reviewer và ngày ký.
2. **Chưa có live evidence.** Test đã sẵn sàng nhưng chưa có JSON/log/ảnh/metrics
   chứng minh kết quả thật.
3. **Jira scaffold chưa hoàn thiện.** `JIRA_MANDATE_25.md` còn placeholder và link
   source đang trỏ tới file không tồn tại
   `MANDATE-25-ai-resilience-fallback.md` thay vì `Mandate25.md`.
4. **Chưa có PR/commit/repro artifact đã điền.**

### Rủi ro kỹ thuật cần biết

1. **Breaker là process-local.** Mỗi replica tự học trạng thái outage; một replica
   mở breaker không làm replica khác dừng gọi provider.
2. **Breaker dùng chung theo model + region, không theo workflow step.** Một call
   thành công ở step khác reset failure streak. Outage toàn provider vẫn được
   chặn, nhưng lỗi chỉ xảy ra ở một step muộn có thể bị success ở step sớm che
   mất.
3. **Graph không còn hard `asyncio.wait_for`.** Bedrock calls có logical deadline
   và frontend gateway có deadline, nhưng Catalog và Product Review gRPC calls
   bên trong Copilot chưa truyền per-call timeout. Nếu dependency nội bộ treo,
   client hết hạn sau 18 giây nhưng worker có thể tiếp tục chạy.
4. **Product Review gateway có backward-compatibility parser.** Nếu JSON từ
   backend không parse được, gateway đang gắn raw response thành `GROUNDED`.
   Nên đổi nhánh này thành controlled `FALLBACK` để biên backend/frontend fail
   closed.
5. **Tên test còn chữ `mock`.** Không ảnh hưởng hành vi nhưng dễ làm reviewer hiểu
   nhầm test không dùng service/Bedrock thật.
6. **Live scenarios chỉ chấm trực tiếp một bề mặt.** Đây là sàn hợp lệ theo
   Mandate, nhưng chưa đạt mức evidence cao hơn cho cả Product Review và Copilot.

## 10. Kiểm tra đã thực hiện trong lần rà soát

| Kiểm tra | Kết quả |
|---|---|
| Parse AST các Python file thay đổi liên quan | PASS — 13 file |
| Discover file test Mandate 25 | PASS — tìm thấy 4 scenario |
| Chạy test mặc định không bật live | PASS — 4 test được skip đúng chủ đích |
| `git diff --check` | PASS — không có whitespace error |
| Docker Compose + AWS Bedrock live | **Chưa chạy trong audit này** |

Không được suy diễn bốn test bị skip là test pass. Chỉ đánh dấu scenario `PASS`
trong Jira sau khi chạy live và lưu artifact.

## 11. Việc cần làm để đóng Mandate 25

1. Chạy lần lượt bốn scenario live và lưu
   `MANDATE25_EVIDENCE_FILE`.
2. Lưu log các event retry, breaker open/reject/half-open/recovered, schema
   reject và fallback.
3. Chụp response + cart before/after của malformed tool-call case.
4. Điền số attempt, latency, request-preservation rate và provider-call count vào
   `JIRA_MANDATE_25.md`; thay toàn bộ placeholder.
5. Sửa link source trong Jira scaffold thành `./Mandate25.md`.
6. Tạo và ký ADR resilience cho cả hai bề mặt, đặt status `Accepted`.
7. Gắn PR/commit, repro command, evidence JSON, log/ảnh và ADR vào một Jira ticket
   `AI MANDATE #25`.

Sau khi hoàn tất các bước trên và tất cả scenario live pass, Mandate 25 có thể
được đánh dấu hoàn thành. Hiện trạng phù hợp nhất là:
**implementation ready, live evidence and governance pending**.
