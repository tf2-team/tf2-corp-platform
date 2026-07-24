# Summary Bot Hybrid Cache Implementation Handoff

Tài liệu này là task handoff cho member triển khai **hybrid semantic cache chỉ
trên Summary Bot (`product-reviews`)**. Không triển khai cache cho
`shopping-copilot` trong task này.

## 1. Goal

Giảm số lần gọi model khi cùng một người dùng hỏi lại câu giống hoặc gần giống
về cùng một sản phẩm, đồng thời bảo đảm:

- kết quả semantic chỉ được dùng khi `product_id` khớp;
- cache được cô lập theo người dùng;
- review nguồn thay đổi thì không trả kết quả cũ;
- cache lỗi thì Summary Bot vẫn hoạt động bằng đường gọi model;
- response luôn cho biết `cache_status=hit|miss`.

“Hybrid” trong task này có nghĩa là:

```text
vector similarity của question
AND user_scope khớp
AND product_id khớp
AND source_hash khớp
AND model/prompt/embedding version khớp
```

Đây không phải task thay đổi hybrid retrieval BM25 + dense hiện có trong
`techx_ai_common.retrieval`.

## 2. Scope

### In Scope

- RPC `ProductReviewService.AskProductAIAssistant`.
- Index `ai_summary_cache_idx`.
- Prefix `ai:cache:summary:`.
- Exact hit và semantic hit cho Summary Bot.
- TTL, source-based invalidation, user isolation, metrics và test.
- Cache metadata trong response để replay có thể xác minh.

### Out of Scope

- `shopping-copilot`.
- Memory ngắn hạn hoặc dài hạn.
- Thay đổi `valkey-cart`.
- Cache catalog, cart, pending action hoặc response bị block/fallback.
- Tích hợp hoặc viết policy riêng cho `shopping-copilot`.
- Sửa Terraform hoặc Helm trong task logic này.

## 3. Existing Foundation

Branch `aie` đã có:

- service local `valkey-ai-cache` dùng Valkey bundle 9.0;
- service `ai-cache-bootstrap` tạo index idempotent;
- index `ai_summary_cache_idx`;
- các biến `AI_CACHE_*` cho `product-reviews`;
- cache mặc định tắt bằng `AI_CACHE_ENABLED=false`.

Kiểm tra local:

```powershell
docker compose up ai-cache-bootstrap
docker exec valkey-ai-cache valkey-cli PING
docker exec valkey-ai-cache valkey-cli FT._LIST
```

Kết quả phải có `PONG` và `ai_summary_cache_idx`.

## 4. Files to Change

Member chỉ nên sửa hoặc tạo các file sau:

| File | Việc cần làm |
|---|---|
| `src/ai-common/techx_ai_common/semantic_cache.py` | Adapter chung: connection, normalize, scope/hash, lookup và store |
| `src/ai-common/techx_ai_common/bedrock.py` | Giữ lại usage input/output token từ response model |
| `src/ai-common/pyproject.toml` | Khai báo dependency `valkey` cho adapter chung |
| `src/ai-common/tests/test_semantic_cache.py` | Unit test cho adapter chung |
| `src/product-reviews/product_reviews_server.py` | Tích hợp lookup/store tại Summary Bot boundary |
| `src/product-reviews/metrics.py` | Thêm hit, miss, error và latency metrics |
| `src/product-reviews/tests/test_summary_cache.py` | Test integration với flow Summary Bot |
| `pb/demo.proto` | Thêm cache metadata vào Summary response |
| generated protobuf files | Regenerate bằng target có sẵn sau khi sửa proto |
| `src/product-reviews/README.md` | Thêm lệnh chạy và replay ngắn |

### Shared Boundary

Đặt phần cơ chế ổn định trong `ai-common` để bot khác có thể dùng lại:

- tạo Valkey client từ config;
- normalize text;
- tạo HMAC user scope và deterministic key;
- serialize vector `FLOAT32`;
- exact lookup, filtered KNN lookup, store và TTL;
- fail-open khi Valkey lỗi.

Adapter chung nhận `index_name`, `key_prefix`, metadata filters và payload từ
caller. Không hardcode `summary`, product review schema hoặc protobuf class
vào `ai-common`.

Giữ policy của Summary Bot trong `product_reviews_server.py`:

- lúc nào fetch/sanitize review;
- cách tính `source_hash` từ review;
- status nào được cache;
- prompt/model version;
- cách dựng `AskProductAIAssistantResponse`;
- metrics của Summary Bot.

Không tạo interface/factory/plugin system. Một module với các function hoặc
một class nhỏ là đủ. Khi làm Copilot, member sau reuse adapter và truyền
index/prefix/policy khác, không sửa behavior của Summary Bot.

## 5. Configuration Contract

Đọc các biến sau:

| Variable | Default | Ý nghĩa |
|---|---:|---|
| `AI_CACHE_ENABLED` | `false` | Feature flag tổng |
| `AI_CACHE_ADDR` | `valkey-ai-cache:6379` | Valkey endpoint |
| `AI_CACHE_TLS` | `false` | Bật TLS ở môi trường deploy |
| `AI_CACHE_PASSWORD` | rỗng local | Auth token |
| `AI_CACHE_TTL_SECONDS` | `3600` | TTL mỗi entry |
| `AI_CACHE_MAX_DISTANCE` | `0.12` | Cosine distance lớn nhất được hit |
| `AI_CACHE_USER_HMAC_SECRET` | local default | Secret tạo user scope |

Không log password, secret, raw `user_id`, raw question hoặc cache key.

## 6. Cache Record

Lưu mỗi entry dưới dạng Valkey HASH:

```text
key: ai:cache:summary:<sha256>

kind              summary
user_scope        HMAC-SHA256(user_id)
product_scope     normalized product_id
source_hash       SHA-256 của review nguồn chuẩn hóa
prompt_scope      summary-prompt:v1
model_scope       provider:model
embedding_scope   all-MiniLM-L6-v2:v1
question_hash     SHA-256 của normalized question
answer_json       serialized AskProductAIAssistantResponse payload
embedding         FLOAT32 little-endian bytes, DIM 384
created_at        Unix timestamp
```

Cache key phải deterministic từ:

```text
user_scope
product_scope
source_hash
prompt_scope
model_scope
embedding_scope
question_hash
```

Set HASH và TTL trong cùng pipeline:

```python
pipe.hset(key, mapping=record)
pipe.expire(key, ttl_seconds)
pipe.execute()
```

Chỉ lưu response thành công có status `GROUNDED`. Không lưu:

- `BLOCKED`;
- `RATE_LIMITED`;
- `FALLBACK`;
- `ABSTAINED`;
- response không qua schema/grounding validation.

## 7. Identity Boundary

`x-session-id` hiện đang được dùng cho rate limit nhưng không đủ để đại diện
người dùng xuyên phiên.

Trong `AskProductAIAssistant`, đọc:

```text
x-user-id       stable user boundary cho cache
x-session-id    rate-limit/session boundary hiện tại
```

Quy tắc:

- thiếu `x-user-id` thì bỏ qua cache và trả `cache_status=miss`;
- không dùng `anonymous` làm shared cache scope;
- `user_scope = HMAC-SHA256(AI_CACHE_USER_HMAC_SECRET, x-user-id)`;
- không lưu raw `x-user-id` trong Valkey;
- người dùng B không được query entry của người dùng A.

## 8. Source Hash and Invalidation

Trước lookup, vẫn phải đọc và sanitize toàn bộ review nguồn. Mục tiêu cache là
bỏ qua model call, không phải bỏ qua source validation.

Tính `source_hash` từ **toàn bộ danh sách review sau sanitize nhưng trước bước
retrieval theo question**, sắp theo `source_id`, gồm:

```text
source_id | score | normalized text
```

Không đưa username hoặc PII vào hash input.

Khi mentor sửa một review:

1. request tiếp theo đọc lại nguồn;
2. `source_hash` thay đổi;
3. filter không tìm thấy entry cũ;
4. response trả `cache_status=miss`;
5. model chạy và tạo entry mới.

Không cần scan hoặc xóa entry cũ ngay. TTL sẽ dọn entry cũ; `source_hash`
ngăn entry đó được sử dụng.

## 9. Lookup Algorithm

Thứ tự trong `get_ai_assistant_response`:

```text
sanitize request
fetch + sanitize all reviews
compute user_scope, source_hash and normalized question
exact lookup
semantic lookup with metadata filters
if hit: validate cached payload and return
rate limit expensive model path
retrieve reviews relevant to question
call model + grounding + output guard
if GROUNDED: store cache
return miss response
```

Exact lookup dùng deterministic key trước. Nếu miss, chạy vector query trên
`ai_summary_cache_idx`.

Semantic query bắt buộc filter:

```text
@kind:{summary}
@user_scope:{...}
@product_scope:{...}
@source_hash:{...}
@prompt_scope:{...}
@model_scope:{...}
@embedding_scope:{...}
=>[KNN 1 @embedding $vector AS distance]
```

Chỉ hit khi `distance <= AI_CACHE_MAX_DISTANCE`.

Mã sản phẩm phải nằm trong TAG filter, không dựa vào vector question. Vì vậy:

```text
"Tóm tắt review product A123"
"Tóm tắt review product A124"
```

không bao giờ dùng chung entry dù embedding rất giống nhau.

Cache exception phải được catch tại cache boundary, tăng error metric và tiếp
tục đường model như một cache miss.

## 10. Embedding

Reuse model `all-MiniLM-L6-v2` đang được load lazy trong
`techx_ai_common.retrieval`; không load thêm một model thứ hai trong process.

Member có thể expose một helper nhỏ từ `retrieval.py` nếu cần, nhưng không
refactor toàn bộ retrieval pipeline.

Embedding phải:

- dimension `384`;
- `numpy.float32`;
- little-endian bytes;
- normalize question ổn định trước encode;
- có `embedding_scope` để đổi model không dùng nhầm cache cũ.

## 11. Response Contract

Thêm vào `AskProductAIAssistantResponse` trong `pb/demo.proto`:

```protobuf
string cache_status = 5;  // hit | miss
string cache_match = 6;   // exact | semantic | none
float cache_distance = 7; // 0 for exact/miss
```

Sau đó chạy:

```powershell
make docker-generate-protobuf
```

Commit tất cả generated stubs do command tạo ra. Không sửa generated files
bằng tay.

Mọi response của RPC phải có `cache_status`:

- exact hit: `hit`, `exact`, `0`;
- semantic hit: `hit`, `semantic`, khoảng cách thật;
- model path hoặc cache bị bypass/error: `miss`, `none`, `0`.

## 12. Metrics

Thêm metric low-cardinality trong `src/product-reviews/metrics.py`:

```text
ai_cache_requests_total{outcome,match}
ai_cache_lookup_duration_ms{outcome}
ai_cache_model_calls_total
ai_cache_model_input_tokens_total
ai_cache_model_output_tokens_total
```

Allowed labels:

```text
outcome = hit | miss | error | bypass
match   = exact | semantic | none
```

Không dùng `user_id`, `product_id`, question, cache key hoặc source hash làm
metric label.

Token phải lấy từ trường `usage` của response model thật, không ước lượng từ
độ dài chuỗi. Nếu wrapper hiện tại chỉ trả text, mở rộng wrapper để trả thêm
`inputTokens` và `outputTokens` nhưng giữ API cũ tương thích với caller khác.

## 13. Tests

### Unit Tests

Trong `src/ai-common/tests/test_semantic_cache.py`:

1. Normalize question cho kết quả deterministic.
2. User scope là HMAC và không chứa raw user ID.
3. Exact key thay đổi khi product, source hoặc user thay đổi.
4. Semantic hit chỉ được nhận dưới distance threshold.
5. Payload lỗi schema bị xem là miss.
6. Valkey exception fail-open thành miss.
7. Store đặt TTL.

### Summary Flow Tests

Trong `src/product-reviews/tests/test_summary_cache.py`:

1. Request đầu: `miss`, model gọi một lần.
2. Request y hệt: `hit/exact`, model không gọi thêm.
3. Paraphrase cùng ý: `hit/semantic`, model không gọi thêm.
4. Câu gần giống nhưng product khác: `miss`.
5. Cùng request nhưng user khác: `miss`.
6. Sửa review nguồn: request tiếp theo `miss` và trả dữ liệu mới.
7. Cache unavailable: request vẫn trả response model.
8. `BLOCKED`, `FALLBACK`, `ABSTAINED` không được store.

Mock model/embedding trong unit test. Ít nhất một integration test phải dùng
Valkey Search thật:

```powershell
docker compose up ai-cache-bootstrap
$env:AI_CACHE_ENABLED="true"
python -m pytest src/ai-common/tests/test_semantic_cache.py -v
python -m pytest src/product-reviews/tests/test_summary_cache.py -v
```

## 14. Replay Evidence

Thêm một script nhỏ tại:

```text
src/product-reviews/scripts/replay_summary_cache.py
```

Script nhận:

```text
product_id
question
user_id
session_id
repeat
output_file
```

Mỗi lần gọi in một JSON line:

```json
{
  "request_no": 2,
  "product_id": "A123",
  "cache_status": "hit",
  "cache_match": "semantic",
  "cache_distance": 0.04,
  "latency_ms": 28.7
}
```

Không in raw user ID hoặc secret. README phải ghi chính xác lệnh chạy script
và bản ghi review nào mentor có thể sửa để kiểm tra invalidation.

### Before and After Measurement

Chạy cùng một dataset có request lặp ở hai chế độ:

```text
Baseline: AI_CACHE_ENABLED=false
After:    AI_CACHE_ENABLED=true, bắt đầu với cache rỗng
```

Không thay model, prompt, dataset hoặc concurrency giữa hai lần chạy. Mỗi lần
phải lưu raw JSON Lines và một bảng tổng hợp:

| Metric | Baseline | Cache Enabled | Saving |
|---|---:|---:|---:|
| Requests | | | |
| Cache hits | 0 | | |
| Cache hit-rate | 0% | | |
| Model calls | | | |
| Input tokens | | | |
| Output tokens | | | |
| Mean latency (ms) | | | |
| p95 latency (ms) | | | |
| Total model cost (USD) | | | |

Công thức:

```text
hit_rate = cache_hits / cacheable_requests
input_cost = input_tokens / 1_000_000 * input_price_per_million
output_cost = output_tokens / 1_000_000 * output_price_per_million
total_model_cost = input_cost + output_cost
cost_saved = baseline_cost - cache_enabled_cost
cost_saved_percent = cost_saved / baseline_cost * 100
```

Ghi model ID, region, ngày đo và nguồn đơn giá cạnh bảng. Chi phí phải tính từ
token usage thật của các model call trong replay; không hardcode một con số
“tiết kiệm dự kiến”.

## 15. Acceptance Criteria

Task hoàn thành khi:

- [ ] Chỉ Summary Bot được tích hợp cache.
- [ ] Lần đầu miss, câu lặp lần hai hit và không gọi model.
- [ ] Paraphrase cùng product/user/source có thể semantic hit.
- [ ] Product khác luôn miss dù vector gần nhau.
- [ ] User khác không đọc được entry của user trước.
- [ ] Review nguồn thay đổi làm request tiếp theo miss.
- [ ] Entry có TTL.
- [ ] Cache down không làm Summary Bot down.
- [ ] Response luôn có `cache_status=hit|miss`.
- [ ] Có hit-rate và model-call count từ replay thật.
- [ ] Có mean/p95 latency trước–sau trên cùng dataset.
- [ ] Có input/output token thật và model cost trước–sau.
- [ ] Có raw replay JSONL và bảng tổng hợp tái tính được.
- [ ] Test mới và test `product-reviews` hiện có đều pass.
- [ ] README có lệnh setup, test và replay.

## 16. Pull Request Boundary

PR của member chỉ nên chứa:

- adapter cache dùng chung trong `ai-common`;
- policy và integration cache của `product-reviews`;
- response contract và generated protobuf;
- metrics;
- tests;
- replay script;
- README hướng dẫn chạy.

Nếu phát hiện cần sửa `tf2-corp-chart`, `tf2-corp-infra`,
`shopping-copilot` hoặc memory, ghi thành follow-up; không mở rộng PR này.
