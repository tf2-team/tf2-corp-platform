# AI MANDATE #24 — LLM Observability

## Jira Metadata

| Field | Value |
|---|---|
| Summary | `AI MANDATE #24` |
| Labels | `ai-mandate`, `m24` |
| Priority | `High` |
| Assignee | Trần Quang Minh |
| Contributors | T-Sunm, hungxqt |

## 1. Outcome at a Glance

Shopping Copilot đã có một đường quan sát end-to-end cho tầng model. Mỗi request
AI trả về `x-trace-id`; từ ID đó, người kiểm tra có thể lấy trace và dựng lại
chuỗi frontend, gRPC, Copilot, retrieval, model và tool calls. Mỗi model-call
span ghi model/version, token vào/ra, estimated cost, latency, outcome và
user/session đã pseudonymize.

Trace không lưu prompt, response hoặc tool arguments thô. Request kiểm chứng có
email đánh dấu `pii-test@example.com` vẫn trả kết quả nghiệp vụ bình thường,
nhưng tìm toàn trace theo chuỗi này trả `0/0`. Một failure có kiểm soát cũng đã
được chạy qua đúng đường request thật: Bedrock trả `ValidationException`, hệ
thống ghi model error, tạo `app.ai.fallback` với `app.ai.outcome=fallback`, rồi
trả thông báo an toàn cho người dùng.

Grafana cung cấp view tổng hợp token, estimated cost và p95 latency theo model,
bề mặt và khoảng thời gian. Evidence trong tài liệu này đến từ runtime thật;
không có trace hoặc số liệu được tự tạo.

## 2. Why this Change Matters

Trước thay đổi này, muốn biết một request khách đã gọi model bao nhiêu lần, chậm
ở bước nào hoặc rơi vào fallback ở đâu thì phải ghép log thủ công. Cách đó không
đủ để debug một agent nhiều bước, kiểm soát chi phí hoặc chứng minh dữ liệu nhạy
cảm không bị nhân bản sang hệ thống observability.

Mandate này tạo ba khả năng vận hành:

1. **Reconstruct:** bắt đầu từ một request khách và đi lại toàn bộ model,
   retrieval và tool chain bằng một trace ID.
2. **Account:** tổng hợp token, cost và latency theo model và bề mặt mà không
   đọc từng log record.
3. **Audit safely:** giữ metadata cần cho debug nhưng không lưu raw prompt,
   response, tool arguments hoặc raw user/session ID.

## 3. Scope and Data Boundaries

### 3.1 Graded Surface

Bề mặt evidence chính là Shopping Copilot:

```text
POST /api/copilot
  → frontend
  → ShoppingCopilotService/Search
  → copilot_search
  → retrieval/model/tool spans
  → response + x-trace-id
```

Review Summary dùng cùng telemetry contract và xuất hiện trên aggregate
dashboard, nhưng không cần dùng để đạt sàn Mandate #24.

### 3.2 Trace Identity Contract

| Field | Contract |
|---|---|
| `trace_id` | 32 ký tự hex, lấy từ active OpenTelemetry span và trả qua header `x-trace-id`. |
| `user_id` | Không lưu raw value; trace chỉ giữ HMAC pseudonym khi telemetry secret được cấp. |
| `conversation_id` | Không lưu raw value; được pseudonymize riêng với namespace session. |
| Model/version | Ghi ở `gen_ai.request.model` và `gen_ai.response.model`. |
| Usage | Ghi ở `gen_ai.usage.input_tokens` và `gen_ai.usage.output_tokens` khi provider trả usage. |
| Cost | Chỉ ghi khi có usage và pricing version hợp lệ; thiếu dữ liệu không được biểu diễn sai thành cost `0`. |
| Latency/time | Lấy từ start time và duration của span. |
| Outcome | `app.ai.outcome=ok|error|fallback`; error span chỉ ghi loại lỗi an toàn. |
| Tool calls | Model span ghi số/tên tool allow-listed; mỗi tool execution có span riêng. |

### 3.3 Privacy Boundary

Telemetry áp dụng data minimization:

- Không ghi raw prompt, model response, tool arguments hoặc tool results.
- Không ghi raw user ID hoặc conversation ID.
- User và session được HMAC-SHA256 với namespace riêng.
- OpenTelemetry GenAI message-content capture mặc định là `false`.
- Trace error không ghi exception event chứa payload; chỉ ghi metadata lỗi cần
  cho vận hành.

Email `pii-test@example.com` được dùng như PII canary. Chuỗi này xuất hiện trong
request ở UI nhưng không xuất hiện trong trace tương ứng.

## 4. Design Summary

### 4.1 End-to-End Request Path

```mermaid
flowchart LR
    A[Customer request] --> B[Frontend API]
    B -->|x-trace-id| H[Customer response]
    B --> C[Shopping Copilot gRPC]
    C --> D[Retrieval and memory]
    D --> E[Model-call span]
    E --> F{Tool call?}
    F -- Yes --> G[Allow-listed tool span]
    G --> E
    F -- No --> H
    E -- Provider error --> I[app.ai.fallback]
    I --> H
    B -. trace ID .-> J[Jaeger fetch by ID]
    E -. span metrics .-> K[Prometheus and Grafana]
```

Frontend chỉ trả trace ID đang active; nó không tự sinh một ID rời khỏi
OpenTelemetry context. Fetch endpoint là read-only, chỉ nhận trace ID đúng định
dạng, đặt `Cache-Control: private, no-store`, timeout sau 5 giây và giới hạn
response ở 5 MiB.

### 4.2 Model-call Record

Shared helper `call_model()` là nguồn GenAI span có kiểm soát. Một successful
model call ghi:

- provider, requested model và response model;
- input/output tokens;
- estimated cost và pricing version;
- surface và workflow step;
- allow-listed tool names/count;
- pseudonym user/session;
- `app.ai.outcome=ok`.

Nếu provider ném lỗi, cùng span chuyển sang `app.ai.outcome=error`, ghi
`error.type` và giữ nguyên parent trace. Fallback ở cấp workflow tạo span
`app.ai.fallback` riêng với `app.ai.outcome=fallback`.

Botocore auto-instrumentation được tắt trên hai AI service để manual GenAI span
không bị nhân đôi. HTTP provider span vẫn có thể tồn tại bên dưới model span để
thể hiện network attempt; nó không được tính như một model-call record thứ hai.

### 4.3 Retrieval and Tool Spans

Copilot tạo `copilot_search` làm workflow span. Các bước retrieval và tool
execution nằm dưới cùng request trace. Tool span chỉ lưu tên tool đã allow-list
và outcome; raw arguments/results không được đưa vào attributes.

### 4.4 Aggregate View

Application phát token và cost counters với labels cardinality thấp:
`surface`, `provider`, `model`, `token_type` và `pricing_version`. Collector
`spanmetrics` tổng hợp call count và duration theo:

- `app.ai.surface`;
- `gen_ai.provider.name`;
- `gen_ai.request.model`;
- `gen_ai.operation.name`;
- `app.ai.outcome`.

Grafana dashboard hiển thị Tokens, Cost, P95 Latency, Error Rate và Fallback
Rate theo time window.

## 5. Replay and Reproduction

### 5.1 Starting Conditions

- Docker stack hoặc mentor environment đã chạy.
- Shopping Copilot dùng model/provider thật.
- `AI_TELEMETRY_HMAC_SECRET` đã được cấp.
- Truy cập storefront, Jaeger và Grafana qua cùng frontend proxy.

Local entry points:

```text
Storefront: http://localhost:8080
Jaeger:     http://localhost:8080/jaeger/ui/
Grafana:    http://localhost:8080/grafana/
```

### 5.2 Replay and Fetch Trace by ID

Lệnh dưới đây gửi request từ ngoài, lấy trace ID từ response và fetch đúng trace
vừa tạo:

```powershell
$baseUrl = "http://localhost:8080"
$marker = "pii-test@example.com"
$conversationId = [guid]::NewGuid().ToString()
$turnId = [guid]::NewGuid().ToString()

$body = @{
  user_message = "Find me all products under `$100. Contact email: $marker"
  user_id = "mentor-user-24"
  conversation_id = $conversationId
  turn_id = $turnId
} | ConvertTo-Json

$response = Invoke-WebRequest `
  -Method Post `
  -Uri "$baseUrl/api/copilot" `
  -ContentType "application/json" `
  -Body $body

$traceId = [string]$response.Headers["x-trace-id"]
$trace = Invoke-RestMethod "$baseUrl/api/ai-traces/$traceId"

$traceId
$response.Content
```

Expected observable results:

- Response có `x-trace-id` gồm 32 ký tự hex.
- Fetch endpoint trả trace có cùng ID.
- Trace chứa frontend, Shopping Copilot và model-call spans.
- Successful model span có model/version, token, cost, duration, outcome và
  user/session pseudonym.

Runtime check ngày `31/07/2026` gọi
`GET /api/ai-traces/2407e2afa5c0614c5fe6d2889ab2599c`, nhận HTTP `200` và
đúng một trace có `traceID=2407e2afa5c0614c5fe6d2889ab2599c`.

### 5.3 PII Negative Check

```powershell
$serializedTrace = $trace | ConvertTo-Json -Depth 100

if ($serializedTrace.Contains($marker)) {
  throw "FAIL: raw PII marker appeared in trace"
}

"PASS: raw PII marker is absent from trace $traceId"
```

Request dùng cho evidence vừa là một yêu cầu nghiệp vụ bình thường, vừa chứa PII
canary. Vì vậy cùng trace chứng minh response vẫn hoạt động end-to-end và raw PII
không được lưu. Khi chấm, mentor có thể gửi request thường và request PII thành
hai lượt riêng qua cùng contract mà không cần thay đổi implementation.

### 5.4 Controlled Error/Fallback

Để tạo lỗi provider thật nhưng có kiểm soát, tạm thời dùng một model version
không tồn tại rồi recreate riêng Shopping Copilot:

```powershell
$env:LLM_PROVIDER = "bedrock"
$env:BEDROCK_MODEL_ID = "us.amazon.nova-2-lite-v1:999"

docker compose --env-file .env --env-file .env.override `
  up -d --no-deps --force-recreate shopping-copilot
```

Gửi một request mới để tránh cache:

```text
find products under $123.45
```

Expected observable results:

- UI trả `Assistant Temporarily Unavailable`.
- HTTP response vẫn an toàn và có `x-trace-id`.
- Provider attempt trả `ValidationException`.
- Trace có error model call và span `app.ai.fallback`.
- Fallback span ghi `app.ai.outcome=fallback` và `app.ai.surface=copilot`.

Khôi phục cấu hình sau khi capture:

```powershell
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
Remove-Item Env:BEDROCK_MODEL_ID -ErrorAction SilentlyContinue

docker compose --env-file .env --env-file .env.override `
  up -d --no-deps --force-recreate shopping-copilot
```

## 6. Runtime Evidence

### Scenario A — External Replay Returns a Trace ID

**Objective:** chứng minh người kiểm tra có thể bơm request từ ngoài và nhận
trace ID của chính request đó.

**Observed result:** request
`Find me all product under $100. Contact email: pii-test@example.com.` trả danh
sách sản phẩm thành công. Network response có
`x-trace-id=e954485a0f0ac99ff9096de100ae7623`.

![Successful Copilot replay returns x-trace-id](AI_MANDATE_24_01_REPLAY_AND_TRACE_ID.jpeg)

*Request nghiệp vụ có PII canary được gửi qua `POST /api/copilot`, trả HTTP 200,
kết quả sản phẩm và trace ID 32 ký tự. Request headers nhạy cảm được thu gọn,
không đưa cookie hoặc authorization token vào evidence.*

### Scenario B — Full Model Record and PII Protection

**Objective:** dựng lại request theo trace ID, kiểm tra các trường lõi và xác
nhận PII canary không xuất hiện.

**Observed result:** trace
`e954485a0f0ac99ff9096de100ae7623` có 4 services, depth 12 và 18 spans. Model
span `chat us.amazon.nova-2-lite-v1:0` thể hiện:

- `gen_ai.provider.name=aws.bedrock`;
- request/response model `us.amazon.nova-2-lite-v1:0`;
- input tokens `2189`, output tokens `64`;
- non-zero estimated cost và pricing version;
- duration khoảng `1.01 s`;
- `app.ai.outcome=ok`;
- `app.ai.surface=copilot`;
- user và session pseudonym;
- `app.ai.telemetry_complete=true`.

Jaeger search toàn trace theo `pii-test@example.com` trả `0/0`.

![Full model-call trace and PII negative search](AI_MANDATE_24_02_FULL_TRACE_AND_PII_PROTECTION.jpeg)

*Cùng trace ID từ Scenario A nối request đến model span đủ trường lõi. Email
đánh dấu xuất hiện ở request nhưng không xuất hiện trong trace; user/session chỉ
còn pseudonym.*

### Scenario C — Aggregate Token, Cost and Latency View

**Objective:** chứng minh telemetry được tổng hợp theo model, surface và time
window mà không đọc log thô.

**Observed result:** dashboard `LLM Observability` hiển thị token input/output,
estimated cost và p95 latency cho `copilot` và `summary`; time range được hiển
thị trực tiếp trên ảnh.

![LLM aggregate dashboard](AI_MANDATE_24_03_AGGREGATE_VIEW.png)

*Grafana tổng hợp token, estimated cost và p95 latency theo model và AI surface.
Dashboard cũng có panel Error Rate và Fallback Rate cho vận hành.*

### Scenario D — Controlled Provider Error Produces a Traceable Fallback

**Objective:** chứng minh một provider failure thật được ghi trong cùng trace và
được chuyển thành fallback an toàn.

**Observed result:** trace
`2407e2afa5c0614c5fe6d2889ab2599c` đi từ frontend đến Shopping Copilot. Bedrock
trả HTTP 400 do model version kiểm thử không hợp lệ. Trace chứa error model
attempt và span `app.ai.fallback` với:

- `app.ai.outcome=fallback`;
- `app.ai.surface=copilot`;
- reason là `ValidationException`;
- fallback span nằm trong cùng request trace.

![Controlled provider error and fallback span](AI_MANDATE_24_04_ERROR_FALLBACK_TRACE.png)

*Failure được trigger qua request path thật, không tạo trace giả. Copilot ghi
provider error, tạo `app.ai.fallback` và trả thông báo an toàn cho người dùng.*

## 7. Requirement-to-Evidence Matrix

| Directive requirement | Implementation | Runtime evidence | Status |
|---|---|---|---|
| Mỗi model call có model/version, token, cost, latency, outcome và identity an toàn | [`call_model()`](../../../src/ai-common/techx_ai_common/observability.py#L159-L240) | Scenario B | **PASS** |
| Một trace ID nối request, model, retrieval và tool chain | [`copilot_search`](../../../src/shopping-copilot/copilot_server.py#L60-L80), [`execute_tool`](../../../src/shopping-copilot/react_agent.py#L167-L177) | Scenario B | **PASS** |
| Request ngoài trả trace ID | [`x-trace-id` middleware](../../../src/frontend/utils/telemetry/InstrumentationMiddleware.ts#L21-L41) | Scenario A | **PASS** |
| Fetch trace theo ID | [Read-only Jaeger proxy](<../../../src/frontend/pages/api/ai-traces/[traceId]/index.ts#L19>) | Repro và runtime check mục 5.2 | **PASS** |
| Cost/token/latency tổng hợp theo model/surface/time | [Collector dimensions](../../../src/otel-collector/otelcol-config.yml#L178-L185), [Grafana dashboard](../../../src/grafana/provisioning/dashboards/demo/llm-observability-dashboard.json#L18) | Scenario C | **PASS** |
| Raw PII/secret không xuất hiện trong trace | [`pseudonymize()`](../../../src/ai-common/techx_ai_common/observability.py#L61-L71), content capture disabled in [`docker-compose.yml`](../../../docker-compose.yml#L638) | Scenario A–B | **PASS** |
| Error/fallback được trace | [`record_fallback()`](../../../src/ai-common/techx_ai_common/observability.py#L265-L277) | Scenario D | **PASS** |
| Tracing không nhân đôi model-call record | Botocore auto-instrumentation disabled in [`docker-compose.yml`](../../../docker-compose.yml#L637) | Scenario B phân biệt manual model span và HTTP child span | **PASS** |

Instrumentation chỉ thêm in-process span attributes, HMAC và counters quanh
provider call; không thêm một synchronous remote dependency vào đường chính.
OTLP export do OpenTelemetry pipeline xử lý ngoài model invocation.

## 8. Decisions, Ownership, and References

**Implementation commits:**

- [`881b3dc`](https://github.com/tf2-team/tf2-corp-platform/commit/881b3dc50bd90a3c9073301e9ee9dc55b1a4b625) — end-to-end LLM observability.
- [`84e6d03`](https://github.com/tf2-team/tf2-corp-platform/commit/84e6d0362d3b7208c756cdd878ce50815c95fe4b) — GenAI telemetry and private trace proxy.
- [`5a2e97a`](https://github.com/tf2-team/tf2-corp-platform/commit/5a2e97a1c4ef6798e160fc4de07bb7fb916e5179) — integration with the current observability path.

**Implementation contributors:** T-Sunm, hungxqt

**Design owner:** Trần Quang Minh

**Reviewer/sign-off date:** `[REVIEWER — ký tên và ngày thực tế]`

### 8.1 ADR Record and Sign-off

| Decision | Status | Sign-off |
|---|---|---|
| Dùng OpenTelemetry manual wrapper làm GenAI model-call record; tắt botocore auto-instrumentation để không nhân đôi token, cost và call count. | `Accepted` | Trần Quang Minh, 31/07/2026 |
| Giữ một trace ID xuyên frontend, gRPC, Copilot, retrieval, model và tool; trả ID đó qua `x-trace-id` và cung cấp fetch endpoint read-only. | `Accepted` | Trần Quang Minh, 31/07/2026 |
| Không lưu raw prompt/response/tool payload; user và session được HMAC với namespace riêng trước khi đưa vào trace. | `Accepted` | Trần Quang Minh, 31/07/2026 |
| Cost chỉ được ghi khi có token usage và pricing version hợp lệ; aggregate labels phải có cardinality thấp. | `Accepted` | Trần Quang Minh, 31/07/2026 |
| Provider error và workflow fallback là hai observability events riêng nhưng cùng parent trace; fallback phải trả response an toàn cho user. | `Accepted` | Trần Quang Minh, 31/07/2026 |

### 8.2 Technical References

- [Directive #24](MANDATE-24-llm-observability.md)
- [Implementation tutorial plan](llm-observability-implementation-tutorial-plan.md)
- [Runtime remediation plan](llm-observability-remediation-plan.md)
- [Implementation change record](../../changes/2026-07-29-integrate-llm-observability.md)
- [Shared model telemetry](../../../src/ai-common/techx_ai_common/observability.py)
- [LLM Observability dashboard](../../../src/grafana/provisioning/dashboards/demo/llm-observability-dashboard.json)

## 9. Jira Evidence Comment

Paste the following concise summary into the Jira comment:

> **Implementation:** commits
> [`881b3dc`](https://github.com/tf2-team/tf2-corp-platform/commit/881b3dc50bd90a3c9073301e9ee9dc55b1a4b625),
> [`84e6d03`](https://github.com/tf2-team/tf2-corp-platform/commit/84e6d0362d3b7208c756cdd878ce50815c95fe4b)
> và
> [`5a2e97a`](https://github.com/tf2-team/tf2-corp-platform/commit/5a2e97a1c4ef6798e160fc4de07bb7fb916e5179).
>
> **Replay/fetch:** `POST /api/copilot` trả `x-trace-id`; fetch bằng
> `GET /api/ai-traces/{traceId}`. Repro đầy đủ nằm tại mục 5.
>
> **Runtime evidence:** successful trace
> `e954485a0f0ac99ff9096de100ae7623` đủ model/version, token, cost,
> latency, outcome và user/session pseudonym; PII canary
> `pii-test@example.com` không xuất hiện trong trace. Controlled failure
> trace `2407e2afa5c0614c5fe6d2889ab2599c` ghi
> `app.ai.outcome=fallback`. Grafana tổng hợp token, cost và p95 latency
> theo model/surface/time.
>
> **ADR:** quyết định và sign-off nằm tại mục 8.1 của tài liệu này.
