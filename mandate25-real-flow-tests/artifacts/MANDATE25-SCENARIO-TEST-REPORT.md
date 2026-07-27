# MANDATE25 — Báo cáo kiểm thử real-flow

## 1. Tóm tắt

Báo cáo tổng hợp bốn lần chạy mới nhất trong `mandate25-real-flow-tests/artifacts`. Runner gửi request gRPC thật đến hai service chạy bằng Docker Compose:

- Product Reviews: `ProductReviewService.AskProductAIAssistant`.
- Shopping Copilot: `ShoppingCopilotService.Search`.

Runner không dùng mock, Prometheus, Jaeger, trace hoặc metric làm điều kiện PASS. Bằng chứng gồm response gRPC, thời gian phản hồi, container ID và log circuit breaker.

Product được dùng trong tất cả scenario:

```text
product_id:   0PUK6V6EV0
product_name: Solar System Color Imager
```

Kết quả tổng hợp:

| Scenario | Product Reviews | Shopping Copilot | Kết luận |
|---|---:|---:|---|
| Một lỗi provider đơn | PASS | PASS | PASS |
| Chuỗi lỗi kéo dài/circuit breaker | PASS | PASS | PASS |
| Recovery với fault mode `none` | FAIL | PASS | FAIL một phần |
| Model trả JSON hỏng | PASS | PASS | PASS |

Tổng cộng có 7/8 kết quả bề mặt-scenario đạt yêu cầu. Product Reviews chưa đạt recovery vì Bedrock trả output không hợp lệ theo contract.

## 2. Chuẩn bị và cách chạy

Mở PowerShell tại thư mục gốc:

```powershell
cd D:\Xbrain_BT\tf2-corp-platform
```

Chạy một lỗi provider đơn:

```powershell
python mandate25-real-flow-tests\e2e_runner.py --scenario provider-failure
```

Chạy chuỗi lỗi kéo dài để mở circuit breaker:

```powershell
python mandate25-real-flow-tests\e2e_runner.py --scenario sustained-outage
```

Chạy recovery với Bedrock bình thường:

```powershell
python mandate25-real-flow-tests\e2e_runner.py --scenario recovery
```

Chạy model output hỏng:

```powershell
python mandate25-real-flow-tests\e2e_runner.py --scenario malformed-output
```

Chạy toàn bộ:

```powershell
python mandate25-real-flow-tests\e2e_runner.py --scenario all
```

Có thể chỉ định fault mode:

```powershell
python mandate25-real-flow-tests\e2e_runner.py `
  --scenario provider-failure `
  --fault-mode throttling
```

Mỗi lần chạy, runner recreate hai service với fault mode tương ứng, tìm product thật trong catalog, gửi request gRPC và ghi `summary.json` cùng `summary.md` vào thư mục mang run ID.

## 3. Input chung

### Product Reviews

RPC:

```text
ProductReviewService.AskProductAIAssistant
```

Input nghiệp vụ:

```json
{
  "product_id": "0PUK6V6EV0",
  "question": "What do customers say about quality and reliability?"
}
```

Runner truyền `x-session-id` trong gRPC metadata. Với sustained outage, mỗi logical request dùng session khác nhau để không bị cooldown 2 giây chặn trước Bedrock adapter.

### Shopping Copilot

RPC:

```text
ShoppingCopilotService.Search
```

Input nghiệp vụ:

```json
{
  "user_message": "Find Solar System Color Imager",
  "user_id": "mandate25-e2e-user"
}
```

Với sustained outage, mỗi logical request dùng user ID khác nhau. Circuit breaker vẫn được giữ chung vì breaker được quản lý theo model và region trong cùng process, không theo user.

## 4. Scenario 1 — Một lỗi provider đơn

### Mục tiêu

Kiểm tra một lỗi timeout từ Bedrock không làm gục service. Hai chatbot phải trả đường lui an toàn.

### Cấu hình

```text
BEDROCK_FAULT_MODE=timeout
BEDROCK_MAX_ATTEMPTS=3
BEDROCK_TOTAL_DEADLINE_SECONDS=14
AI_CACHE_ENABLED=false
```

### Diễn biến

1. Runner recreate hai service với fault `timeout`.
2. Runner gửi một request đến Product Reviews.
3. Runner gửi một request đến Shopping Copilot.
4. Bedrock adapter phát sinh lỗi timeout có kiểm soát.
5. Hai service xử lý lỗi và trả response gRPC thay vì làm RPC thất bại.

### Output thực tế

Run ID: `20260727T013742Z`

Product Reviews:

```json
{
  "status": "FALLBACK",
  "reason": "LLM or dependency error: BedrockUnavailableError",
  "claims": 0,
  "claim_source_ids": [],
  "elapsed_ms": 10797.0,
  "checks": {
    "fallback": true,
    "safe_reason": true
  },
  "pass": true
}
```

Shopping Copilot:

```json
{
  "status": "FALLBACK",
  "reason": "Shopping assistance is temporarily unavailable. Please try again shortly.",
  "products": 0,
  "product_ids": [],
  "claims": 0,
  "pending_action_token": "",
  "elapsed_ms": 2516.0,
  "checks": {
    "fallback": true,
    "safe_reason": true
  },
  "pass": true
}
```

### Kết luận

PASS cho cả hai chatbot. Hệ không gục, trả fallback an toàn và không tạo product, claim hoặc pending action từ request lỗi.

Artifact: `artifacts/20260727T013742Z/summary.json`.

## 5. Scenario 2 — Chuỗi lỗi kéo dài và circuit breaker

### Mục tiêu

Kiểm tra chuỗi lỗi timeout làm circuit breaker mở. Request sau phải bị breaker từ chối nhanh và nhận fallback.

### Cấu hình

```text
BEDROCK_FAULT_MODE=timeout
BEDROCK_BREAKER_FAILURE_THRESHOLD=3
BEDROCK_BREAKER_RECOVERY_SECONDS=2
```

### Diễn biến

1. Runner giữ mỗi service trong cùng container suốt scenario.
2. Runner gửi ba logical request lỗi cho mỗi chatbot.
3. Mỗi request dùng user/session riêng để vượt qua cooldown nhưng vẫn đi vào cùng breaker.
4. Runner gửi request thứ tư.
5. Runner kiểm tra response thứ tư và các log `bedrock_breaker_opened`, `bedrock_breaker_rejected`.

### Output thực tế

Run ID: `20260727T014409Z`

Product Reviews:

```json
{
  "status": "FALLBACK",
  "reason": "LLM or dependency error: CircuitBreakerOpenError",
  "elapsed_ms": 1625.0,
  "checks": {
    "breaker_opened": true,
    "breaker_rejected": true,
    "fallback": true
  },
  "pass": true
}
```

Shopping Copilot:

```json
{
  "status": "FALLBACK",
  "reason": "Shopping assistance is temporarily unavailable. Please try again shortly.",
  "products": 0,
  "pending_action_token": "",
  "elapsed_ms": 250.0,
  "checks": {
    "breaker_opened": true,
    "breaker_rejected": true,
    "fallback": true
  },
  "pass": true
}
```

### Kết luận

PASS cho cả hai chatbot. Log chứng minh breaker đã mở và từ chối request. Request cuối trả nhanh hơn vì không tiếp tục gọi provider.

Artifact: `artifacts/20260727T014409Z/summary.json`.

## 6. Scenario 3 — Recovery

### Mục tiêu

Đưa fault mode về `none`, gọi lại Bedrock và yêu cầu hai chatbot trả response bình thường thay vì fallback.

### Cấu hình

```text
BEDROCK_FAULT_MODE=none
LLM_PROVIDER=bedrock
AI_CACHE_ENABLED=false
```

### Diễn biến

1. Runner recreate hai service với fault mode `none`.
2. Runner gửi request Product Reviews.
3. Runner gửi request Shopping Copilot.
4. Runner yêu cầu status thuộc `GROUNDED` hoặc `ABSTAINED` và không phải `FALLBACK`.

### Output thực tế

Run ID: `20260727T015208Z`

Product Reviews:

```json
{
  "status": "FALLBACK",
  "reason": "LLM or dependency error: InvalidModelOutputError",
  "claims": 0,
  "elapsed_ms": 13813.0,
  "checks": {
    "not_fallback": false,
    "recovery_response": false,
    "safe_reason": true
  },
  "pass": false
}
```

Shopping Copilot:

```json
{
  "status": "GROUNDED",
  "reason": "",
  "products": 1,
  "product_ids": [
    "0PUK6V6EV0"
  ],
  "pending_action_token": "",
  "elapsed_ms": 4203.0,
  "checks": {
    "not_fallback": true,
    "recovery_response": true,
    "safe_reason": true
  },
  "pass": true
}
```

### Kết luận

Shopping Copilot PASS và trả đúng product thật. Product Reviews FAIL vì model output không đạt contract, dẫn đến `InvalidModelOutputError`. Product Reviews vẫn giữ an toàn bằng fallback và không trả claim rác.

Scenario hiện chứng minh recovery sau khi recreate container với fault mode `none`. Nó chưa chứng minh circuit breaker tự chuyển `OPEN → HALF_OPEN → CLOSED` trong cùng PID vì fault mode của service chỉ được đọc khi process khởi động.

Artifact: `artifacts/20260727T015208Z/summary.json`.

## 7. Scenario 4 — Model output hỏng

### Mục tiêu

Kiểm tra model trả malformed JSON. Service phải chặn output trước khi tạo dữ liệu nghiệp vụ hoặc tool-call arguments.

### Cấu hình

```text
BEDROCK_FAULT_MODE=malformed_json
BEDROCK_SCHEMA_MAX_ATTEMPTS=2
```

### Diễn biến

1. Runner recreate hai service với fault `malformed_json`.
2. Bedrock adapter trả chuỗi JSON hỏng.
3. Product Reviews phải trả fallback, không trả claim/source.
4. Shopping Copilot phải trả fallback trước downstream tool path.
5. Runner xác nhận Copilot không trả product và không tạo pending action token.

### Output thực tế

Run ID: `20260727T015440Z`

Product Reviews:

```json
{
  "status": "FALLBACK",
  "reason": "LLM or dependency error: InvalidModelOutputError",
  "claims": 0,
  "claim_source_ids": [],
  "elapsed_ms": 10234.0,
  "checks": {
    "fallback": true,
    "no_tool_args_executed": true,
    "safe_reason": true
  },
  "pass": true
}
```

Shopping Copilot:

```json
{
  "status": "FALLBACK",
  "reason": "Shopping assistance is temporarily unavailable. Please try again shortly.",
  "products": 0,
  "product_ids": [],
  "claims": 0,
  "pending_action_token": "",
  "elapsed_ms": 1562.0,
  "checks": {
    "fallback": true,
    "no_tool_args_executed": true,
    "safe_reason": true
  },
  "pass": true
}
```

### Kết luận

PASS cho cả hai chatbot. Output hỏng bị chặn, hệ không gục và trả fallback. Shopping Copilot không tạo product hoặc pending token, nên không chuyển args rác sang Cart tool.

Artifact: `artifacts/20260727T015440Z/summary.json`.
