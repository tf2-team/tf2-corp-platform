# Kế hoạch tutorial triển khai LLM Observability

## 1. Mục tiêu

Tài liệu này lập kế hoạch cho năm tutorial triển khai
[Mandate 24](./MANDATE-24-llm-observability.md) trên:

- Product Review Summary trong `src/product-reviews`.
- Shopping Copilot trong `src/shopping-copilot`.

Sau khi hoàn thành, hệ thống phải:

1. Tạo một span cho mỗi lần gọi model.
2. Dựng lại được model, retrieval và tool calls của một request bằng cùng một
   trace ID.
3. Tổng hợp được token, chi phí và độ trễ theo model, bề mặt và thời gian.
4. Không lưu prompt, PII, secret hoặc tool payload thô trong telemetry.
5. Có cửa replay trả trace ID và cửa fetch trace theo ID.
6. Có một aggregate view tối thiểu để AIOps và mentor sử dụng.

Đây là kế hoạch triển khai chức năng và tutorial. Chưa lập kế hoạch cho report,
ảnh evidence, Jira submission, alerting, auto-remediation hoặc ADR.

## 2. Phạm vi trách nhiệm

```text
Product Review / Shopping Copilot
              |
              | OTLP gRPC
              v
      OpenTelemetry Collector
       |            |             |
       | traces     | metrics     | logs
       v            v             v
     Jaeger      Prometheus    OpenSearch
       |            |
       +------------+
              |
        Grafana / AIOps
```

AI Engineering chịu trách nhiệm:

- Instrument model, retrieval và tool calls.
- Phát telemetry an toàn qua OTLP.
- Cung cấp replay entry và fetch-trace entry.
- Kiểm chứng dữ liệu trong Jaeger, Prometheus, OpenSearch và Grafana.

Không cần chạy AIOps runtime trong lần triển khai này. AIOps là consumer của
telemetry sau khi contract đã ổn định.

## 3. Hiện trạng và khoảng trống

### 3.1. Phần có thể tái sử dụng

- Hai AI service đã chạy bằng `opentelemetry-instrument`.
- OTel Collector đã nhận OTLP và route:
  - Trace sang Jaeger.
  - Metrics sang Prometheus.
  - Logs sang OpenSearch.
- Collector đã có `spanmetrics`.
- Frontend đã dùng `@opentelemetry/api`.
- AIOps đã có client cho Jaeger, Prometheus và OpenSearch.
- Production Helm values đã tắt GenAI message-content capture.

### 3.2. Khoảng trống cần xử lý

- Chưa có span cho từng lần gọi Bedrock/OpenAI.
- Shared Bedrock adapter đang bỏ qua response usage.
- Copilot ReAct loop gọi model trực tiếp.
- Chưa có token và cost metrics.
- `spanmetrics` chưa có dimensions cho model/surface/outcome.
- Chưa có safe retrieval/tool spans.
- User/session chưa được pseudonymize nhất quán.
- Local Docker Compose vẫn bật message-content capture.
- Product Review vẫn ghi nội dung câu hỏi đã sanitize vào span/log.
- External API chưa trả trace ID.
- Chưa có cửa fetch trace theo ID.
- Chưa có aggregate view dành cho LLM.

### 3.3. Model-call inventory

| Bề mặt | Vị trí | Call |
|---|---|---|
| Summary | `techx_ai_common/bedrock.py` | Bedrock Converse |
| Summary | `techx_ai_common/grounding.py` | OpenAI-compatible |
| Summary | `product_reviews_server.py` | Tool selection/final answer |
| Copilot | `react_agent.py` | ReAct rounds |
| Copilot | `memory_retrieval.py` | Retrieval hint |
| Copilot | `memory_extractor.py` | Memory extraction |
| Copilot | `bedrock_grounding.py` | Review-grounded answer |

Eval runners không thuộc runtime instrumentation scope.

## 4. Telemetry contract tối thiểu

Ưu tiên OpenTelemetry GenAI semantic conventions. Chỉ tạo custom attributes
cho dữ liệu riêng của project.

### 4.1. Model-call span

Span name theo format:

```text
{gen_ai.operation.name} {gen_ai.request.model}
```

Ví dụ: `chat anthropic.claude-3-haiku`.

| Attribute | Quy tắc |
|---|---|
| `gen_ai.operation.name` | Dùng operation chuẩn như `chat` |
| `gen_ai.provider.name` | `aws.bedrock` hoặc provider thực tế |
| `gen_ai.request.model` | Model ID được gửi |
| `gen_ai.response.model` | Model/version provider trả về hoặc fallback xác định bên dưới |
| `gen_ai.usage.input_tokens` | Chỉ ghi khi provider trả usage |
| `gen_ai.usage.output_tokens` | Chỉ ghi khi provider trả usage |
| `error.type` | Exception class an toàn |
| `app.ai.surface` | `summary` hoặc `copilot` |
| `app.ai.workflow_step` | Ví dụ `grounded_summary`, `react_round` |
| `app.ai.outcome` | `ok`, `error` hoặc `fallback` |
| `app.ai.estimated_cost_usd` | Chỉ ghi khi có usage và pricing |
| `app.ai.pricing_version` | Bắt buộc khi có estimated cost |
| `app.ai.tool_call_count` | Chỉ số lượng |
| `app.ai.tool_names` | Chỉ tên tool trong allow-list |
| `app.ai.user_pseudonym` | HMAC; không dùng làm metric label |
| `app.ai.session_pseudonym` | HMAC; không dùng làm metric label |

Timestamp, duration, trace ID, span ID và parent/child relationship do OTel SDK
quản lý.

### 4.2. Quy tắc model version

Để trường model/version không bị thiếu:

1. Ưu tiên model/version trong response.
2. Nếu provider không trả, dùng immutable model ID hoặc deployment version trong
   config đã gửi request.
3. Nếu cả hai đều không có, ghi `unknown` và
   `app.ai.telemetry_complete=false`.
4. Không suy đoán version từ tên marketing.

`unknown` chỉ phục vụ chẩn đoán và không được tính là đạt Mandate floor. Model
được dùng trong normal/fallback checks phải có version xác định từ response
hoặc deployment config.

### 4.3. Outcome và fallback

- Provider attempt thành công: `ok`.
- Provider attempt ném lỗi: `error`.
- Secondary model call được gọi vì primary call lỗi: secondary call ghi
  `fallback`.
- Nếu hệ thống trả static fallback mà không gọi model lần nữa:
  - Failed model call vẫn là `error`.
  - Request span ghi `fallback`.
  - Tạo child span `app.ai.fallback` với reason class an toàn.

Không sửa lại failed model call thành `fallback` sau khi span đã đóng.

### 4.4. Privacy

Không ghi:

- Prompt, system prompt hoặc response thô.
- Tool arguments hoặc tool result thô.
- Review text hoặc username.
- Raw user/session/conversation/turn ID.
- Authorization, API key hoặc pending-cart token.
- Exception message có thể chứa payload.

Pseudonym:

```text
HMAC-SHA256(AI_TELEMETRY_HMAC_SECRET, namespace + ":" + raw_id)
```

Production không có default secret. User và session dùng namespace riêng.
Telemetry phải an toàn trước khi gọi `span.set_attribute()` hoặc `logger.*()`;
Collector không phải lớp masking chính.

### 4.5. Metrics

Tái sử dụng `spanmetrics` cho:

- Model-call count.
- Model-call latency.

Thêm dimensions cardinality thấp:

- `app.ai.surface`
- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.operation.name`
- `app.ai.outcome`

Application chỉ phát thêm:

| Instrument | Loại | Labels |
|---|---|---|
| `app_ai_model_tokens` | Counter | surface, provider, model, token type |
| `app_ai_model_cost_usd` | Counter | surface, provider, model, pricing version |

Không tạo application counter/histogram khác cho call count hoặc latency.
Không đưa trace ID, pseudonym, product ID, conversation ID hoặc error message
vào metric labels.

Pricing table nhỏ được đặt cùng shared observability helper cho đến khi có nhu
cầu độc lập thật sự. Bảng giá phải có version/effective date. Thiếu usage hoặc
pricing trả `None`, không trả `0`.

### 4.6. Retrieval và tool spans

| Span | Safe attributes |
|---|---|
| `retrieval {source}` | surface, source, result count, outcome |
| `execute_tool {tool_name}` | surface, allow-listed tool name, outcome |
| `app.ai.fallback` | surface, reason class |

Không phát `app_ai_tool_calls` metric trong lần này. Tool spans đã đủ để dựng
lại request; chỉ thêm metric khi AIOps có use case tổng hợp cụ thể.

## 5. Chuỗi năm tutorial

Mỗi tutorial gồm mục tiêu, file tác động, thay đổi nhỏ nhất, code mẫu, một check
chạy được và lỗi thường gặp.

### Tutorial 1 — Contract, privacy và shared helper

**Mục tiêu:** tạo một đường instrumentation dùng chung, không tạo framework.

File chính:

- `src/ai-common/techx_ai_common/observability.py`
- Một test file cho helper.
- `docker-compose.yml`.

Các bước:

1. Tạo helper mở model-call span và ghi safe attributes.
2. Extract usage cho Bedrock và OpenAI-compatible response.
3. Implement HMAC pseudonym.
4. Đặt versioned pricing table nhỏ trong cùng module.
5. Phát token/cost counters.
6. Đặt `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` làm mặc định
   ở local; chỉ cho phép override tạm bằng dữ liệu giả để kiểm tra Mandate 6.
7. Xóa span/log chứa sanitized question hoặc tool payload.
8. Test success, error, fallback, missing usage, unknown model và PII canary.

**Check:** `PII-TOKEN-XYZ` và secret giả không xuất hiện trong captured
attributes, events hoặc logs.

### Tutorial 2 — Product Review Summary vertical slice

**Mục tiêu:** đạt sàn Mandate 24 trên một bề mặt trước khi mở rộng.

File chính:

- `src/ai-common/techx_ai_common/bedrock.py`
- `src/ai-common/techx_ai_common/grounding.py`
- `src/product-reviews/product_reviews_server.py`

Các bước:

1. Instrument từng `client.converse()`/OpenAI call bằng shared helper.
2. Giữ nguyên response nghiệp vụ.
3. Truyền surface, workflow step và pseudonym qua tham số rõ ràng.
4. Tạo retrieval span quanh review retrieval/ranking.
5. Tạo tool spans cho `fetch_product_reviews` và `fetch_product_info`.
6. Bảo đảm retry tạo span riêng nhưng giữ cùng parent trace.
7. Thêm dimensions cho Collector `spanmetrics`.

**Check:** một Summary request tạo được request span, model-call spans,
retrieval/tool spans, usage và cost trong cùng trace.

### Tutorial 3 — Replay, fetch trace và aggregate view

**Mục tiêu:** mentor hoặc AIOps có thể gửi request, lấy trace ID, fetch trace và
xem dữ liệu tổng hợp mà không chạy AIOps runtime.

#### Replay entry

Tái sử dụng external API hiện có:

- `src/frontend/pages/api/product-ask-ai-assistant/[productId]/index.ts`

Response trả header `x-trace-id` lấy từ active valid span context. Không tự sinh
trace ID ngoài OTel.

#### Fetch-trace entry

Ưu tiên thấp nhất theo thứ tự:

1. Nếu Jaeger query API đã được expose an toàn, dùng trực tiếp
   `GET /api/traces/{trace_id}` và chỉ document URL.
2. Nếu Jaeger không thể expose, thêm một thin read-only proxy:
   `GET /api/ai-traces/{trace_id}`.

Proxy chỉ:

- Chấp nhận trace ID 32 ký tự hex.
- Gọi internal Jaeger `GET /api/traces/{trace_id}`.
- Trả nguyên response và status phù hợp.
- Có cùng access control với mentor environment.
- Không hỗ trợ arbitrary Jaeger query.

Không thêm endpoint này vào chatbot service và không cần chạy AIOps service.

#### Aggregate view

Tạo một Grafana dashboard tối thiểu trong provisioning hiện có, gồm:

1. Token usage theo model/surface.
2. Estimated cost theo model/surface.
3. p95 model-call latency theo model/surface.

PromQL phải dùng tên series thực tế sau OTLP/Prometheus translation. Đây là
chức năng bắt buộc, không phải report nghiệm thu.

**Check:** gửi request từ ngoài → nhận `x-trace-id` → gọi fetch endpoint → thấy
đủ model/retrieval/tool chain → mở aggregate view thấy series tăng.

### Tutorial 4 — Mở rộng sang Shopping Copilot

**Mục tiêu:** dùng lại contract đã chạy trên Summary, không tạo helper thứ hai.

File chính:

- `src/shopping-copilot/react_agent.py`
- `src/shopping-copilot/memory_retrieval.py`
- `src/shopping-copilot/memory_extractor.py`
- `src/shopping-copilot/bedrock_grounding.py`
- Copilot frontend API route.

Các bước:

1. Instrument từng ReAct model round.
2. Ghi round index ở span, không dùng làm metric label.
3. Tạo span cho `_run_tool()` nhưng không lưu arguments/results.
4. Instrument retrieval hint, memory extraction và review grounding.
5. Giữ toàn bộ spans dưới parent `copilot_search`.
6. Áp dụng cùng HMAC contract cho user/conversation.
7. Trả `x-trace-id` từ Copilot external API.

**Check:** request có hai ReAct rounds và một tool tạo hai model-call spans,
một tool span và retrieval spans trong cùng trace.

### Tutorial 5 — Failure, privacy và backend smoke test

**Mục tiêu:** kiểm chứng đường xuất thật và các failure paths.

Cases tối thiểu:

- Normal request.
- Provider timeout/rate limit.
- Missing usage.
- Structured response retry.
- Tool validation/dependency failure.
- Controlled static fallback hoặc secondary-model fallback.
- Request chứa `PII-TOKEN-XYZ`.

Chạy tối thiểu:

- Một AI surface trước khi đạt Mandate floor.
- Cả hai surface trước khi đóng hạng mục AI Engineering.
- OTel Collector, Jaeger, Prometheus và Grafana.
- OpenSearch khi kiểm tra logs.

Assertions:

- Mỗi provider attempt có một model-call span.
- Error có `error.type`; fallback đúng semantics tại mục 4.3.
- Retry không làm đứt parent trace.
- Token/cost chỉ tăng khi usage/pricing hợp lệ.
- Fetch-trace entry trả đúng trace vừa replay.
- Aggregate view thay đổi sau request.
- PII canary không có trong Jaeger hoặc OpenSearch.

Poll backend với timeout hữu hạn; không dùng sleep cứng và không silently skip
khi backend không kết nối được.

## 6. Thứ tự triển khai

### Gate A — Mandate floor

Tutorial 1–3 và phần Summary của Tutorial 5.

Hoàn thành khi:

- Summary có full-field model-call spans.
- Một request dựng lại được qua trace ID.
- Replay và fetch-trace entries chạy được.
- Token/cost/latency có aggregate view.
- PII canary không xuất hiện.
- Có một error/fallback trace.

### Gate B — Hai chatbot

Tutorial 4 và toàn bộ Tutorial 5.

Hoàn thành khi:

- Summary và Copilot dùng cùng contract/helper.
- Mọi runtime model call trong inventory đã được instrument.
- Retrieval và tool calls không làm đứt trace.
- Không nhân đôi call-count/latency metrics.

## 7. File-change map tối thiểu

| Khu vực | Thay đổi |
|---|---|
| `ai-common/observability.py` | Span helper, HMAC, usage, pricing, token/cost metrics |
| Shared Bedrock/OpenAI paths | Gọi helper tại provider boundary |
| Product Review | Summary context, retrieval/tool spans, bỏ raw content |
| Shopping Copilot | ReAct, memory, grounding và tool spans |
| OTel Collector | Thêm spanmetrics dimensions |
| Frontend API | `x-trace-id` và thin fetch proxy nếu cần |
| Grafana provisioning | Một LLM aggregate dashboard tối thiểu |
| Tests | Một helper test và service/smoke checks cần thiết |

Không sửa AIOps runtime trong chuỗi tutorial này.

## 8. Điều kiện hoàn thành

- [ ] Mỗi model attempt tạo một span theo OTel GenAI conventions.
- [ ] Model/version của các provider được kiểm thử không còn giá trị `unknown`.
- [ ] Token, cost, latency và outcome query được theo model/surface/time.
- [ ] Model, retrieval và tool calls nằm trong cùng request trace.
- [ ] Summary và Copilot trả `x-trace-id`.
- [ ] Fetch-trace entry trả được trace theo ID.
- [ ] Aggregate view có token, cost và p95 latency.
- [ ] Error/fallback semantics nhất quán.
- [ ] PII/secret canary không xuất hiện trong trace hoặc log.
- [ ] AIOps runtime không cần chạy để kiểm chứng.
- [ ] Không có report/evidence/Jira work trong kế hoạch này.

## 9. Follow-up ngoài phạm vi

- ADR và quy trình ký.
- Jira `AI MANDATE #24`.
- Evidence/repro package và ảnh nghiệm thu.
- Alert thresholds và auto-remediation.
- Per-user cost dashboard.
- Retention, sampling và production access-control review.
