# LLM Observability Remediation Plan

## Introduction and motivation

Plan này xuất phát từ một smoke test thật của Shopping Copilot, không phải từ giả định kiến trúc. Khi gửi yêu cầu tìm camera dưới `$1000` và so sánh review, UI trả fallback. Trace cùng request cho thấy ba hiện tượng khác nhau, có nguyên nhân và cách xử lý khác nhau:

| Quan sát | Điều đó cho thấy | Vì sao plan xử lý như vậy |
|---|---|---|
| Copilot gọi model tối đa bốn vòng, gọi `search_catalog` hai lần rồi trả fallback | Model đã không tự kết thúc chuỗi tool calls trong ngân sách cho phép. Service, Catalog và trace vẫn hoạt động. | Đây là biến thiên hành vi của model, không đủ bằng chứng cho runtime defect. Giữ giới hạn và fallback để an toàn; thêm test/eval để đo tần suất và chất lượng thay vì đổi logic ứng dụng theo một run. |
| Bốn invocation model tạo tám `chat` span, theo từng cặp có timestamp và latency gần trùng nhau | Cùng một Bedrock call đang được ghi bởi hai cơ chế instrumentation. | Đây là lỗi dữ liệu telemetry xác định được: cost, token và call count có thể bị nhân đôi. Loại duplicate trước để các số liệu sau đáng tin. |
| Collector báo `data refused due to high memory usage` và `sending queue is full` | Trace có thể tới Jaeger, nhưng metrics có thể bị drop trước khi tới Prometheus/Grafana. | Đây là lỗi pipeline quan sát, nên kiểm tra startup order và tải exporter trước; chỉ tối giản pipeline hoặc tăng memory khi đo lại vẫn tái hiện. |

Vì vậy plan tách ba việc: **sửa telemetry sai**, **đo năng lực model**, rồi **ổn định metrics pipeline**. Thứ tự này quan trọng: không thể dùng dashboard để đánh giá model khi mỗi model call đang bị đếm đôi hoặc metrics đang bị drop.

## 1. Mục tiêu

Khắc phục ba vấn đề đã quan sát được trong lần smoke test Shopping Copilot:

1. Copilot trả fallback sau khi chạm giới hạn bốn vòng gọi model/tool; đây được xem là hành vi cần đo của model, không phải runtime bug trong scope này.
2. Một lần gọi Bedrock tạo hai `chat` span, làm token và cost có nguy cơ bị đếm đôi.
3. OpenTelemetry Collector từ chối metrics do áp lực bộ nhớ, khiến Grafana thiếu dữ liệu.

Plan này chỉ sửa luồng runtime và telemetry hiện tại. Không thêm service AIOps, report, alert hay dashboard mới.

## 2. Baseline đã xác nhận

- Request kiểm chứng: `Find me a suitable camera under $1000 and compare its reviews.`
- Trace ID: `b7bfb3f8cb4b78abd0966967e8a24aa1`
- Tất cả service bắt buộc đều chạy; `ai-cache-bootstrap` kết thúc với exit code `0` là đúng thiết kế.
- Trace đi xuyên qua `frontend` → `shopping-copilot` → `product-catalog`.
- Copilot gọi `search_catalog` hai lần rồi trả `app.ai.fallback`.
- Bốn lần gọi model tạo tám `chat` span có thời gian gần như trùng nhau.
- Collector báo `data refused due to high memory usage` và `sending queue is full`.

## 3. Nguyên tắc khắc phục

- Giữ `_MAX_TOOL_ROUNDS` và fallback hiện tại như safety boundary; đánh giá tool loop qua eval thay vì sửa runtime theo một lần chạy.
- Chỉ một lớp chịu trách nhiệm tạo GenAI span cho mỗi model invocation.
- Không tắt privacy controls hoặc bật capture prompt để debug.
- Ưu tiên thay đổi cấu hình nhỏ và test hồi quy trước khi tăng tài nguyên.
- Mỗi phase phải pass độc lập trước khi chuyển sang phase tiếp theo.

## 4. Phase 1 — Loại bỏ duplicate model spans

### Thay đổi

Giữ `techx_ai_common.observability.call_model` làm nguồn duy nhất tạo GenAI span vì wrapper này đang chịu trách nhiệm cho:

- model/provider/version;
- input/output token;
- estimated cost;
- surface, workflow step và outcome;
- privacy-safe user/session pseudonym.

Tắt auto-instrumentation `botocore` cho `product-reviews` và `shopping-copilot` bằng cấu hình OpenTelemetry hiện có. Không xóa SDK instrumentation khỏi dependency tree.

Rà lại cả đường OpenAI-compatible để chắc chắn không có auto-instrumentation thứ hai tạo cùng semantic span. Chỉ tắt instrumentor nào thực sự tạo duplicate trong trace.

### Files dự kiến

- `docker-compose.yml`
- Test observability hiện có; chỉ bổ sung một check nhỏ nếu chưa có kiểm tra “một invocation, một span”.

### Kiểm chứng

Chạy một request Copilot chỉ cần một lần gọi model và một request Bedrock có tool.

| Assumption | Experiment | Metric | Success threshold |
|---|---|---|---|
| Duplicate đến từ wrapper + botocore auto-instrumentation | Tắt riêng `botocore`, rebuild hai AI service và so trace trước/sau | Số `chat` span trên số lần `client.converse` | Chính xác `1:1` |
| Manual wrapper vẫn đủ dữ liệu | Kiểm tra attributes trên span còn lại | Tỷ lệ field bắt buộc hiện diện | 100% field Mandate 24 của model call |
| Trace cha-con không bị đứt | Mở trace từ `x-trace-id` | Model/tool/retrieval spans cùng trace | 100% cùng trace ID |

### Gate

Không triển khai phase 2 nếu token hoặc cost vẫn bị đếm đôi.

## 5. Phase 2 — Thêm test cho model tool-loop

### Phạm vi

Model có thể gọi lại `search_catalog` với arguments khác và chạm giới hạn bốn vòng. Đây là hành vi cần theo dõi qua eval; không thay đổi prompt, tool policy, `_MAX_TOOL_ROUNDS` hoặc runtime guard trong remediation này.

### Test case mới

Thêm case sau vào bộ eval/test live:

```text
Find me a suitable camera under $1000 and compare its reviews.
```

Case phải ghi nhận cả model rounds, tool calls và outcome; không giả định model luôn trả `ok`.

### Files dự kiến

- `src/shopping-copilot/tests/test_react_agent.py`
- Bộ eval Copilot hiện có nếu đã có case tương ứng.

### Kiểm chứng

| Assumption | Experiment | Metric | Success threshold |
|---|---|---|---|
| Model có thể lặp tool trên prompt so sánh | Chạy case baseline với provider/model đang cấu hình | Số model rounds, số `search_catalog`, outcome | Được ghi nhận trong mỗi run |
| Fallback là safety boundary hợp lệ | Khi model chạm giới hạn, kiểm tra response và trace | Partial result có bị trả như answer không | 0 partial answer được trả như thành công; outcome là `fallback` |
| Khi model chọn đúng sequence, kết quả vẫn grounded | Chạy cùng case với model/provider khác hoặc run pass | Unsupported product/review claim | 0 |

### Gate

Test phải tái hiện được prompt, số vòng, tool calls và outcome trong trace. Nếu tỷ lệ fallback vượt ngưỡng sản phẩm, mở ticket model/eval riêng; không sửa runtime trong plan này.

## 6. Phase 3 — Ổn định Collector và spanmetrics

### Bước 3.1: phục hồi vận hành không đổi code

1. Khởi động `prometheus` trước Collector.
2. Restart Collector để bỏ queue đã tích lũy khi Prometheus chưa sẵn sàng.
3. Gửi một lượng nhỏ request ở cả `summary` và `copilot`.
4. Theo dõi memory, queue errors và dữ liệu dashboard trong 10 phút.

Nếu không còn lỗi, giữ nguyên resource limit và ghi nhận startup ordering là nguyên nhân.

### Bước 3.2: thay đổi cấu hình chỉ khi lỗi còn tái hiện

1. Bỏ `debug` exporter khỏi traces và metrics pipeline mặc định; Jaeger và Prometheus đã là nơi quan sát chính.
2. Giữ `memory_limiter`.
3. Nếu Collector vẫn từ chối dữ liệu dưới smoke load, tăng giới hạn container từ `200 MiB` lên mức nhỏ nhất pass bài test, bắt đầu ở `400 MiB`.
4. Không tăng queue size khi exporter downstream chưa khỏe; queue lớn hơn chỉ trì hoãn lỗi và dùng thêm memory.

### Files dự kiến

- `src/otel-collector/otelcol-config.yml`
- `docker-compose.yml` chỉ khi cần tăng memory.

### Kiểm chứng

| Assumption | Experiment | Metric | Success threshold |
|---|---|---|---|
| Queue đầy do Prometheus khởi động sau Collector | Restart theo đúng thứ tự rồi chạy smoke load | `sending queue is full` | 0 lần trong 10 phút |
| Debug exporter tạo tải không cần thiết | So memory/error trước và sau khi bỏ exporter | Collector memory và rejected metrics | Không có rejected metrics |
| `400 MiB` đủ nếu cấu hình tối giản vẫn thiếu memory | Chạy cùng smoke load với limit mới | Peak memory và limiter rejection | Peak < 80% limit; 0 rejection |
| Dashboard nhận đủ spanmetrics | So số model calls trong Jaeger và Grafana | Sai lệch count | 0 cho cửa sổ test cô lập |

### Gate

- Không còn `data refused due to high memory usage`.
- Không còn `sending queue is full`.
- Token, cost và p95 latency xuất hiện trong Grafana cho cả `copilot` và `summary`.

## 7. Phase 4 — End-to-end regression

Chạy lần lượt:

1. Unit tests của `ai-common`, `product-reviews` và `shopping-copilot`.
2. Frontend tests và TypeScript check.
3. Collector config validation.
4. Rebuild `product-reviews`, `shopping-copilot` và `frontend` nếu source tương ứng thay đổi.
5. Restart Collector/Grafana nếu config mounted thay đổi.
6. Chạy hai smoke cases:
   - mở product detail để sinh Product Review summary;
   - chạy prompt camera baseline trong Shopping Copilot.
7. Lấy `x-trace-id`, mở Jaeger và đối chiếu Grafana.
8. Dùng PII canary giả để xác nhận raw prompt, secret, tool arguments và user ID gốc không xuất hiện.

## 8. Definition of Done

- Một model invocation tạo đúng một GenAI span.
- Copilot baseline có test/eval ghi nhận rõ số model rounds, tool calls và `ok`/`fallback`; không dùng kết quả một run để kết luận năng lực model.
- Trace thể hiện đầy đủ request → retrieval/tool → model → outcome.
- Model, token, cost và latency không bị đếm đôi.
- Collector không drop trace/metrics trong smoke window 10 phút.
- Grafana hiển thị dữ liệu cho `copilot` và `summary`.
- Không có raw prompt, PII, secret hoặc raw tool arguments trong trace/log.
- Không cần chạy service AIOps để hoàn tất validation.

## 9. Thứ tự triển khai đề xuất

1. Phase 1: duplicate spans — sửa trước vì dữ liệu cost sai sẽ làm mọi kiểm chứng sau sai.
2. Phase 2: tool loop — thêm test/eval, không sửa runtime.
3. Phase 3: Collector — đo sau khi span volume đã đúng.
4. Phase 4: regression và privacy validation.
