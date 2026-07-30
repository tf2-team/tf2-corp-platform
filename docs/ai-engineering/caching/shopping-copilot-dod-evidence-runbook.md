# Bằng chứng DoD A1.3 — Shopping Copilot Hybrid Cache

**Ngày:** 2026-07-29
**Phạm vi:** Shopping Copilot (`shopping-copilot`) hybrid cache: exact lookup + semantic KNN trên Valkey
**Branch:** `feat/ai-shopping-hybrid-cache`
**Commit đang test:** `dc7756c`
**Model khi cache miss:** Amazon Bedrock `us.amazon.nova-2-lite-v1:0`, region `us-east-1`
**Compose:** `docker-compose.yml` + `docker-compose.ai-dev.yml`
**Công cụ Replay:** `src/shopping-copilot/scripts/replay_shopping_cache.py`
**Thư mục Artifact:** [`evidence/a1.3-shopping-cache/`](../../../evidence/a1.3-shopping-cache/)

Cấu hình cache tại thời điểm đo lường:

```text
AI_CACHE_ENABLED=true
AI_CACHE_ADDR=valkey-ai-cache:6379
AI_CACHE_TTL_SECONDS=3600
AI_CACHE_MAX_DISTANCE=0.40
LLM_PROVIDER=bedrock
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
```

`AI_CACHE_USER_HMAC_SECRET` cố tình được loại trừ khỏi bằng chứng để bảo mật.

> `0.40` là cấu hình được ghi lại cho lần chạy này. Việc hiệu chỉnh ngưỡng cho môi trường production nằm ngoài phạm vi của tài liệu này.

---

## 1. Kết quả tổng quan

Luồng cache cốt lõi đã đo lường và hoạt động đúng:

1. Yêu cầu khám phá (grounded) đầu tiên trả về `miss/none`.
2. Yêu cầu lặp lại y hệt trả về `hit/exact`, khoảng cách (distance) `0`.
3. Câu hỏi đồng nghĩa an toàn (paraphrase) trả về `hit/semantic`, khoảng cách `0.0846951`.
4. Cả ba kết quả đều bảo toàn cấu trúc danh sách gồm ba ID sản phẩm giống nhau.
5. Trong lần gọi `hit/exact`, bộ đếm số lần gọi model Bedrock không thay đổi, giữ nguyên ở mức `16 -> 16`.
6. Valkey đã tạo index `ai_copilot_cache_idx`; các entry được đo có TTL dương là `3348` và `3456` giây so với cấu hình `3600`.
7. Bộ test đầy đủ cho Shopping Copilot cộng với semantic-cache dùng chung đều pass: `65 passed`.
8. Một truy vấn lặp lại trả về `NO_RESULTS` vẫn giữ kết quả là `miss` hai lần, chứng minh rằng các phản hồi không đạt trạng thái "grounded" sẽ không được lưu vào cache.

Gói bằng chứng này không khẳng định rằng mọi trường hợp lỗi (failure-path) DoD đều đã được đo lường live. Các cơ chế cô lập User/conversation, invalidation nguồn và fail-open đã được cover bởi code và tests, nhưng đang chờ để xuất ra các artifact runtime riêng.

---

## 2. Danh sách Artifact

| # | Artifact | Mục đích |
|---|---|---|
| 01 | [01-tests-output.txt](../../../evidence/a1.3-shopping-cache/01-tests-output.txt) | Toàn bộ tests của Shopping Copilot + semantic-cache dùng chung |
| 02 | [02-valkey-index-and-ttl.txt](../../../evidence/a1.3-shopping-cache/02-valkey-index-and-ttl.txt) | Valkey health, index, namespace của physical key, version metadata và TTL |
| 03 | [03-replay-non-cacheable.jsonl](../../../evidence/a1.3-shopping-cache/03-replay-non-cacheable.jsonl) | Các request lặp lại trả về `NO_RESULTS` vẫn là miss |
| 04 | [04-replay-cache-enabled.jsonl](../../../evidence/a1.3-shopping-cache/04-replay-cache-enabled.jsonl) | Bằng chứng runtime chính: cold miss, exact hit và semantic hit |
| 05 | [05-model-call-suppression.txt](../../../evidence/a1.3-shopping-cache/05-model-call-suppression.txt) | Lượt Exact hit không làm tăng bộ đếm model của Bedrock |
| 06 | [06-metrics-snapshot.txt](../../../evidence/a1.3-shopping-cache/06-metrics-snapshot.txt) | Prometheus counters cho cache/model/token |
| 07 | [07-summary-table.md](../../../evidence/a1.3-shopping-cache/07-summary-table.md) | Bảng tóm tắt kết quả đo đạc và các hạn chế |

Các ảnh chụp màn hình UI được cung cấp trong luồng review là bằng chứng bổ sung. Các file JSONL thô và output từ Prometheus/Valkey ở trên là bằng chứng dưới dạng machine-readable chính thức.

---

## 3. Ma trận theo dõi DoD (Definition of Done)

| # | Definition of Done (Tiêu chí Hoàn thành) | Bằng chứng | Kết quả |
|---|---|---|---|
| 1 | Request đầu tiên đi qua luồng cold | Artifact 04, hàng 1: `miss/none`, `GROUNDED` | **PASS — runtime** |
| 2 | Request lặp lại tái sử dụng kết quả cache | Artifact 04, hàng 2: `hit/exact`, distance `0` | **PASS — runtime** |
| 3 | Paraphrase an toàn có thể dùng semantic cache | Artifact 04, hàng 3: `hit/semantic`, distance `0.0846951 <= 0.40` | **PASS — runtime** |
| 4 | Lượt Hit không gọi provider model | Artifact 05: Bedrock counter `16 -> 16` ở một lần exact hit | **PASS — runtime** |
| 5 | Giữ nguyên phản hồi có cấu trúc | Artifact 04: tất cả các hàng đều trả về `1YMWWN1N4O`, `6E92ZMYYFZ`, `OLJCESPC7Z` | **PASS — runtime** |
| 6 | Chỉ các phản hồi grounded hợp lệ mới được lưu cache | Artifact 03: cùng một request `NO_RESULTS` bị `miss` hai lần; artifact 01 tests fallback/cart/error paths | **PASS — runtime + test** |
| 7 | Cache entry sẽ hết hạn | Artifact 02: TTL `3348` và `3456`, cấu hình `3600` | **PASS — runtime** |
| 8 | Có sẵn cache và model metrics | Artifact 06: miss/exact/semantic counters cộng với model/token counters | **PASS — runtime** |
| 9 | Key không làm lộ user/conversation/question gốc | Artifact 02: Physical key dùng SHA-256 và HMAC scopes đã mã hóa | **PASS — runtime + code** |
| 10 | Cô lập User và conversation scopes | Artifact 01 chứa các bài kiểm tra HMAC conversation-scope | **PASS — test; chờ check live** |
| 11 | Sửa Catalog/review/conversation vô hiệu hóa entries cũ | Artifact 01 bài kiểm tra source-snapshot | **PASS — test; chờ check live** |
| 12 | Valkey bị lỗi thì tự động Fail-open | Artifact 01 bài kiểm tra lỗi cache | **PASS — test; chờ check live** |
| 13 | Bảng so sánh chi phí Cache OFF vs Cache ON | Bộ đếm exact-hit chứng minh tiết kiệm được một lần gọi model; replay chế độ cache-off chưa được đo toàn bộ | **CHƯA HOÀN THIỆN** |

Trạng thái cố tình phân biệt rõ giữa bằng chứng runtime thực tế và bằng chứng ở mức độ unit-test. Một bài unit PASS không được xem là đã thử nghiệm live (bơm lỗi thật).

---

## 4. Môi trường và khởi động

Thư mục làm việc: repository root `tf2-corp-platform`.

Không cần build lại nếu các images tương ứng đã tồn tại:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml up -d --no-build `
  valkey-ai-cache ai-cache-bootstrap postgresql product-catalog `
  product-reviews valkey-cart shopping-copilot
```

Compose cũng tự khởi động các dependencies như OpenTelemetry collector.
Để lấy bằng chứng Prometheus:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml `
  up -d --no-build prometheus
```

Shopping Copilot preloads guardrail models trước khi mở gRPC port. Quá trình này có thể tốn vài phút trên CPU:

```powershell
docker logs -f shopping-copilot
```

Chỉ tiếp tục sau khi thấy dòng:

```text
Shopping Copilot gRPC server started on port 3552
```

Luôn dò tìm host port ngẫu nhiên sau khi tạo lại container:

```powershell
$port = (
  (docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml `
    port shopping-copilot 3552) -split ":"
)[-1]
Write-Host "SHOPPING_COPILOT host port = $port"
```

Host port đo được ở lần chạy này là `57722`. Nó không cố định và không được hardcode ở những lần chạy sau.

---

## 5. Các bước thực hiện bằng chứng và đầu ra

### 5.1 Toàn bộ tests — artifact 01

**Mục tiêu kiểm tra:** Xác minh các cơ chế exact/semantic, HMAC scoping, cập nhật source-snapshot, lỗi payload (malformed entry fallback), đường dẫn giỏ hàng/lỗi không thể cache, định tuyến luồng, guardrails và công cụ.

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src/ai-common;src/shopping-copilot;src/product-reviews"

python -m pytest `
  src/ai-common/tests/test_semantic_cache.py `
  src/shopping-copilot/tests `
  -q -p no:cacheprovider
```

Kết quả đo lường:

```text
65 passed, 265 warnings in 29.97s
```

Warnings chỉ là cảnh báo thư viện cũ (dependency deprecation); không có test nào fail.

### 5.2 Valkey và index — artifact 02

**Mục tiêu kiểm tra:** Xác nhận Valkey đang chạy và có cả 2 semantic indexes.

```powershell
docker exec valkey-ai-cache valkey-cli PING
docker exec valkey-ai-cache valkey-cli FT._LIST
```

Kết quả:

```text
PONG
ai_copilot_cache_idx
ai_summary_cache_idx
```

### 5.3 Replay phản hồi không thể cache — artifact 03

**Mục tiêu kiểm tra:** Một request `NO_RESULTS` lặp lại không bao giờ được tính là hit.

```powershell
python src/shopping-copilot/scripts/replay_shopping_cache.py `
  --host localhost --port $port `
  --user-id evidence-user-20260729 `
  --session-id 77777777-7777-4777-8777-777777777777
```

Các kết quả liên quan:

```text
sequence=1 status=NO_RESULTS cache_status=miss cache_match=none
sequence=2 status=NO_RESULTS cache_status=miss cache_match=none
```

Câu prompt mặc định thứ ba là `GROUNDED` và vẫn là cold miss, nên nó đủ điều kiện lưu vào cache. Dữ liệu thô ở artifact 03.

### 5.4 Cold miss, exact hit và semantic hit — artifact 04

**Mục tiêu kiểm tra:** Thể hiện vòng đời của hybrid-cache bằng một câu truy vấn có khả năng trả về kết quả catalog grounded.

```powershell
python src/shopping-copilot/scripts/replay_shopping_cache.py `
  --host localhost --port $port `
  --user-id evidence-happy-20260729 `
  --session-id 88888888-8888-4888-8888-888888888888 `
  --request 'Recommend telescope options priced below $150.' `
  --request 'Recommend telescope options priced below $150.' `
  --request 'Find telescope options under $150.'
```

Kết quả:

| Lượt | Loại request | Trạng thái | Cache | Match | Distance |
|---:|---|---|---|---|---:|
| 1 | Lần đầu (Cold request) | `GROUNDED` | `miss` | `none` | `0` |
| 2 | Lặp lại y hệt (Exact repeat) | `GROUNDED` | `hit` | `exact` | `0` |
| 3 | Cùng nghĩa (Safe paraphrase) | `GROUNDED` | `hit` | `semantic` | `0.0846951` |

Tất cả 3 dòng đều trả về:

```text
1YMWWN1N4O
6E92ZMYYFZ
OLJCESPC7Z
```

### 5.5 Chặn gọi model — artifact 05

**Mục tiêu kiểm tra:** Chứng minh lượt hit (exact hit) đã tự động bỏ qua vòng gọi model provider, thay vì chỉ suy đoán qua độ trễ.

Truy vấn Prometheus:

```promql
shopping_copilot_model_calls_total{provider="bedrock"}
```

Quy trình:

1. Đọc bộ đếm.
2. Gửi 1 exact request trong phạm vi user/conversation đã có cache.
3. Chờ metric xuất ra.
4. Đọc bộ đếm lại.

Kết quả:

```text
MODEL_CALLS_BEFORE=16
response cache_status=hit cache_match=exact
MODEL_CALLS_AFTER=16
```

Kết quả: **PASS**. Phản hồi được xử lý ở dạng cache hit và số đếm gọi model không hề tăng lên.

### 5.6 Metrics snapshot — artifact 06

Các dòng đo đạc Prometheus:

```text
shopping_copilot_cache_requests_total:
  miss/none      = 4
  hit/exact      = 1
  hit/semantic   = 1

shopping_copilot_model_calls_total{provider="bedrock"} = 16
shopping_copilot_model_input_tokens_total{provider="bedrock"} = 18814
shopping_copilot_model_output_tokens_total{provider="bedrock"} = 680
```

Các bộ đếm này cộng dồn từ khi khởi động container. Artifact 05 là bằng chứng đối chiếu trước/sau cho một lần exact hit.

### 5.7 Physical keys, metadata và TTL — artifact 02

```powershell
$keys = docker exec valkey-ai-cache valkey-cli `
  --scan --pattern "ai:cache:copilot:*"

foreach ($key in $keys) {
  docker exec valkey-ai-cache valkey-cli TTL $key
  docker exec valkey-ai-cache valkey-cli HMGET $key `
    kind user_scope product_scope source_hash `
    prompt_scope model_scope embedding_scope question_hash created_at
}
```

Kết quả:

```text
COPILOT_KEY_COUNT=2
TTL=3348
TTL=3456
kind=shopping-copilot
prompt_scope=shopping-react-agent:v1
model_scope=bedrock:us.amazon.nova-2-lite-v1:0
embedding_scope=all-MiniLM-L6-v2:v1
```

Tất cả định danh user, conversation, nguồn và câu hỏi đều đã được băm (hash).

---

## 6. Thiết kế Scope và Key

Physical key:

```text
ai:cache:copilot:<entry_digest>
```

Trong đó:

```text
entry_digest = SHA256(canonical_json(
  user_scope,
  product_scope,
  source_hash,
  prompt_scope,
  model_scope,
  embedding_scope,
  question_hash
))
```

Bảo vệ quyền riêng tư (Privacy scopes):

```text
user_scope =
  HMAC-SHA256(AI_CACHE_USER_HMAC_SECRET, user_id)

product_scope =
  HMAC-SHA256(
    AI_CACHE_USER_HMAC_SECRET,
    "conversation:" + conversation_id + ":" + request_type
  )
```

Đối với Shopping Copilot, trường `product_scope` chứa thông tin kết hợp giữa conversation và request type đã hash; nó không phải là ID sản phẩm thô.

Bộ lọc nguồn/phiên bản:

```text
source_hash     = hash(conversation state + Mem0 + catalog + review snapshot)
prompt_scope    = shopping-react-agent:v1
model_scope     = bedrock:us.amazon.nova-2-lite-v1:0
embedding_scope = all-MiniLM-L6-v2:v1
kind            = shopping-copilot
```

User ID, conversation ID thô và nội dung câu hỏi không bao giờ tồn tại trong physical key.

---

## 7. Giải thích Ảnh chụp màn hình

### Hình 1 — Lần Miss đầu tiên (Cold cache miss)

> Request đầu tiên `Recommend telescope options priced below $150.` đi qua luồng ReAct/Catalog và trả về 3 sản phẩm. Payload mạng báo cáo `cacheStatus=miss`, `cacheMatch=none` và `cacheDistance=0`, xác nhận không có entry hợp lệ nào được sử dụng.

### Hình 2 — Hit chính xác (Exact cache hit)

> Nhập lại y hệt request trong cùng một ngữ cảnh user và conversation trả về `cacheStatus=hit`, `cacheMatch=exact` và `cacheDistance=0`. Cấu trúc sản phẩm được tải về trực tiếp từ Valkey. Artifact 05 cũng chứng minh bộ đếm model-call không bị tăng.

### Hình 3 — Hit theo ý nghĩa (Semantic cache hit)

> Chuyển đổi câu hỏi thành `Find telescope options under $150.` giữ nguyên được ý định khám phá sản phẩm và scope của nguồn. Phản hồi trả về `cacheStatus=hit`, `cacheMatch=semantic` và `cacheDistance=0.0846951`, nằm trong ngưỡng giới hạn.

### Hình 4 — Ngữ cảnh hội thoại và bộ nhớ (Conversation and memory context)

> Câu hỏi tiếp theo về việc trợ lý nhớ được gì sẽ trả về "telescope preference" từ conversation đang hoạt động. Đây là minh chứng hỗ trợ tính năng tích hợp ReAct/conversation/Mem0, không phải bằng chứng về cache-hit trừ khi có thêm metadata cache hiển thị.

---

## 8. Bảng trường hợp ngoại lệ (Edge-case matrix)

| Edge case (Ngoại lệ) | Hoạt động dự kiến | Bằng chứng hiện tại |
|---|---|---|
| Request cold grounded | Miss, thực thi graph, sau đó lưu (store) | Runtime artifact 04 |
| Request lặp lại y hệt | `hit/exact`, distance `0`, không gọi model provider | Runtime artifacts 04 và 05 |
| Câu hỏi đồng nghĩa an toàn | `hit/semantic` khi toàn bộ scopes khớp và khoảng cách được chấp nhận | Runtime artifact 04 |
| `NO_RESULTS` | Không lưu / Không dùng lại | Runtime artifact 03 |
| `FALLBACK`, `BLOCKED`, `ABSTAINED` | Không lưu cache | Tests/code |
| Công cụ gọi bị lỗi runtime | Thiết lập `cache_eligible=false`; không lưu những lỗi tạm thời | Tests/code |
| Thao tác trên giỏ hàng hoặc có hành động chờ (pending) | Bỏ qua lookup/store; không bao giờ replay mã xác nhận | Tests/code |
| Chế độ Ẩn danh / Không có conversation | Bypass cache | Tests/code |
| Người dùng khác nhau (Different user) | Miss do đã có cô lập HMAC user | Tests; Đang chờ artifact live |
| Cuộc hội thoại khác nhau | Miss do đã có cô lập HMAC conversation | Tests; Đang chờ artifact live |
| Đổi thông tin Catalog/review/conversation/Mem0 | Tạo `source_hash` mới, do đó báo miss | Tests; Đang chờ artifact live |
| Sửa phiên bản Prompt/model/embedding | Miss do không khớp hybrid filters | Code/Valkey metadata |
| Hết hạn TTL | Key tự động hết hạn; request tiếp theo bị miss | Đo được TTL dương; Đang chờ request kiểm tra sau khi hết hạn |
| Valkey ngừng hoạt động | Tự động Fail-open và chạy tiếp graph | Tests; Đang chờ test bơm lỗi live |
| Cache payload lỗi | Bỏ qua hit và chạy theo đường dẫn miss | Tests |

---

## 9.Evidence bổ sung(Optional)

Các artifacts sau cần được bổ sung trước khi có thể kết luận mọi tiêu chí DoD đã hoạt động ổn định end-to-end:

1. Chạy lại (replay) cùng một nhóm test scenario với chế độ Cache-disabled.
2. Lượt Miss live với trường hợp Different-user và Different-conversation.
3. Live source invalidation sau khi chủ động cập nhật Catalog hoặc review.
4. Thử nghiệm live stop/request/start Valkey để kiểm tra tính năng fail-open.
5. Truy vấn báo miss (post-expiration) sau khi vượt quá TTL, hoặc cấu hình chạy thử với một TTL cực ngắn.

Tên các file đề xuất:

```text
08-replay-baseline-cache-off.jsonl
09-runtime-isolation.jsonl
10-source-invalidation.txt
11-fail-open.txt
12-post-expiry-miss.txt
```

---


## 10. Checklist

- [x] Full tests: `65 passed`
- [x] Valkey trả về `PONG`
- [x] Index `ai_copilot_cache_idx` đã tồn tại
- [x] Cold grounded request báo: `miss/none`
- [x] Request lặp lại (Exact repeat) báo: `hit/exact`
- [x] Câu hỏi đồng nghĩa an toàn (Safe paraphrase) báo: `hit/semantic`, distance `0.0846951`
- [x] Payload cấu trúc danh sách sản phẩm được bảo toàn
- [x] Bộ đếm gọi provider của lượt Exact hit không đổi: `16 -> 16`
- [x] Các metrics Cache/model/token đã được xuất (exported)
- [x] Physical key namespace và thông tin metadata về phiên bản đã được kiểm tra
- [x] TTL mang giá trị dương tiệm cận với cấu hình `3600`
- [x] Yêu cầu trả về `NO_RESULTS` không bị bắt thành hit ở lượt tiếp theo
- [ ] Chạy baseline với trạng thái Cache-disabled
- [ ] Đo lường live cho cơ chế cô lập user/conversation
- [ ] Đo lường live cho source invalidation
- [ ] Test live Fail-open cho Valkey
- [ ] Truy vấn báo miss sau khi quá hạn TTL
