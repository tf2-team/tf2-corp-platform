# MANDATE #25 — Task 2: Shopping Copilot, Fault Replay và Evidence

## 1. Mục tiêu

Tích hợp lớp Bedrock reliability của Task 1 vào `shopping-copilot`; chứng minh
malformed model output không kích hoạt downstream tool; đồng thời chuẩn bị đầy
đủ replay, ADR và evidence cho Jira `AI MANDATE #25`.

Task hoàn thành khi ban chấm có thể chủ động tạo từ bên ngoài:

1. một lỗi provider đơn;
2. một chuỗi lỗi provider kéo dài;
3. một malformed model output;

Kết quả phải chứng minh hệ thống fallback, mở breaker, không chạy tool với dữ
liệu rác và tự phục hồi khi provider hoạt động trở lại.

## 2. Phụ thuộc từ Task 1

Task 2 sử dụng các API ổn định từ
`src/ai-common/techx_ai_common/bedrock.py`:

```python
converse_text(system_prompt, user_prompt)
converse_json(response_model, system_prompt, user_prompt)
get_breaker_state()
```

Task 2 phải xử lý các exception sau:

```python
BedrockUnavailableError
CircuitBreakerOpenError
InvalidModelOutputError
```

Task 2 không được triển khai thêm một cơ chế retry hoặc circuit breaker. Nếu
interface của Task 1 chưa sẵn sàng, dùng fake adapter trong test nhưng không merge
implementation trùng lặp vào Shopping Copilot.

## 3. Phạm vi

### Trong phạm vi

- Bedrock intent parsing trong Shopping Copilot.
- Fallback routing của LangGraph.
- Deadline có hiệu lực đối với lời gọi synchronous.
- Schema validation của `ShoppingIntent`.
- Chứng minh catalog/review/cart tools không chạy sau malformed output.
- Cart pending-action safety.
- Fault injection có thể được điều khiển từ bên ngoài.
- Repro scripts/commands chạy bằng Docker Compose.
- Test, log, metrics, ADR và evidence.
- Nội dung bàn giao cho Jira `AI MANDATE #25`.

### Ngoài phạm vi

- Viết lại reliability adapter của Task 1.
- Thay đổi AWS account/model.
- Cho phép model gọi trực tiếp `CartService.AddItem`.
- Thay đổi public gRPC/protobuf nếu không thật sự cần thiết.
- Xây UI quản trị fault injection.

## 4. Các file chính

- `src/shopping-copilot/intent_parser.py`
- `src/shopping-copilot/copilot_graph.py`
- `src/shopping-copilot/copilot_server.py`
- `src/shopping-copilot/copilot_contracts.py`
- `src/shopping-copilot/cart_tool.py`
- `src/shopping-copilot/tests/test_bedrock_runtime.py`
- `src/shopping-copilot/tests/test_copilot_graph.py`
- Fault replay test/script mới trong `src/shopping-copilot/tests/` hoặc `scripts/`
- `docs/ai-engineering/AI_MANDATE_25_EVIDENCE.md`
- `docs/ai-engineering/ADR-AIE-25-controlled-degradation.md`

## 5. Hành vi Shopping Copilot bắt buộc

### Luồng thành công

1. Input guardrail xử lý user message.
2. Bedrock trả JSON cho `ShoppingIntent`.
3. Pydantic validate toàn bộ intent.
4. Chỉ chuyển intent hợp lệ sang catalog node.
5. Product IDs dùng cho review/cart phải lấy từ catalog results.
6. AI chỉ được tạo pending cart action.
7. Chỉ chạy `CartService.AddItem` qua `ConfirmCartAction` sau khi xác thực token.

### Lỗi provider

Khi xảy ra timeout, throttling, HTTP 5xx, retry exhausted hoặc breaker open, hệ
thống phải:

- trả `CopilotStatus.FALLBACK`;
- trả reason trung thực, ví dụ:

```text
Shopping assistance is temporarily unavailable. Please try again shortly.
```

- không trả stack trace hoặc raw provider error;
- không chạy catalog, review hay cart node;
- không tạo pending cart token;
- không gọi `CartService.AddItem`.

### Malformed model output

Schema boundary phải chặn mọi output sau:

- JSON sai cú pháp;
- JSON đúng cú pháp nhưng sai kiểu;
- thiếu trường bắt buộc theo contract;
- field thừa;
- enum/value vượt constraint;
- object/list sai shape.

Sau số lần schema retry cho phép, hệ thống phải:

- trả `FALLBACK`;
- không crash;
- không gọi downstream tools;
- log `bedrock_schema_rejected`;
- không đưa malformed blob vào response hoặc log.

## 6. Deadline và blocking-call safety

`boto3` chạy đồng bộ. Không thể chỉ bọc một coroutine không yield bằng
`asyncio.wait_for()` rồi coi Bedrock call đã có giới hạn thời gian.

Phải bảo đảm deadline bằng:

1. connect/read timeout trong adapter Task 1;
2. tổng attempts có giới hạn;
3. backoff có trần;
4. nếu giữ graph-level deadline, chạy phần blocking trong worker thread/future và
   giới hạn thời gian chờ.

Test phải dùng fake blocking provider để chứng minh request kết thúc trong giới
hạn kỳ vọng. Unit test không được chờ timeout thật hàng chục giây; dùng fake
clock, fake sleep hoặc timeout rất nhỏ.

## 7. Tool safety

### Catalog

- Chỉ gọi sau khi `ShoppingIntent` đã validate.
- Intent parse failure phải skip catalog node.
- Test sử dụng mock và `assert_not_called()`.

### Review Q&A

- `target_product_id` phải thuộc `allowed_product_ids`.
- Không dùng product ID do model cung cấp trực tiếp nếu catalog chưa xác nhận.
- Malformed intent phải không gọi Product Review service.

### Cart

- Model không được gọi trực tiếp `CartService.AddItem`.
- Graph chỉ được gọi `create_pending_token()`.
- Product ID trong pending token phải lấy từ catalog result đã cho phép.
- Quantity phải nằm trong constraint của contract.
- `ConfirmCartAction` phải validate:
  - token tồn tại;
  - token chưa hết hạn;
  - token thuộc đúng user;
  - token chưa được sử dụng;
  - payload hợp lệ.
- Malformed model output không được tạo pending token.
- Cart stub phải được `assert_not_called()` trong malformed-output test.

## 8. Fault injection

### Nguyên tắc

- Có thể bật từ bên ngoài container mà không cần sửa code hoặc rebuild image.
- Mặc định tắt.
- Chỉ bật khi có explicit test configuration.
- Không vô hiệu hóa cơ chế xử lý lỗi để làm test pass.
- Không trả raw injected blob cho người dùng.
- Có log rõ fault type nhưng không chứa secret.

### Fault modes tối thiểu

| Mode | Hành vi |
|---|---|
| `none` | Gọi provider bình thường |
| `timeout` | Giả lập provider timeout |
| `throttling` | Giả lập rate-limit/throttling |
| `server_error` | Giả lập provider 5xx |
| `malformed_json` | Trả JSON sai cú pháp |
| `schema_mismatch` | Trả JSON hợp lệ nhưng sai `ShoppingIntent` schema |

Fault mode có thể được điều khiển bằng environment variable hoặc test-only
header/metadata/feature flag. Nếu dùng environment variable, tài liệu phải nêu rõ
cần recreate container khi đổi mode. Nếu dùng flag động, phải bảo vệ để không bị
người dùng thông thường tùy ý bật.

### Sustained failure

Replay phải tạo đủ số lỗi để đạt breaker threshold, sau đó:

1. gửi thêm request khi breaker đang mở;
2. chứng minh provider fake không nhận request đó;
3. tắt fault;
4. chờ recovery interval dành cho replay;
5. gửi probe;
6. chứng minh breaker chuyển về `CLOSED`;
7. gửi request bình thường và nhận kết quả thành công.

Môi trường replay có thể dùng recovery interval ngắn hơn production thông qua
biến môi trường, nhưng không được thay đổi logic breaker.

## 9. Test bắt buộc

### Bedrock intent parsing

- Valid JSON tạo `ShoppingIntent`.
- Malformed JSON lần đầu, valid lần hai thì thành công.
- Malformed JSON mọi lần thì fallback.
- Schema mismatch mọi lần thì fallback.
- Sai kiểu `wants_add_to_cart` bị reject.
- Field thừa bị reject.
- Retry không vượt giới hạn.

### Downstream tool blocking

Trong cùng một test malformed output, phải xác nhận:

```python
catalog_stub.SearchProducts.assert_not_called()
reviews_stub.GetProductReviews.assert_not_called()
create_pending_token.assert_not_called()
cart_stub.AddItem.assert_not_called()
```

Nếu cart stub không nằm trực tiếp trong dependency của Search flow, phải kiểm tra
`ConfirmCartAction` không được gọi và không có pending token nào được tạo.

### Provider failure

- Timeout → `FALLBACK`, không exception.
- Throttling/5xx → retry có giới hạn rồi fallback.
- Breaker open → fallback nhanh và provider fake không được gọi.
- Provider recovery → request hoạt động lại.

### Deadline

- Fake provider block lâu hơn deadline.
- Request kết thúc trong thời gian tối đa được định nghĩa.
- Background operation không được chạy tool sau khi caller đã nhận timeout.

### Cart confirmation

- Token hợp lệ và đúng user chỉ ghi cart đúng một lần.
- Token sai user bị từ chối.
- Token hết hạn bị từ chối.
- Token malformed bị từ chối.
- Token dùng lại không ghi cart lần hai.

## 10. Replay và repro

Cung cấp một entry point duy nhất, ví dụ:

```powershell
python scripts/mandate25_replay.py --scenario provider-single
python scripts/mandate25_replay.py --scenario sustained-outage
python scripts/mandate25_replay.py --scenario malformed-output
```

Nếu script chạy bên trong container, cung cấp lệnh Docker Compose tương đương.

Mỗi scenario phải xuất kết quả machine-readable hoặc một bảng rõ ràng gồm:

- scenario;
- request count;
- response status;
- elapsed milliseconds;
- provider call count;
- retry count;
- breaker state trước/sau;
- downstream tool call count;
- PASS/FAIL.

### Scenario A — lỗi provider đơn

- Inject một lỗi timeout, throttling hoặc HTTP 5xx.
- Response không phải application 500.
- Status là `FALLBACK`.
- Reason cho biết đang tạm suy giảm.
- Ghi fallback latency.

### Scenario B — lỗi kéo dài và recovery

- Inject đủ lỗi liên tiếp để mở breaker.
- Chứng minh request tiếp theo không gọi provider.
- Tắt inject.
- Chờ recovery interval.
- Probe thành công.
- Chứng minh breaker `CLOSED` và request sau thành công.

### Scenario C — malformed output

- Inject một blob không khớp schema `ShoppingIntent`.
- Response là `FALLBACK`.
- Không crash.
- Provider attempts không vượt giới hạn.
- Catalog/review/cart tool call count bằng 0.

## 11. ADR

Tạo `docs/ai-engineering/ADR-AIE-25-controlled-degradation.md` với các nội dung:

- Context: phụ thuộc Bedrock và rủi ro timeout/output rác.
- Decision:
  - bounded retry;
  - timeout;
  - circuit breaker;
  - honest fallback;
  - Pydantic validation ở boundary;
  - pending-action pattern cho cart.
- Alternatives:
  - chỉ dùng SDK retry;
  - fallback model;
  - cache response;
  - queue request.
- Consequences:
  - độ trễ tối đa;
  - breaker state theo process;
  - không có cross-instance breaker;
  - fallback không tạo nội dung.
- Security/privacy:
  - không log prompt/output/credential;
  - tool arguments không được dùng trước validation.
- Người thực hiện và người review ký tên, ghi ngày.

## 12. Evidence

Tạo `docs/ai-engineering/AI_MANDATE_25_EVIDENCE.md` với các nội dung:

1. Tóm tắt kiến trúc.
2. Link ADR.
3. Link PR/commit.
4. Cấu hình timeout/retry/breaker.
5. Repro command.
6. Kết quả Scenario A, B và C.
7. Log breaker open.
8. Log request bị breaker từ chối.
9. Log half-open và recovery.
10. Log/schema rejection.
11. Bằng chứng tool call count bằng 0.
12. Fallback latency thực tế.
13. Test command và test summary.
14. Ảnh/log đính kèm Jira.
15. Tên hai người thực hiện và chữ ký review.

Không đưa AWS account ID, access key, secret, session token, raw prompt hoặc dữ
liệu người dùng vào evidence.

## 13. Definition of Done

Task hoàn thành khi:

- Shopping Copilot dùng reliability adapter của Task 1.
- Provider failure dẫn đến fallback có kiểm soát.
- Request không vượt deadline đã công bố.
- Malformed output bị Pydantic reject trước downstream nodes.
- Test chứng minh catalog/review/cart không chạy với output rác.
- Chuỗi lỗi mở breaker và request sau không gọi provider.
- Khi provider hoạt động trở lại, breaker tự phục hồi.
- Ba replay scenario chạy được từ bên ngoài.
- Có số đo fallback latency và provider/tool call count.
- ADR được hai người ký/review.
- Evidence chứa đủ repro, log, test result và link commit/PR.
- Nội dung sẵn sàng dán vào một Jira ticket `AI MANDATE #25`.

## 14. Phối hợp và tránh conflict

- Task 1 sở hữu `src/ai-common/techx_ai_common/bedrock.py`.
- Task 2 không sửa retry/breaker implementation nếu chưa thống nhất.
- Task 2 sở hữu Shopping Copilot tests, replay, ADR và evidence.
- Nếu cần thay đổi adapter interface, phải thống nhất trước khi merge.
- Merge Task 1 trước hoặc cung cấp commit/interface ổn định để Task 2 rebase.
- Cuối cùng, cả hai bên chạy replay trên cùng cấu hình Docker Compose và ký
  ADR/evidence.
