# Mandate #25 — AI Resilience and Controlled Degradation Report

> **Trạng thái:** Phần triển khai đã có; bằng chứng live và phê duyệt governance vẫn đang chờ.
>
> **Chỉ thị nguồn:** [Mandate25.md](./Mandate25.md)
>
> `IMPLEMENTED — LIVE TODO` nghĩa là hành vi đã tồn tại trong code, nhưng
> chưa có artifact replay live chứng minh Definition of Done. Không được xem
> trạng thái này là `PASS`.

## Executive Summary

Product Review và Shopping Copilot đều gọi Amazon Bedrock thông qua adapter
dùng chung `techx_ai_common.bedrock`. Adapter này giới hạn số lần thử với
provider, giới hạn backoff có jitter, áp dụng deadline logic tổng, sử dụng
circuit breaker trong phạm vi process, kiểm tra nghiêm ngặt output có cấu trúc
và hỗ trợ fault injection được cấu hình từ bên ngoài.

Cả hai bề mặt đều trả về response `FALLBACK` rõ ràng khi Bedrock không khả dụng
hoặc trả output không thể sử dụng. Product Review không trả claims. Shopping
Copilot còn xóa products, claims, sources, tiêu chí đã diễn giải và thao tác
giỏ hàng đang chờ trước khi trả response suy giảm.

Code hiện bao phủ cả hai bề mặt, nhưng live replay suite mới kiểm tra trực tiếp
Shopping Copilot. Bốn kịch bản live đang bị skip mặc định và chưa tạo artifact
bằng chứng trong working tree. ADR đã ký, liên kết Jira/PR, số liệu đo được và
owner sign-off cũng vẫn còn thiếu.

### Completion Snapshot

| DoD | Kết quả hiện tại | Bằng chứng chính |
|---|---|---|
| Một provider failure không trả 500 hoặc treo request | `IMPLEMENTED — LIVE TODO` | `test_01_provider_failure_falls_back`; artifact live đang chờ |
| Timeout và retry backoff nằm trong giới hạn | `IMPLEMENTED — LIVE TODO` | Shared Bedrock adapter và cấu hình Compose; timeline live đang chờ |
| Breaker mở khi lỗi kéo dài và tự phục hồi | `IMPLEMENTED — LIVE TODO` | `test_03_sustained_failure_opens_breaker_then_recovers`; artifact live đang chờ |
| Output model không hợp lệ bị chặn trước khi chạy tool | `IMPLEMENTED — LIVE TODO` | Kiểm tra toàn batch ReAct và `test_04_malformed_tool_call_never_executes`; artifact live đang chờ |
| ADR được chấp nhận và ký | `TODO — user fill` | ADR ID, reviewer và sign-off đang chờ |

Mandate #25 chưa hoàn tất khi còn bất kỳ dòng nào ở trạng thái `LIVE TODO`
hoặc `TODO`.

---

## Scope

### Surfaces

| Bề mặt | Trong phạm vi | Provider và model | Ranh giới output có cấu trúc | Fallback có kiểm soát |
|---|---|---|---|---|
| Shopping Copilot | Có | Amazon Bedrock; `BEDROCK_MODEL_ID`, mặc định `us.amazon.nova-2-lite-v1:0` | `RetrievalHint`, `MemoryExtraction`, `GroundedDraft` và ReAct tool calls | `FALLBACK`; xóa state dở dang, thu hồi action đang chờ, tắt điều kiện dùng cache |
| Product Review | Có | Amazon Bedrock; cùng model có thể cấu hình | `GroundedDraft`, sau đó kiểm tra grounded claim | `FALLBACK`; thông báo trung thực và `claims=[]`; frontend API chuyển gateway failure thành HTTP 200 fallback |

Phạm vi triển khai bao phủ cả hai bề mặt. Entry point của live replay hiện chỉ
chứng minh hành vi Shopping Copilot; bằng chứng live tương đương cho Product
Review vẫn đang chờ.

### Failure Modes

| Failure mode | Cơ chế inject | Hành vi đã triển khai | Hành vi người dùng nhìn thấy |
|---|---|---|---|
| Provider timeout | `BEDROCK_FAULT_SEQUENCE=timeout` | Retry trong giới hạn attempt và deadline, sau đó fallback | Response `FALLBACK` trung thực |
| Provider rate limit | `BEDROCK_FAULT_SEQUENCE=throttle` | Xem 429/throttling là lỗi có thể retry, sau đó fallback và ghi nhận vào breaker | Response `FALLBACK` trung thực |
| Provider 5xx | `BEDROCK_FAULT_SEQUENCE=server_error` | Xem một số lỗi 5xx là lỗi có thể retry, sau đó fallback và ghi nhận vào breaker | Response `FALLBACK` trung thực |
| JSON có cấu trúc bị lỗi | `BEDROCK_FAULT_SEQUENCE=malformed_json` | Từ chối tại ranh giới Pydantic; retry tạo schema trong giới hạn | Fallback sau khi hết số lần thử schema |
| Tool call không hợp lệ | `BEDROCK_FAULT_SEQUENCE=malformed_tool_call` | Kiểm tra toàn bộ assistant batch trước khi dispatch; batch lỗi không chạy tool nào | Shopping Copilot trả `FALLBACK`, không có cart action đang chờ |
| Lỗi kéo dài | Lặp lại `timeout`, `throttle` hoặc `server_error` | Mở breaker sau số logical call thất bại đã cấu hình | Request trong trạng thái `OPEN` bỏ qua Bedrock và trả fallback |
| Provider phục hồi | Kết quả `pass` ở cuối sequence sau recovery interval | Cho phép một probe half-open; một call thành công sẽ đóng breaker | Response bình thường trở lại, không cần restart service |

Các outcome được fault plan hỗ trợ là `pass`, `timeout`, `throttle`,
`server_error`, `malformed_json` và `malformed_tool_call`. Fault injection yêu
cầu `LLM_PROVIDER=bedrock` và mặc định bị tắt.

---

## Timeout and Bounded Retry

### Default Configuration

| Thiết lập | Mặc định | Vị trí | Hành vi |
|---|---:|---|---|
| Connect timeout cho mỗi provider attempt | 2 s | `BEDROCK_CONNECT_TIMEOUT_SECONDS` | Giảm theo logical budget còn lại nếu còn dưới 2 s |
| Read timeout cho mỗi provider attempt | 8 s | `BEDROCK_READ_TIMEOUT_SECONDS` | Giảm theo logical budget còn lại nếu còn dưới 8 s |
| Số provider attempt trong một logical Bedrock call | 2 | `BEDROCK_MAX_ATTEMPTS` | Bao gồm call ban đầu |
| Backoff base | 0.25 s | `BEDROCK_BACKOFF_BASE_SECONDS` | Cơ số exponential trước jitter |
| Backoff multiplier | 2 | `_backoff_seconds()` | `base × 2^(attempt-1)` |
| Backoff cap | 1 s | `BEDROCK_BACKOFF_MAX_SECONDS` | Giới hạn delay trước jitter |
| Jitter | Equal jitter, 50–100% delay đã cap | `_backoff_seconds()` | Tránh các retry đồng thời |
| Số lần thử output có cấu trúc | 2 | `BEDROCK_SCHEMA_MAX_ATTEMPTS` | Các lần thử schema dùng chung deadline |
| Logical Bedrock deadline | 12 s | `BEDROCK_TOTAL_DEADLINE_SECONDS` | Bao phủ attempt, backoff và schema retry |
| Product Review frontend deadline | 15 s | `ProductReview.gateway.ts` | Giới hạn thời gian chờ gRPC public |
| Shopping Copilot frontend deadline | 18 s | `ShoppingCopilot.gateway.ts` | Giới hạn thời gian chờ gRPC public |
| Botocore internal attempts | 1 | Shared adapter `BotoConfig` | Ngăn một lớp retry ẩn |
### Retry Classification

Các lỗi có thể retry:

- connect timeout, read timeout, endpoint connection failure và closed
  connection;
- HTTP 429;
- HTTP status `>= 500`;
- `ThrottlingException`, `TooManyRequestsException`,
  `ServiceUnavailableException`, `InternalServerException`,
  `ModelTimeoutException` và `ModelErrorException`.

### Live Retry Evidence

| Trường | Giá trị |
|---|---|
| Kịch bản | `test_02_retry_is_bounded_and_recovers` |
| Fault sequence | `timeout,pass` |
| Cấu hình test | 2 provider attempt; base 50 ms; cap 100 ms; 1 schema attempt; deadline 12 s |
| Số provider attempt quan sát được | `TODO — user fill` |
| Backoff quan sát được | `TODO — user fill` |
| Độ trễ end-to-end | `TODO — user fill` |
| Đường dẫn bằng chứng | `TODO — user fill` |
| Trạng thái | `IMPLEMENTED — LIVE TODO` |

---

## Circuit Breaker

### Configuration and State Machine

| Thiết lập | Mặc định | Hành vi |
|---|---:|---|
| Failure threshold | 3 logical call thất bại | Một logical call được tính một lần sau khi retry hoặc deadline thất bại |
| Failure window | Không có | Các lỗi liên tiếp được cộng dồn cho tới khi có success |
| Open duration | 30 s | Cấu hình bởi `BEDROCK_BREAKER_RECOVERY_SECONDS` |
| Half-open probe limit | 1 probe đang chạy | Request đồng thời bị từ chối khi probe đang chạy |
| Success threshold để đóng | 1 probe thành công | Success reset state và failure count |
| Breaker key | Bedrock model + AWS region | Dùng chung giữa các workflow step trong một process |
| State storage | Process-local memory | Không chia sẻ giữa replica hoặc service process |
| Failure được tính | Retry exhaustion và logical deadline exhaustion | Bao gồm chuỗi timeout, 429 và 5xx tạm thời |
| Failure bị loại trừ | Lỗi cấu hình/client không retry, lỗi policy/user, schema/tool rejection | Half-open failure không retry chỉ giải phóng probe, không tính là outage |

```text
CLOSED
  └─ failure threshold reached ─► OPEN

OPEN
  ├─ before recovery interval ───► reject before provider
  └─ recovery interval elapsed ─► HALF_OPEN

HALF_OPEN
  ├─ successful probe ───────────► CLOSED
  └─ retryable failed probe ─────► OPEN
```

### Live Breaker Evidence

| Giai đoạn | Hành vi triển khai kỳ vọng | Kết quả live thực tế |
|---|---|---|
| Logical call thất bại 1 | Giữ `CLOSED`; trả fallback | `TODO — user fill` |
| Logical call thất bại 2 | Đạt threshold; chuyển sang `OPEN`; trả fallback | `TODO — user fill` |
| Request tiếp theo | Từ chối trước khi dùng outcome `pass` còn lại | `TODO — user fill` |
| Hết recovery interval | Chuyển sang `HALF_OPEN`; cho phép một probe Bedrock thật | `TODO — user fill` |
| Probe thành công | Chuyển về `CLOSED` mà không restart | `TODO — user fill` |
| Đường dẫn bằng chứng | Replay/log/trace artifact | `TODO — user fill` |

Trạng thái: `IMPLEMENTED — LIVE TODO`.

---

## Structured Output and Tool Safety

### Validation Boundaries

| Output | Schema | Parser và validation | Giới hạn | Cổng tool |
|---|---|---|---:|---|
| Retrieval hint | `RetrievalHint` | `model_validate_json()` | Mặc định 2 schema attempt | N/A |
| Memory extraction | `MemoryExtraction` | `model_validate_json()` | Mặc định 2 schema attempt | N/A |
| Review summary draft | `GroundedDraft` | `model_validate_json()`, sau đó kiểm tra evidence thành `GroundedResponse` | Mặc định 2 schema attempt | N/A |
| ReAct assistant batch | Bedrock content shape và Pydantic tool input model | Kiểm tra mọi content block, tool ID, tool name, input object và argument model | Một batch trả về; batch lỗi đi vào fallback | Chỉ tới `_run_tool()` sau khi toàn batch hợp lệ |

Shopping Copilot kiểm tra ReAct tool input bằng:

- `CatalogSearchInput`;
- `ProductInput`;
- `ReviewQuestionInput`;
- `CartActionInput`.

Thứ tự validation:

1. Kiểm tra shape của Bedrock assistant message và content list.
2. Kiểm tra mỗi block chỉ là text hoặc tool use.
3. Kiểm tra tool có được phép dùng trong turn hay không.
4. Kiểm tra mọi tool ID, name và input object.
5. Validate mọi input bằng Pydantic model tương ứng.
6. Từ chối call trùng lặp.
7. Chỉ chạy tool sau khi toàn bộ batch vượt qua validation.

Batch có cả call hợp lệ và không hợp lệ sẽ không chạy gì, vì validation hoàn
tất trước khi message hoặc application state bị thay đổi.

### Injected Malformed Fixtures

Fixture JSON có cấu trúc lỗi:

```json
{
  "wrong_schema": true
}
```

Fixture tool call:

```json
{
  "toolUse": {
    "toolUseId": "mandate25-invalid",
    "name": "prepare_cart_action",
    "input": {
      "quantity": 0
    }
  }
}
```

### Live Garbage-output Evidence

| Kiểm tra | Kỳ vọng | Thực tế |
|---|---|---|
| Service response | `FALLBACK` có kiểm soát, không phải RPC failure | `TODO — user fill` |
| Kết quả parser/schema | Từ chối invalid tool batch | `TODO — user fill` |
| Số invalid tool call đã chạy | 0 | `TODO — user fill` |
| Cart trước và sau | Giống hệt nhau | `TODO — user fill` |
| Pending action được tạo | Không | `TODO — user fill` |
| Bedrock request thật tiếp theo | Trả status có kiểm soát bình thường | `TODO — user fill` |
| Đường dẫn bằng chứng | JSON/log/cart snapshot | `TODO — user fill` |

Trạng thái: `IMPLEMENTED — LIVE TODO`.

---

## Observability

### Implemented Metrics

| Metric | Loại | Thuộc tính chính | Mục đích |
|---|---|---|---|
| `bedrock_provider_calls_total` | Counter | `workflow_step`, `attempt` | Đếm provider attempt |
| `bedrock_provider_failures_total` | Counter | `workflow_step`, `reason_class`, `retryable` | Đếm provider attempt failure |
| `bedrock_retries_total` | Counter | `workflow_step`, `reason_class` | Đếm retry có giới hạn đã lên lịch |
| `bedrock_request_duration_seconds` | Histogram | `workflow_step`, `outcome` | Đo latency logical call, gồm cả retry |
| `bedrock_breaker_state_transitions_total` | Counter | `workflow_step`, `to_state` | Đếm chuyển trạng thái breaker |
| `bedrock_circuit_open_rejections_total` | Counter | `workflow_step`, `breaker_state` | Đếm call bị bỏ qua trước Bedrock |
| `bedrock_schema_validation_failures_total` | Counter | `workflow_step`, `boundary` | Đếm output có cấu trúc bị từ chối |
| `bedrock_deadline_exceeded_total` | Counter | `workflow_step` | Đếm logical deadline exhaustion |
| `bedrock_fault_injections_total` | Counter | `workflow_step`, `outcome` | Đếm fault được tiêu thụ |
| `app_ai_assistant_fallback_total` | Counter | `provider`, `error_class` | Đếm Product Review fallback |

Observability layer dùng chung còn phát model span và tool span không chứa nội
dung nhạy cảm, token usage, chi phí ước tính khi biết bảng giá và span
`app.ai.fallback`. Layer này không đính kèm raw prompt, raw tool argument hoặc
raw PII.

### Implemented Log Events

- `bedrock_fault_injected`;
- `bedrock_retry_scheduled`;
- `bedrock_breaker_opened`;
- `bedrock_breaker_rejected`;
- `bedrock_breaker_half_open`;
- `bedrock_breaker_recovered`;
- `bedrock_schema_rejected`;
- `bedrock_fallback_returned`;
- Shopping Copilot ghi log quá trình suy giảm an toàn theo exception class,
  nhưng không trả thông tin chi tiết của provider cho người dùng.

### Observability Evidence

- Metrics export: `TODO — user fill`
- Retry timeline: `TODO — user fill`
- Breaker transition logs: `TODO — user fill`
- Invalid-output trace/tool audit: `TODO — user fill`
- Dashboard hoặc screenshots: `TODO — user fill`

---

## Reproduction and Fault Injection

Lỗi provider đơn lẻ:

```powershell
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_01_provider_failure_falls_back
```

Retry có giới hạn rồi Bedrock thật phục hồi:

```powershell
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_02_retry_is_bounded_and_recovers
```

Lỗi kéo dài, breaker từ chối request và phục hồi half-open:

```powershell
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_03_sustained_failure_opens_breaker_then_recovers
```

Tool call lỗi kèm kiểm tra cart trước/sau:

```powershell
python src/product-reviews/tests/test_mandate25_bedrock_mock.py Mandate25RealBedrockScenarioTests.test_04_malformed_tool_call_never_executes
```

Chạy toàn bộ kịch bản live và ghi một file bằng chứng:

```powershell
$env:MANDATE25_EVIDENCE_FILE = "artifacts/mandate25-evidence.json"
python src/product-reviews/tests/test_mandate25_bedrock_mock.py
```
---

## Verification Status

### Local Checks Performed During This Audit

| Kiểm tra | Kết quả | Diễn giải |
|---|---|---|
| Mandate #25 live suite với pytest collection mặc định | `4 skipped` | Đúng với cấu hình hiện tại vì chưa bật `RUN_MANDATE25_LIVE`; đây không phải kết quả pass |
| Shopping Copilot unit test mục tiêu | `11 passed, 5 failed` | Unit suite hiện chưa xanh hoàn toàn |
| Product Review reliability-suite collection | Collection failed | Python environment hiện thiếu `openfeature.contrib`; lần chạy này chưa xác minh được hành vi |
| Live evidence artifact trong working tree | Không tìm thấy | Live DoD vẫn là TODO |
| Mandate #25 ADR đã ký | Không tìm thấy | Governance DoD vẫn là TODO |

### Current Unit-test Mismatches

1. `test_converse_json_accepts_explanatory_text_around_json` kỳ vọng runtime
   trích JSON từ phần văn bản bao quanh. Shared adapter hiện yêu cầu JSON
   strict và đúng ra ném `InvalidModelOutputError` sau các schema attempt có
   giới hạn. Test hiện tại không khớp với strict contract được định ra.
2. Bốn test của `copilot_graph` mock `parse_retrieval_hint` bằng signature cũ.
   Graph hiện truyền thêm keyword `deadline`, khiến mock ném `TypeError` và
   graph trả controlled fallback.
3. Product Review reliability tests không collection được trong Python
   environment hiện có vì thiếu `openfeature.contrib`.

Các vấn đề này chưa được giải quyết. Không đánh dấu suite liên quan là pass
cho tới khi sửa test và môi trường rồi chạy lại.

---

## DoD Verification Matrix

| DoD | Replay case | Tiêu chí chấp nhận | Evidence artifact | Trạng thái |
|---|---|---|---|---|
| Provider failure đơn lẻ | `test_01_provider_failure_falls_back` | Thành công ở mức non-500/RPC; latency có giới hạn; fallback an toàn hiển thị cho người dùng | `TODO — user fill` | `IMPLEMENTED — LIVE TODO` |
| Retry có giới hạn | `test_02_retry_is_bounded_and_recovers` | Một timeout được inject, tối đa hai provider attempt, backoff có cap, không treo | `TODO — user fill` | `IMPLEMENTED — LIVE TODO` |
| Breaker mở | Ba phase đầu của `test_03_sustained_failure_opens_breaker_then_recovers` | Lỗi kéo dài mở breaker; request tiếp theo bỏ qua provider | `TODO — user fill` | `IMPLEMENTED — LIVE TODO` |
| Breaker phục hồi | Phase cuối của `test_03_sustained_failure_opens_breaker_then_recovers` | Probe Bedrock half-open đóng breaker mà không restart | `TODO — user fill` | `IMPLEMENTED — LIVE TODO` |
| Chặn garbage output | `test_04_malformed_tool_call_never_executes` | Từ chối argument lỗi; cart không đổi; không có pending token | `TODO — user fill` | `IMPLEMENTED — LIVE TODO` |
| ADR đã ký | `TODO — user fill: ADR ID` | Có trạng thái Accepted, owner/reviewer và ngày được ghi rõ | `TODO — user fill` | `TODO — user fill` |

---

## Results — User Completion Area

### Single Provider Failure

| Trường | Giá trị |
|---|---|
| Bề mặt | Shopping Copilot |
| Lỗi | Inject `server_error` hai lần tại `retrieval_hint` |
| Số provider attempt cấu hình | 2 |
| Trạng thái cuối | `TODO — user fill` |
| Kết quả gRPC | `TODO — user fill` |
| Response người dùng nhìn thấy | `TODO — user fill` |
| Latency end-to-end | `TODO — user fill` |
| Claims được bịa | `TODO — user fill; required 0` |
| Bằng chứng | `TODO — user fill` |

Diễn giải: `TODO — user fill`.

### Sustained Failure and Recovery

| Metric | Kết quả |
|---|---:|
| Failure threshold đã cấu hình | 2 logical call trong kịch bản live |
| Số lỗi quan sát được trước khi mở | `TODO — user fill` |
| Số request được phục vụ khi breaker mở | `TODO — user fill` |
| Số primary call được bỏ qua khi breaker mở | `TODO — user fill` |
| Recovery interval đã cấu hình | 2 s trong kịch bản live |
| Số half-open probe quan sát được | `TODO — user fill` |
| Thời gian tự phục hồi | `TODO — user fill` |
| Số service restart cần thiết | `TODO — user fill; required 0` |

Diễn giải: `TODO — user fill`.

### Malformed Output

| Metric | Kết quả |
|---|---:|
| Số output lỗi được inject | `TODO — user fill` |
| Số output lỗi bị chặn | `TODO — user fill` |
| Tool call có argument lỗi | `TODO — user fill; required 0` |
| Pending action được tạo | `TODO — user fill; required 0` |
| Cart mutation | `TODO — user fill; required 0` |
| Response có kiểm soát | `TODO — user fill` |
| Crash/RPC failure | `TODO — user fill; required 0` |

Diễn giải: `TODO — user fill`.

### Reliability and Latency

| Metric | Baseline khỏe | Có fault injection | Breaker mở | Sau phục hồi |
|---|---:|---:|---:|---:|
| Requests | `TODO` | `TODO` | `TODO` | `TODO` |
| Controlled responses | `TODO` | `TODO` | `TODO` | `TODO` |
| Tỷ lệ bảo toàn request | `TODO` | `TODO` | `TODO` | `TODO` |
| Primary provider calls | `TODO` | `TODO` | `TODO` | `TODO` |
| Tỷ lệ fallback | `TODO` | `TODO` | `TODO` | `TODO` |
| Latency p50 | `TODO` | `TODO` | `TODO` | `TODO` |
| Latency p95 | `TODO` | `TODO` | `TODO` | `TODO` |

```text
request_preservation_rate
= controlled_non_500_responses / injected_requests

fallback_rate
= fallback_responses / total_requests

provider_calls_avoided
= requests_while_open - primary_provider_calls_while_open
```

Cỡ mẫu và phương pháp tính percentile: `TODO — user fill`.

### Safety Hard Bars

| Hard bar | Yêu cầu | Thực tế | Trạng thái |
|---|---:|---:|---|
| 500/RPC failure trong fallback bắt buộc | 0 | `TODO` | `TODO` |
| Request vượt overall deadline | 0 | `TODO` | `TODO` |
| Tool chạy với argument chưa validation | 0 | `TODO` | `TODO` |
| Side effect trái phép lên cart/data | 0 | `TODO` | `TODO` |
| Business claim bịa trong degraded mode | 0 | `TODO` | `TODO` |
| Lộ secret, system prompt hoặc stack trace | 0 | `TODO` | `TODO` |
| Primary provider call khi breaker `OPEN` | 0 | `TODO` | `TODO` |

---

## ADR — User Completion Area

- **ADR ID:** `TODO — user fill`
- **Trạng thái:** `TODO — user fill; required Accepted`
- **Design owner:** `TODO — user fill`
- **Reviewers:** `TODO — user fill`
- **Ngày quyết định:** `TODO — user fill`
- **Phạm vi:** Product Review và Shopping Copilot

### Decisions Reflected in the Current Implementation

| Quyết định | Lựa chọn đã triển khai | Hệ quả |
|---|---|---|
| Fallback strategy | `FALLBACK`/abstention trung thực; không dùng fallback model | Tránh bịa thông tin sản phẩm hoặc review |
| Retry policy | Hai provider attempt, exponential equal-jitter backoff có cap, deadline 12 s | Ngăn retry vô hạn và retry ẩn bị khuếch đại từ SDK |
| Circuit breaker | Shared adapter tùy biến | Một resilience policy phục vụ cả hai bề mặt |
| Breaker scope | Process-local, định danh theo model và region | Các replica không chia sẻ breaker state |
| Recovery | Một half-open probe sau interval đã cấu hình | Provider khỏe sẽ đóng breaker mà không restart |
| Structured validation | Pydantic tại ranh giới model output | Output có cấu trúc lỗi không đi vào business logic |
| Tool safety | Kiểm tra toàn bộ ReAct batch trước dispatch | Một call lỗi chặn toàn bộ call trong batch |
| Degraded contract | `FALLBACK` rõ ràng, thông báo trung thực, xóa state dở dang | Người dùng thấy suy giảm có kiểm soát, không có claim không được hỗ trợ |
| Fault injection | Điều khiển bằng environment theo workflow step và outcome sequence | Live test inject lỗi mà không cần patch object Python |

### Risks Requiring ADR Review

| Rủi ro | Giảm thiểu hiện tại | Rủi ro còn lại / quyết định cần có |
|---|---|---|
| Retry amplification | Botocore internal attempts cố định là 1; adapter sở hữu retry | Xác nhận giới hạn production và giả định về capacity |
| Breaker mở quá sớm | Threshold và recovery interval có thể cấu hình | Tinh chỉnh bằng bằng chứng production |
| Breaker state khác nhau giữa replica | Process-local locking | Quyết định có cần state phân tán hay không |
| Một workflow step reset failure streak của step khác | Breaker key theo model và region | Quyết định key theo surface hay workflow step |
| Dependency gRPC nội bộ bị treo | Frontend gateway deadline | Nếu cần, thêm deadline cho từng call bên trong Copilot |
| Legacy response parser của Product Review fail open | API bắt gateway error, nhưng plain text legacy vẫn được xem là grounded | Quyết định có đổi nhánh compatibility sang `FALLBACK` hay không |

### Sign-off

| Vai trò | Tên | Quyết định | Ngày |
|---|---|---|---|
| Design owner | `TODO — user fill` | `TODO — user fill` | `TODO — user fill` |
| Reviewer | `TODO — user fill` | `TODO — user fill` | `TODO — user fill` |
| Reviewer | `TODO — user fill` | `TODO — user fill` | `TODO — user fill` |

---

## Evidence Inventory

| Artifact | Nội dung bắt buộc | Path/link | Sẵn sàng |
|---|---|---|---|
| Implementation PR/commit | Resilience implementation | `TODO — user fill` | `[ ]` |
| Configuration evidence | Timeout, retry, deadline và breaker bounds | `TODO — user fill` | `[ ]` |
| Single-failure replay | Controlled fallback và latency có giới hạn | `TODO — user fill` | `[ ]` |
| Retry timeline | Attempt, backoff và tổng giới hạn | `TODO — user fill` | `[ ]` |
| Breaker-open replay | Provider call dừng khi breaker mở | `TODO — user fill` | `[ ]` |
| Recovery replay | Half-open probe đưa breaker về closed | `TODO — user fill` | `[ ]` |
| Malformed-output fixture | Blob được inject chính xác | `TODO — user fill` | `[ ]` |
| Tool-safety evidence | Số invalid tool execution bằng 0 | `TODO — user fill` | `[ ]` |
| Cart safety evidence | Snapshot trước/sau và không có pending token | `TODO — user fill` | `[ ]` |
| Metrics export | Preservation rate và fallback latency | `TODO — user fill` | `[ ]` |
| Logs/traces/screenshots | Retry, fallback, breaker và schema event | `TODO — user fill` | `[ ]` |
| Reproduction script | Entry point fault injection bên ngoài | `src/product-reviews/tests/test_mandate25_bedrock_mock.py` | `[x]` |
| Signed ADR | Trạng thái Accepted và reviewer được nêu tên | `TODO — user fill` | `[ ]` |

Đường dẫn artifact đề xuất:

```text
artifacts/mandate25/
├── evidence.json
├── retry-timeline.txt
├── breaker-transitions.txt
├── malformed-output.json
├── cart-before-after.json
├── metrics-summary.md
└── repro-output.txt
```

---

## Hidden-set Readiness Checklist

- [ ] Một provider failure trả controlled response, không trả 500/RPC failure.
- [ ] Timeout và retry bounds hiển thị trong live evidence.
- [ ] Lỗi kéo dài mở breaker tại threshold đã cấu hình.
- [ ] Request trong trạng thái `OPEN` không gọi Bedrock.
- [ ] Probe khỏe đưa breaker về `CLOSED`.
- [ ] Phục hồi không cần restart service.
- [ ] JSON có cấu trúc lỗi không làm service crash.
- [ ] Tool argument sai schema không được dispatch.
- [ ] Số invalid tool execution bằng 0.
- [ ] Cart không đổi và không còn pending token.
- [ ] Degraded response trung thực, không có claim bịa.
- [ ] Replay nhận fault thông qua cấu hình bên ngoài.
- [ ] Đã đính kèm bằng chứng từng case và số đo tổng hợp.
- [ ] ADR đã được chấp nhận và ký.

---

## Limitations and Follow-up

1. Chạy cả bốn kịch bản live và đính kèm JSON, log, trace cùng bằng chứng
   cart trước/sau.
2. Bổ sung replay live trực tiếp cho Product Review nếu muốn tuyên bố cả hai
   bề mặt đã được chứng minh đầy đủ.
3. Sửa năm Shopping Copilot unit-test failure và chạy lại suite.
4. Cài dependency test của Product Review trong verification environment rồi
   chạy lại reliability suite.
5. Quyết định breaker scope có tiếp tục là process-local và dùng chung giữa
   các workflow step hay không.
6. Thêm deadline cho gRPC nội bộ của Copilot nếu cần 12-second graph budget
   dừng cả worker activity, không chỉ thời gian chờ của public client.
7. Rà soát legacy gateway parser của Product Review, hiện đang xem backend text
   không parse được là `GROUNDED`.
8. Tạo, review, chấp nhận và ký ADR cho Mandate #25.
9. Bổ sung link PR, commit, Jira, dashboard, artifact, owner và final sign-off.

Owner/ticket/date của follow-up: `TODO — user fill`.

---

## Evidence Links and Ownership

- Implementation PR: `TODO — user fill`
- Commit: `TODO — user fill`
- Replay script:
  `src/product-reviews/tests/test_mandate25_bedrock_mock.py`
- Replay results: `TODO — user fill`
- Metrics summary: `TODO — user fill`
- Dashboard/traces: `TODO — user fill`
- ADR: `TODO — user fill`
- Jira ticket `AI MANDATE #25`: `TODO — user fill`

Phân công:

- **Resilience design và implementation:** `TODO — user fill`
- **Fault injection và replay:** `TODO — user fill`
- **Evidence review:** `TODO — user fill`
- **ADR approvers:** `TODO — user fill`
- **Ngày final sign-off:** `TODO — user fill`
