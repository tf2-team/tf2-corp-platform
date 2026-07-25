# MANDATE #25 — Task 1: Bedrock Reliability và Product Reviews

## 1. Mục tiêu

Xây dựng lớp reliability dùng chung cho Amazon Bedrock và tích hợp vào
`product-reviews`. Khi provider timeout, throttling, trả HTTP 5xx hoặc trả output
không hợp lệ, hệ thống phải:

- không trả HTTP 500 do exception từ model;
- không treo vô hạn;
- giới hạn số lần retry và thời gian backoff;
- mở circuit breaker khi lỗi kéo dài;
- ngừng gọi provider khi circuit breaker đang mở;
- tự phục hồi khi provider hoạt động trở lại;
- trả `FALLBACK` hoặc `ABSTAINED` trung thực, không bịa nội dung;
- chỉ sử dụng output đã qua schema validation và grounding.

Task 1 chịu trách nhiệm chính cho Requirements 1–4 của MANDATE #25 trên Product
Reviews, đồng thời cung cấp các reliability primitive cho Task 2.

## 2. Phạm vi

### Trong phạm vi

- Bedrock adapter dùng chung trong `src/ai-common/techx_ai_common/bedrock.py`.
- Timeout và retry có giới hạn cho Bedrock Converse.
- Exponential backoff có trần.
- Circuit breaker thread-safe dùng chung trong từng service process.
- Fallback của Bedrock trong `src/product-reviews/product_reviews_server.py`.
- Schema validation đối với `GroundedDraft`.
- Grounding và abstention khi model output không đủ bằng chứng.
- Log, metrics và unit/integration test liên quan.
- Cấu hình qua biến môi trường và Docker Compose.

### Ngoài phạm vi

- Thay đổi model Bedrock hoặc AWS account.
- Thực hiện fallback sang một model thứ hai.
- Thay đổi giao diện gRPC công khai.
- Xây dựng replay script và tài liệu Jira cuối cùng; phần này thuộc Task 2.
- Thay đổi business logic catalog/cart của Shopping Copilot.

## 3. Các file chính

- `src/ai-common/techx_ai_common/bedrock.py`
- `src/product-reviews/product_reviews_server.py`
- `src/product-reviews/tests/test_reliability.py`
- Test mới cho Bedrock reliability trong `src/ai-common/tests/`
- `docker-compose.yml`
- `.env`

Không đưa secret, AWS access key hoặc prompt của người dùng vào log, test fixture
hay tài liệu.

## 4. Interface bàn giao cho Task 2

Giữ tương thích hai hàm đang được sử dụng:

```python
def converse_text(system_prompt: str, user_prompt: str) -> str:
    ...

def converse_json(
    response_model: type[T],
    system_prompt: str,
    user_prompt: str,
) -> T:
    ...
```

Task 1 có thể bổ sung API đọc trạng thái để phục vụ health check, test và evidence:

```python
def get_breaker_state() -> str:
    """Trả CLOSED, OPEN hoặc HALF_OPEN."""
```

Các public exception phải ổn định để caller có thể phân loại:

```python
class BedrockUnavailableError(RuntimeError):
    """Provider lỗi hoặc retry đã cạn."""


class CircuitBreakerOpenError(BedrockUnavailableError):
    """Request bị chặn trước khi gọi provider vì breaker đang mở."""


class InvalidModelOutputError(RuntimeError):
    """Output không qua schema validation sau số lần repair cho phép."""
```

Caller không được phụ thuộc vào exception nội bộ của boto3/botocore.

## 5. Cấu hình bắt buộc

Thêm các biến môi trường sau với giá trị mặc định an toàn:

| Biến | Default | Ý nghĩa |
|---|---:|---|
| `BEDROCK_CONNECT_TIMEOUT_SECONDS` | `3` | Timeout thiết lập kết nối |
| `BEDROCK_READ_TIMEOUT_SECONDS` | `12` | Timeout chờ provider response |
| `BEDROCK_MAX_ATTEMPTS` | `3` | Tổng số lần gọi provider, gồm lần đầu |
| `BEDROCK_BACKOFF_BASE_SECONDS` | `0.25` | Backoff cơ sở |
| `BEDROCK_BACKOFF_MAX_SECONDS` | `2` | Trần backoff |
| `BEDROCK_SCHEMA_MAX_ATTEMPTS` | `2` | Tổng số lần thử khi JSON hoặc schema sai |
| `BEDROCK_BREAKER_FAILURE_THRESHOLD` | `5` | Số lỗi liên tiếp để mở breaker |
| `BEDROCK_BREAKER_RECOVERY_SECONDS` | `30` | Thời gian chờ trước half-open probe |

Ràng buộc cấu hình:

- Mọi timeout phải lớn hơn 0.
- `MAX_ATTEMPTS` và `SCHEMA_MAX_ATTEMPTS` phải từ 1 trở lên.
- Backoff tối đa không được nhỏ hơn backoff cơ sở.
- Failure threshold phải từ 1 trở lên.
- Cấu hình sai phải khiến service fail-fast khi khởi động; thông báo lỗi không
  được chứa secret.

## 6. Thiết kế retry

### Provider retry

Chỉ retry các lỗi tạm thời:

- connect/read timeout;
- throttling/rate limit;
- HTTP 5xx;
- lỗi kết nối tạm thời được botocore đánh dấu retryable.

Không retry các lỗi sau:

- thiếu hoặc sai credential;
- access denied;
- model ID không hợp lệ;
- request validation error;
- lỗi cấu hình ứng dụng.

Tổng số lần gọi không được vượt `BEDROCK_MAX_ATTEMPTS`. Dùng exponential backoff
có jitter, với thời gian chờ không vượt `BEDROCK_BACKOFF_MAX_SECONDS`.

Không để boto3 retry ngầm ngoài retry policy của ứng dụng. Nếu dùng cơ chế retry
của botocore, phải cấu hình rõ ràng và dùng test chứng minh tổng số lần gọi không
vượt giới hạn. Không chồng hai lớp retry khiến số lần gọi tăng ngoài dự kiến.

### Schema retry

`converse_json()` phải:

1. lấy text từ Bedrock;
2. validate trực tiếp bằng Pydantic model;
3. nếu JSON/schema sai, thử lại tối đa `BEDROCK_SCHEMA_MAX_ATTEMPTS`;
4. không trả text hoặc object chưa validate;
5. raise `InvalidModelOutputError` khi đã dùng hết số lần thử.

Schema retry phải nằm trong request deadline tổng thể. Không tạo hai chuỗi
provider retry độc lập khiến request vượt giới hạn thời gian thiết kế.

## 7. Thiết kế circuit breaker

Breaker có ba trạng thái:

- `CLOSED`: cho phép gọi provider.
- `OPEN`: từ chối ngay, không gọi boto3.
- `HALF_OPEN`: chỉ cho phép một probe kiểm tra provider đã hồi phục chưa.

Quy tắc:

1. Một provider call thành công reset bộ đếm lỗi và giữ/đưa breaker về `CLOSED`.
2. Sau khi cạn retry, lỗi provider retryable chỉ tăng failure counter một lần cho
   mỗi logical request.
3. Khi failure counter đạt threshold, breaker chuyển sang `OPEN`.
4. Trong `OPEN`, request bị từ chối ngay bằng `CircuitBreakerOpenError`.
5. Khi hết recovery interval, chỉ một request được thực hiện half-open probe.
6. Probe thành công chuyển breaker sang `CLOSED` và reset counter.
7. Probe thất bại chuyển breaker về `OPEN` và bắt đầu recovery interval mới.
8. Lỗi schema không được tính là provider outage nếu provider vẫn phản hồi thành
   công; theo dõi bằng metric riêng.
9. Implementation phải thread-safe vì gRPC server dùng nhiều worker.

Breaker được phân tách theo process, Bedrock model và region. Task này không yêu
cầu đồng bộ breaker qua Redis/Valkey.

## 8. Tích hợp Product Reviews

Luồng `LLM_PROVIDER=bedrock` phải giữ thứ tự:

1. Rate limit và input guardrail.
2. Backend lấy review theo `request_product_id` trong request, không dùng tool
   arguments do model tạo.
3. Sanitize reviews và retrieval.
4. Nếu không có review hợp lệ, trả `ABSTAINED` và không gọi Bedrock.
5. Nếu có review hợp lệ, gọi `generate_grounded_summary()`.
6. Chỉ nhận `GroundedDraft` đã qua Pydantic.
7. Chạy `validate_grounded_summary()`.
8. Chỉ trả các claim còn nguồn hợp lệ.
9. Khi provider lỗi, breaker mở hoặc output vẫn không hợp lệ sau retry, trả
   response có `status=FALLBACK`.

Fallback message mặc định:

```text
AI summary is temporarily unavailable.
```

Không đưa raw exception message, AWS request body, credential, prompt hoặc review
PII vào response. `reason` chỉ chứa error class hoặc category ổn định.

## 9. Observability

### Structured log

Ghi các event:

- `bedrock_call_started`
- `bedrock_retry_scheduled`
- `bedrock_retry_exhausted`
- `bedrock_schema_rejected`
- `bedrock_breaker_opened`
- `bedrock_breaker_rejected`
- `bedrock_breaker_half_open`
- `bedrock_breaker_recovered`
- `bedrock_fallback_returned`

Các field bắt buộc:

- service name;
- provider và model ID;
- attempt number;
- error category;
- breaker state;
- elapsed milliseconds.

Không log system prompt, user prompt, model output nguyên văn hoặc AWS credential.

### Metrics

Các metric bắt buộc:

- provider calls;
- provider failures theo category;
- retry count;
- schema rejection count;
- fallback count;
- breaker transition count;
- breaker rejected-request count;
- provider latency;
- fallback latency.

Tên metric phải ổn định để Task 2 có thể dùng làm evidence.

## 10. Test bắt buộc

Tất cả test phải dùng fake client, clock và sleep; không gọi AWS thật.

### Bedrock adapter

- Valid response trả đúng Pydantic model.
- Timeout được retry đúng số lần.
- Throttling được retry đúng số lần.
- HTTP 5xx được retry đúng số lần.
- Access denied không retry.
- Backoff tăng dần và không vượt trần.
- Tổng số lần gọi không vượt cấu hình.
- Malformed JSON lần đầu, hợp lệ lần hai thì thành công.
- Malformed JSON mọi lần thì raise `InvalidModelOutputError`.
- Field thừa hoặc sai kiểu bị Pydantic reject.

### Circuit breaker

- Dưới threshold breaker vẫn `CLOSED`.
- Đạt threshold breaker chuyển `OPEN`.
- Trong `OPEN`, boto3 fake không được gọi.
- Chưa hết recovery interval thì không probe.
- Hết interval thì đúng một request được probe.
- Probe thành công chuyển `CLOSED`.
- Probe thất bại chuyển lại `OPEN`.
- Hai thread đồng thời không được cùng thực hiện half-open probe.

### Product Reviews

- Provider timeout trả `FALLBACK`, không ném exception ra gRPC handler.
- Provider 5xx trả `FALLBACK`.
- Breaker open trả fallback nhanh và không gọi provider.
- Invalid `GroundedDraft` trả fallback.
- Không có safe review trả `ABSTAINED` và không gọi provider.
- Claim có source ID giả bị loại.
- Claim bịa số bị loại.
- Không có claim sống sót thì abstain.

## 11. Definition of Done

Task hoàn thành khi:

- Timeout, attempts và backoff cap được cấu hình rõ trong code.
- Test chứng minh không retry vô hạn.
- Circuit breaker mở sau chuỗi lỗi và chặn provider calls.
- Breaker tự phục hồi sau một successful half-open probe.
- Product Reviews không trả application error khi Bedrock timeout hoặc trả 5xx.
- Malformed output không được sử dụng và dẫn đến fallback có kiểm soát.
- Fallback không bịa nội dung.
- Log và metrics đủ để Task 2 thu thập evidence.
- Toàn bộ test mới pass trong môi trường repository/container.
- Interface bàn giao đã được cung cấp cho người thực hiện Task 2.

## 12. Bàn giao

Người thực hiện cung cấp:

- commit/PR chứa implementation;
- danh sách biến môi trường mới;
- câu lệnh chạy unit tests;
- ví dụ log breaker open và recovery từ test;
- ghi chú interface/exception để Task 2 tích hợp;
- xác nhận không thay đổi public gRPC contract.
