# AI MANDATE #23 — GenAI Caching and Memory

> **Status:** `DRAFT — evidence pending`
>
> Đây là dàn ý body Jira. Thay mọi `[TODO]` bằng link, số đo thực tế hoặc `N/A`
> trước khi chuyển trạng thái sang `PASS`.

## 1. Outcome at a Glance

Tầng AI tránh gọi lại model khi có thể tái sử dụng an toàn một kết quả cũ, giữ
hội thoại mạch lạc trong một session, và truy hồi preference được phép lưu ở
session sau của đúng người dùng. Cache và memory được cô lập theo user; khi nguồn
grounding thay đổi, các cache entry bị ảnh hưởng không còn hợp lệ.

Phạm vi cache gồm Review Summary và Shopping Copilot; phần memory được kiểm chứng trên
Shopping Copilot. Mục tiêu không phải chỉ làm câu trả lời nhanh hơn: mỗi cache hit phải
chỉ ra được là kết quả cũ vẫn an toàn để tái sử dụng, còn dữ liệu đã đổi thì phải buộc hệ
thống tạo câu trả lời mới. Các scenario và raw artifact ở mục 5 là bằng chứng cho
các tuyên bố đã được kiểm chứng; những case chưa có live evidence được ghi rõ thay
vì đánh dấu đạt.

Chi tiết kỹ thuật nằm tại
[shared semantic cache guide](caching/semantic-cache-implementation-guide.md),
[Shopping Copilot cache runbook](caching/shopping-copilot-dod-evidence-runbook.md)
và [Shopping Copilot Mem0 integration](memory/shopping-copilot-mem0-integration-plan.md).

## 2. Why this Change Matters

Người dùng thường lặp lại một câu hỏi, hỏi tiếp dựa trên câu trả lời trước đó, hoặc quay
lại vào một session khác. Nếu mỗi request đều bắt đầu từ đầu, hệ thống vừa tốn token và
chậm hơn cần thiết, vừa khiến trải nghiệm như đang nói với một trợ lý không nhớ gì.

Vấn đề không chỉ là performance. Reuse nhầm một câu trả lời của người khác là rò dữ liệu;
reuse câu trả lời dựa trên catalog hoặc review đã đổi là trả lời sai. Vì vậy cache phải có
ranh giới user và kiểm tra freshness, còn memory phải phân biệt rõ context tạm thời của
một cuộc hội thoại với preference được phép nhớ lâu hơn.

Implementation này có ba tính chất sản phẩm:

1. **Reuse safely:** request lặp và đủ điều kiện trả `cache=hit`, không gọi lại
   model.
2. **Maintain continuity:** Copilot hiểu tham chiếu và constraint qua tối thiểu
   ba lượt liên quan trong cùng session.
3. **Remember only for the right user:** session mới truy hồi permitted durable
   facts của cùng `user_id`; `user_id` khác không nhận cache response hoặc memory
   của người dùng đầu tiên.

## 3. Scope and Data Boundaries

Mỗi lời gọi qua replay hoặc production path đều mang `user_id`, `session_id` và request.
Ba giá trị này xác định dữ liệu nào được phép đọc, cache entry nào có thể tái sử dụng, và
context nào phải bị bỏ đi khi session kết thúc. Với replay, chúng là test identities do
mentor cung cấp; production path ánh xạ chúng từ identity đã được xác thực.

### 3.1 Identity Contract

| Field | Ý nghĩa | Ranh giới được áp dụng |
|---|---|---|
| `user_id` | Ranh giới sở hữu dữ liệu bền | Cache và durable memory không đi qua user khác. Raw ID không dùng làm metric label. |
| `session_id` | Ranh giới một hội thoại | Chỉ giữ conversational context tạm thời. |
| `request` | Yêu cầu của user cho replay/cache lookup | Được normalize trước exact hash hoặc semantic lookup. |
| Source version/hash | Phiên bản catalog/review/source dùng để trả lời | Source thay đổi làm response cũ không còn đủ điều kiện dùng lại. |

Cache key, thứ tự lookup và cách source version tham gia vào cache scope được mô tả trong
[shared semantic cache guide](caching/semantic-cache-implementation-guide.md).

### 3.2 Memory Continuity and User Isolation

Memory xuất hiện như một capability thống nhất của Copilot, nhưng có hai vòng đời
và hai phạm vi dữ liệu riêng:

| Scope | Key | Nội dung lưu | Có thể truy hồi ở session mới? |
|---|---|---|---|
| Session context | `user_id + session_id` | Nhu cầu hiện tại, tham chiếu, item đã chọn, conversational context đang chờ | Không |
| Durable user memory | `user_id` | Preference hoặc shopping constraint đã được policy cho phép | Có |

Chỉ durable fact tối thiểu mới được lưu. PII bị từ chối hoặc sanitize theo policy.
Memory khi truy hồi luôn được xem là untrusted data, không phải instruction.
Chi tiết storage, retrieval, retention và PII guard nằm trong
[Shopping Copilot Mem0 integration](memory/shopping-copilot-mem0-integration-plan.md).

## 4. Design Summary

Thiết kế tách hai việc dễ bị nhầm lẫn: cache tái sử dụng một response còn hợp lệ để tránh
gọi model, còn memory chỉ cung cấp context thuộc đúng user cho một request mới. Cache không
được dùng như kho preference toàn cục, và memory không làm một response cũ trở nên hợp lệ
khi source grounding đã đổi. Hai capability gặp nhau tại request path, nhưng cùng tuân theo
identity boundary ở mục 3.

### 4.1 Request Path

Luồng dưới đây cho thấy thứ tự kiểm soát: hệ thống xác định đúng user và context trước,
sau đó mới quyết định một entry cache còn hợp lệ hay không. Chỉ response đã qua grounding
và validation mới có thể được lưu; một cache hit trả thẳng response hợp lệ, còn cache miss
đi qua model rồi cập nhật cache và memory đủ điều kiện.

```mermaid
flowchart LR
    A[request + user_id + session_id] --> B[Validate identity and safety]
    B --> C[Load session and durable memory]
    C --> D[Build source version and cache scope]
    D --> E{Valid cache entry?}
    E -- hit --> F[Return response: cache=hit]
    E -- miss --> G[Call model and grounded tools]
    G --> H[Validate output]
    H --> I[Store eligible response with TTL]
    I --> J[Update permitted memory]
    J --> K[Return response: cache=miss]
```

### 4.2 Caching Approach

#### Caching là gì?

Trong luồng không có cache, một câu hỏi luôn đi qua guardrail, tools và model dù
hệ thống vừa trả lời đúng câu đó trước đó. Cache thêm một đường đi ngắn hơn: lưu
lại một response đã được kiểm tra và chỉ reuse khi request mới có cùng ranh giới
an toàn với entry cũ.

Cache ở đây không phải memory:

- **Cache** trả lại một response đã tạo trước đó để tránh gọi model lại.
- **Memory** lấy context hoặc preference của user để tạo một response mới.

Ví dụ, user hỏi “Recommend telescope options priced below $150” lần đầu thì hệ
thống vẫn gọi model và lưu response đủ điều kiện. Nếu cùng user hỏi lại đúng câu
đó trong cùng context và source chưa đổi, hệ thống có thể trả exact hit. Nếu user
đổi cách diễn đạt thành “Find telescope options under $150”, hệ thống có thể trả
semantic hit nếu độ tương đồng nằm trong threshold.

#### Motivation và problem cần giải quyết

| Problem | Nếu không xử lý | Kỹ thuật được dùng |
|---|---|---|
| Request lặp vẫn gọi model | Tốn token, model call và thời gian xử lý | Exact cache |
| User diễn đạt lại cùng intent | Exact string key luôn miss | Embedding và semantic KNN |
| Câu giống nhau nhưng khác user | Có nguy cơ rò response giữa user | HMAC user scope |
| Câu giống nhau nhưng khác conversation/intent | Có thể reuse sai conversational state | HMAC conversation + request scope |
| Catalog, review hoặc memory đã đổi | Cache có thể trả dữ liệu cũ | Source snapshot/hash |
| Prompt, model hoặc embedding thay đổi | Entry cũ có thể không còn tương thích | Version scopes và hybrid filters |
| Entry tồn tại quá lâu | Tăng nguy cơ stale response | TTL |
| Valkey hoặc embedding lỗi | Cache làm hỏng toàn bộ Copilot | Fail-open về model path |
| Cart action hoặc output không grounded bị lưu | Có thể replay thao tác hoặc response không an toàn | Cacheability policy |

#### Implementation đang được dùng

Implementation chia thành hai lớp:

1. `techx_ai_common.semantic_cache.SemanticCache` là adapter dùng chung. Lớp này
   quản lý Valkey index, deterministic exact key, embedding, filtered KNN, TTL
   và fail-open.
2. `shopping_cache.py` là policy của Shopping Copilot. Lớp này quyết định request
   nào được cache, tạo conversation scope, chụp source snapshot, serialize state
   an toàn và hydrate state khi hit.

Mỗi lookup được cô lập bằng các giá trị sau:

| Scope/filter | Cách tạo | Problem được giải quyết |
|---|---|---|
| `user_scope` | HMAC-SHA256 từ `user_id` | Không để user khác dùng cùng cache entry; không lộ raw user ID trong key |
| Conversation scope | HMAC từ `conversation_id` và nhóm intent như discovery, product hoặc memory | Không trộn state giữa conversation hoặc loại request |
| `source_hash` | SHA-256 của stable conversation state, memory fingerprint và catalog/review snapshot liên quan | Source/context đổi thì entry cũ không còn match |
| `prompt_scope` | `shopping-react-agent:v1` | Prompt version đổi không reuse entry cũ |
| `model_scope` | Provider và model đang chạy | Model đổi không reuse output không tương thích |
| `embedding_scope` | Tên/version embedding model | Vector từ embedding version khác không bị trộn |

#### Lookup diễn ra như thế nào?

```mermaid
flowchart TD
    A[Request đã qua identity và safety check] --> B[Normalize request]
    B --> C[Build HMAC user and conversation scopes]
    C --> D[Build current source snapshot]
    D --> E[Exact deterministic lookup]
    E --> F{Exact entry hợp lệ?}
    F -- Có --> G[Hydrate state and return exact hit]
    F -- Không --> H[Create request embedding]
    H --> I[Filtered KNN in Valkey]
    I --> J{All hybrid filters match and distance <= 0.12?}
    J -- Có --> K[Hydrate state and return semantic hit]
    J -- Không --> L[Continue to ReAct agent and model]
    L --> M{Output is grounded, read-only and cache eligible?}
    M -- Có --> N[Store response with TTL 3600 seconds]
    M -- Không --> O[Return without storing]
```

Exact lookup chạy trước vì rẻ và không cần vector search. Semantic lookup chỉ
chạy khi exact miss. KNN lấy candidate gần nhất nhưng candidate vẫn phải khớp
đồng thời user, conversation/resource, source, prompt, model và embedding scope.
Threshold mặc định là `0.12`; distance càng nhỏ thì hai request càng gần nhau.

Chỉ response `GROUNDED`, read-only và không có pending action mới được lưu.
Anonymous request, cart mutation và response như `NO_RESULTS` không được biến
thành reusable cache entry. Evidence hiện tại cho thấy hai request `NO_RESULTS`
liên tiếp đều miss.


### 4.3 Cache Safety Rules

Bảng này tách hai loại bằng chứng:

- **Code reference** chỉ ra chính xác logic nằm ở file và dòng nào.
- **Runtime/test evidence** chứng minh logic đó đã chạy hoặc được test như thế nào.

| Rule | Giá trị implementation | Code reference | Runtime/test evidence |
|---|---|---|---|
| Cache scope | Key vật lý dùng namespace `ai:cache:copilot:{sha256}`. Exact key gồm HMAC user scope, conversation/request scope, source hash, prompt/model/embedding version và question hash. Raw user ID, conversation ID và prompt không xuất hiện trong key name. | [`_compute_user_scope()` và deterministic key](../../src/ai-common/techx_ai_common/semantic_cache.py#L163-L195); [conversation/request scope](../../src/shopping-copilot/shopping_cache.py#L81-L108) | [Valkey index and TTL](../../evidence/a1.3-shopping-cache/02-valkey-index-and-ttl.txt); [user/key unit tests](../../src/ai-common/tests/test_semantic_cache.py#L71-L113); [conversation isolation tests](../../src/shopping-copilot/tests/test_shopping_cache.py#L245-L277) |
| Match modes | Exact lookup chạy trước. Exact miss mới tạo embedding và chạy filtered KNN; semantic candidate chỉ được nhận khi distance không vượt threshold. | [exact → semantic lookup](../../src/ai-common/techx_ai_common/semantic_cache.py#L209-L278); [hybrid KNN và distance gate](../../src/ai-common/techx_ai_common/semantic_cache.py#L280-L342) | [Cache-enabled replay](../../evidence/a1.3-shopping-cache/04-replay-cache-enabled.jsonl); [summary](../../evidence/a1.3-shopping-cache/07-summary-table.md) |
| TTL | TTL mặc định đọc từ `AI_CACHE_TTL_SECONDS=3600`; mỗi HASH được gắn `EXPIRE` trong cùng pipeline khi store. | [Shopping Copilot cache config](../../src/shopping-copilot/shopping_cache.py#L53-L66); [`HSET` + `EXPIRE`](../../src/ai-common/techx_ai_common/semantic_cache.py#L411-L415) | Hai entry đo được còn `3348 s` và `3456 s`: [Valkey index and TTL](../../evidence/a1.3-shopping-cache/02-valkey-index-and-ttl.txt); [store/expire unit test](../../src/ai-common/tests/test_semantic_cache.py#L335-L353) |
| Invalidation | Trước lookup, Copilot hash stable conversation state, memory fingerprint và catalog/review snapshot hiện tại. `source_hash` tham gia exact key, được kiểm tra lại trên exact hit và là filter bắt buộc của KNN. Source đổi làm request miss logic; entry cũ chờ TTL hết hạn. | [`compute_source_snapshot()`](../../src/shopping-copilot/shopping_cache.py#L111-L192); [snapshot được tạo trước lookup](../../src/shopping-copilot/shopping_cache.py#L195-L223); [exact source check và KNN source filter](../../src/ai-common/techx_ai_common/semantic_cache.py#L246-L299) | Catalog/review đổi làm snapshot đổi: [Shopping cache test](../../src/shopping-copilot/tests/test_shopping_cache.py#L280-L326). Source hash khác tạo exact key khác và stale hash bị reject: [shared cache tests](../../src/ai-common/tests/test_semantic_cache.py#L105-L113), [mismatch test](../../src/ai-common/tests/test_semantic_cache.py#L202-L220). Live source-mutation replay vẫn cần bổ sung. |
| Cacheable output | Chỉ state `GROUNDED`, `cache_eligible`, không có pending action, có conversation và là read-only question mới được store. Shared adapter kiểm tra lại status trước persistence. | [Copilot store gate](../../src/shopping-copilot/shopping_cache.py#L304-L332); [shared GROUNDED gate](../../src/ai-common/techx_ai_common/semantic_cache.py#L344-L365) | Grounded discovery được lưu và hit: [cache-enabled replay](../../evidence/a1.3-shopping-cache/04-replay-cache-enabled.jsonl); [grounded store test](../../src/ai-common/tests/test_semantic_cache.py#L335-L353) |
| Never cached | Anonymous/missing identity, cart mutation, pending action, tool error hoặc status khác `GROUNDED` đều bypass hoặc không store. Replay hiện tại chứng minh riêng `NO_RESULTS` không được lưu. | [lookup bypass và action policy](../../src/shopping-copilot/shopping_cache.py#L45-L108); [Copilot store rejection](../../src/shopping-copilot/shopping_cache.py#L304-L317); [shared status rejection](../../src/ai-common/techx_ai_common/semantic_cache.py#L355-L368) | [Non-cacheable replay](../../evidence/a1.3-shopping-cache/03-replay-non-cacheable.jsonl); [cart/tool-error tests](../../src/shopping-copilot/tests/test_shopping_cache.py#L203-L242); [abstained test](../../src/ai-common/tests/test_semantic_cache.py#L355-L370) |

#### Invalidation hoạt động như thế nào?

Implementation dùng **logical invalidation theo version**, không xóa tất cả key
ngay khi source thay đổi:

1. Trước mỗi lookup, Shopping Copilot đọc state ổn định của conversation, memory
   liên quan, catalog và review của các product liên quan rồi tạo `source_hash`.
2. Exact key chứa `source_hash`. Khi source đổi, hash mới tạo ra key mới nên
   entry cũ không thể exact hit. Code còn so sánh `stored_source == source_hash`
   như một lớp kiểm tra phòng thủ.
3. Semantic lookup bắt buộc filter `@source_hash:{current_hash}` cùng user,
   conversation/resource, prompt, model và embedding scope. Vì vậy một vector
   gần về ngữ nghĩa nhưng thuộc source cũ vẫn bị loại trước khi xét distance.
4. Entry cũ không còn được đọc nhưng vẫn có thể tồn tại vật lý cho tới khi TTL
   hết hạn. Cách này tránh phải scan/delete hàng loạt key trong request path.

Unit test đã chứng minh thay đổi catalog hoặc review làm snapshot đổi, source hash
khác tạo deterministic key khác và exact record có stale hash bị reject. Phần còn
thiếu là live replay sửa một source record thật rồi chụp `miss` cùng response mới;
đó là thiếu artifact runtime, không phải thiếu logic invalidation trong code.

### 4.4 Verification Source Record

Đây là bản ghi được chọn để đội chạy invalidation replay và để người review có thể
sửa an toàn khi cần xác minh lại.

| Field | Value |
|---|---|
| Service/store | `[TODO]` |
| Record ID | `[TODO: stable ID]` |
| Field có thể sửa khi xác minh | `[TODO]` |
| Giá trị gốc | `[TODO]` |
| Test value / giá trị mới phải xuất hiện trong answer | `[TODO]` |
| Lệnh sửa và restore | `[TODO]` |

## 5. Replay and Reproduction

Replay là cửa kiểm chứng dùng cùng input contract cho mọi case. Nó cho phép người chạy tự
chọn request, user và session thay vì dựa vào câu trả lời được seed sẵn. Vì vậy mentor có
thể lặp lại một request để quan sát hit, đổi source record để buộc miss, hoặc thay identity
để kiểm tra isolation mà không cần hiểu implementation nội bộ.

### 5.1 Replay Schema and Contract

Team cung cấp một replay entry point có thể gọi từ bên ngoài. Không được pre-seed
answer: cache hit phải là kết quả của một request thật trước đó.

**Input**

```json
{
  "request": "Find an option under $150",
  "user_id": "mentor-user-a",
  "session_id": "88888888-8888-4888-8888-888888888888"
}
```

**Response Fields**

```json
{
  "sequence": 1,
  "request": "Find an option under $150",
  "user_id": "mentor-user-a",
  "session_id": "88888888-8888-4888-8888-888888888888",
  "status": "GROUNDED",
  "cache": "hit",
  "cache_status": "hit",
  "cache_match": "exact",
  "cache_distance": 0.0,
  "latency_ms": 12.4,
  "product_ids": ["[product-id]"]
}
```

`cache` luôn nhận một trong hai giá trị `hit` hoặc `miss`. `cache_match` có thể
nhận `exact`, `semantic` hoặc `none`. `cache_status` được giữ lại để tương thích
với evidence cũ và luôn có cùng giá trị với `cache`.

> **Contract gap:** raw replay ngày `2026-07-29` trong
> `03-replay-non-cacheable.jsonl` và `04-replay-cache-enabled.jsonl` mới có
> `cache_status`, chưa có alias literal `cache`. Nếu mentor kiểm tra đúng schema
> trong directive, cần regenerate evidence sau khi replay output bổ sung field
> `cache`.

`session_id` phải là UUID v4 hợp lệ. Service bỏ qua conversation state, cache và
memory khi nhận một giá trị session không hợp lệ; dùng UUID khác khi tạo session mới.

**Entry point:** CLI gọi Shopping Copilot gRPC qua `--host` và `--port`. CLI nhận
`user_id` và `session_id` bên ngoài, rồi map `session_id` thành gRPC
`conversation_id`; mỗi request tự tạo một `turn_id` mới.

**Reproduction command**

Lệnh dưới đây chạy replay bằng input bên ngoài. `--request` có thể lặp lại; mỗi
lần xuất hiện sẽ được thêm thành một phần tử trong request list, theo đúng thứ tự.
Ví dụ này tạo cold miss rồi gửi lại cùng Q để kiểm chứng exact hit.

```powershell
$env:PYTHONPATH = "src/ai-common;src/shopping-copilot;src/product-reviews"

$port = (
  (docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml `
    port shopping-copilot 3552) -split ":"
)[-1]

python src/shopping-copilot/scripts/replay_shopping_cache.py `
  --host localhost --port $port `
  --user-id mentor-user-a `
  --session-id 88888888-8888-4888-8888-888888888888 `
  --request 'Find a portable telescope under $150.' `
  --request 'Find a portable telescope under $150.' `
  --output mandate23-replay.jsonl
```

**Expected output:** Mỗi request tạo một JSONL row gồm `sequence`, `request`,
`user_id`, `session_id`, `status`, `cache`, `cache_status`, `cache_match`,
`cache_distance`, `latency_ms` và `product_ids`. Raw JSONL là bằng chứng cache
flag; nội dung response/source đã đổi phải được chụp ở Scenario A. `model_calls`
và token là metric tổng, không phải field của một replay row. Lệnh invalidation
dùng source record ở mục 4.4 và luôn có bước restore.

**Memory replay pattern:** dùng ba `--request` khác nhau cùng `--user-id` và
`--session-id` cho Scenario B. Chạy lại lệnh với cùng `--user-id` nhưng
`--session-id` mới cho Scenario C; đổi cả `--user-id` lẫn `--session-id` cho
Scenario D.

### 5.2 Evidence Capture Scenarios

Bốn scenario dưới đây là cách team chụp evidence cho ticket. Chúng dùng cùng entry point
ở mục 5.1; mỗi ảnh phải hiển thị input identity, output quan sát được và `cache=hit|miss`
khi cache có liên quan. Raw output và ảnh được đính kèm ngay tại scenario tương ứng.

### Scenario A — Repeated Request and Cache Invalidation

**Mục tiêu:** chứng minh cache hit thật, sau đó chứng minh source freshness.

**Điều kiện bắt đầu:** cache rỗng; source record chỉ định đang có giá trị gốc;
User A và Session A đã sẵn sàng.

| Step | Action | Expected Observable Result |
|---:|---|---|
| 1 | Gửi request Q với User A / Session A | `cache=miss`; response có source value A. |
| 2 | Gửi lại y hệt request Q | `cache=hit`; answer được reuse; model-call count không tăng. |
| 3 | Sửa source record chỉ định từ A sang B | Source mutation thành công. |
| 4 | Gửi lại Q | `cache=miss`; answer có value B, không còn value A. |
| 5 | Restore source record | Test data quay về giá trị ban đầu. |

**Evidence đã có**

- Cold request: `cache_status=miss`, `cache_match=none`, latency
  `88746.88 ms`.
- Exact repeat: `cache_status=hit`, `cache_match=exact`, distance `0`,
  latency `71974.53 ms`, cùng ba product ID với cold request.
- Safe paraphrase: `cache_status=hit`, `cache_match=semantic`, distance
  `0.08469510078430176`, latency `49209.23 ms`, cùng ba product ID.
- Dedicated exact-hit check giữ nguyên Bedrock model-call counter `16 → 16`.
- Valkey có hai entry với TTL dương `3348–3456 s`, gần cấu hình `3600 s`.
- Test suite: `65 passed` trong `29.97 s`.

Raw artifacts:
[cache-enabled replay](../../evidence/a1.3-shopping-cache/04-replay-cache-enabled.jsonl),
[model-call suppression](../../evidence/a1.3-shopping-cache/05-model-call-suppression.txt),
[Valkey/TTL](../../evidence/a1.3-shopping-cache/02-valkey-index-and-ttl.txt),
[metrics snapshot](../../evidence/a1.3-shopping-cache/06-metrics-snapshot.txt),
[test output](../../evidence/a1.3-shopping-cache/01-tests-output.txt) và
[summary table](../../evidence/a1.3-shopping-cache/07-summary-table.md).

![Cold request đi qua cache miss](../../evidence/assets/image6.png)

*Request “Recommend telescope options priced below $150” trả response
grounded. Network response hiển thị `cacheStatus: "miss"`,
`cacheMatch: "none"` và `cacheDistance: 0`, xác nhận cold path chưa reuse cache.*

![Request lặp tạo exact cache hit](../../evidence/assets/image7.png)

*Request giống hệt được gửi lại và trả cùng danh sách sản phẩm. Network
response hiển thị `cacheStatus: "hit"`, `cacheMatch: "exact"` và distance `0`;
artifact model-call suppression xác nhận counter Bedrock không tăng `16 → 16`.*

![Request paraphrase tạo semantic cache hit](../../evidence/assets/image8.png)

*Câu paraphrase “Find telescope options under $150” trả cùng tập sản
phẩm và Network response hiển thị semantic hit với distance khoảng `0.0846951`.*

> **Evidence gap:** các screenshot và raw replay chứng minh cold miss, exact hit,
> semantic hit và model-call suppression. Pack hiện tại chưa có ảnh/live artifact
> cho bước sửa source A → B và restore; vì vậy phần invalidation ở Scenario A
> chưa được đánh dấu hoàn thành.

### Scenario B — Context Across Three Turns

**Mục tiêu:** chứng minh session continuity mà user không phải nhắc lại constraint.

| Turn | Cùng `user_id` và `session_id` | Expected Observable Result |
|---:|---|---|
| 1 | Nêu nhu cầu và durable constraint, ví dụ: “Tôi cần kính thiên văn gọn nhẹ, ngân sách $150.” | Copilot xác nhận hoặc dùng đúng constraint đã nêu. |
| 2 | Hỏi theo ngữ cảnh, ví dụ: “Tìm lựa chọn phù hợp với nhu cầu đó.” | Copilot áp dụng nhu cầu và mức $150 mà không hỏi lại. |
| 3 | Tham chiếu kết quả trước, ví dụ: “So sánh sản phẩm đầu tiên với lựa chọn khác.” | Copilot hiểu “sản phẩm đầu tiên” từ đúng session. |

![Ba lượt hội thoại phụ thuộc ngữ cảnh](../../evidence/assets/image1.png)

*User nêu nhu cầu astronomy gear cho camping, cần portable, quan sát
planet và ngân sách `$200`; lượt sau hỏi hệ thống nhớ gì và Copilot nhắc lại
đúng các constraint; lượt tiếp theo “Find an option for me” dùng context đó để
đưa ra Red Flashlight giá `$57.08`.*

![Tham chiếu this product trong cùng hội thoại](../../evidence/assets/image2.png)

*Sau khi Red Flashlight được chọn ở lượt trước, câu “Show me this product
in detail” được resolve đúng sang Red Flashlight và trả tên, giá `$57.08` cùng
mô tả chi tiết mà user không phải nhắc lại product name.*

![Recall chủ đề trong cùng conversation](../../evidence/assets/image9.png)

*Sau yêu cầu tìm telescope dưới `$150`, user hỏi “what do you remember
about my shopping needs?”. Copilot nhận ra đúng chủ đề telescope từ conversation
hiện tại. Ảnh này hỗ trợ session continuity; nó không hiển thị `user_id` hoặc
`session_id`, nên identity contract vẫn cần raw replay nếu dùng để chấm tự động.*

### Scenario C — Durable Recall in a New Session

**Mục tiêu:** chứng minh durable memory được phép lưu vẫn tồn tại qua ranh giới
session.

| Step | Action | Expected Observable Result |
|---:|---|---|
| 1 | Khởi tạo Session B với cùng User A | Session B có `session_id` mới. |
| 2 | Hỏi lựa chọn mà không nhắc lại durable preference/constraint | Copilot truy hồi và áp dụng đúng fact được phép từ Session A. |
| 3 | Xác nhận temporary reference của Session A không tồn tại | Copilot không xem “sản phẩm đầu tiên” của Session A là đã biết ở Session B. |

![Lưu durable budget preference](../../evidence/assets/image3.png)

*Ở conversation ban đầu, user yêu cầu ghi nhớ maximum budget cho telescope
là `$110`; Copilot xác nhận đã ghi nhận constraint này cho các lần tìm kiếm sau.*

![Recall budget ở conversation mới](../../evidence/assets/image4.png)

*Conversation “Show me telescope options” được mở riêng và user không
nhắc lại `$110`; Copilot vẫn lọc kết quả trong ngân sách, trả Solar Filter
`$69.95` và National Park Foundation Explorascope `$101.96`.*


> **Evidence gap:** các screenshot store/recall trên UI không hiển thị UUID
> session hoặc user identity. Cần raw replay
> với cùng `user_id`, session A/B khác nhau để dùng làm bằng chứng máy kiểm tra.

### Scenario D — Cross-User Isolation and PII Boundary

**Mục tiêu:** chứng minh User B không thể đọc dữ liệu của User A.

| Step | Action | Expected Observable Result |
|---:|---|---|
| 1 | User B gửi cùng request của User A | Không reuse cache entry của User A; `cache=miss` khi phù hợp. |
| 2 | User B hỏi preference của User A | Không trả User-A memory hoặc private data. |
| 3 | Gửi một fact có PII | Fact bị reject hoặc sanitize theo policy và không xuất hiện khi recall sau đó. |

> **Screenshot D — [TODO: đính kèm ảnh cross-user và PII boundary]**
>
> *Caption: User B không nhận cache response, durable memory hoặc PII của User A;
> fact có PII bị reject hoặc sanitize theo policy.*

## 6. Decisions, Ownership, and References

Mục này ghi lại ai chịu trách nhiệm cho implementation và các quyết định không được thay
đổi âm thầm sau khi evidence đã được chụp. Phần ADR bên dưới là record ký trực tiếp trên
Jira; các link kỹ thuật chỉ giải thích cách implementation thực hiện các quyết định đó.

**Implementation PR:** [tf2-team/tf2-corp-platform#140](https://github.com/tf2-team/tf2-corp-platform/pull/140)
**Commit:** `[TODO]`
**Design owner:** `[TODO]`
**Reviewers/sign-off date:** `[TODO]`

### 6.1 ADR Record and Sign-off

| Decision | Status | Sign-off |
|---|---|---|
| Cache key luôn chứa user boundary, source version và TTL; hit không gọi model. | `Accepted` | `[TODO: name, date]` |
| Session context dùng `user_id + session_id`; durable memory chỉ truy hồi trong cùng `user_id`. | `Accepted` | `[TODO: name, date]` |
| Chỉ durable fact được policy cho phép mới được lưu; PII bị reject hoặc sanitize trước persistence. | `Accepted` | `[TODO: name, date]` |

### 6.2 Technical References

- [Shared semantic cache guide](caching/semantic-cache-implementation-guide.md)
- [Shopping Copilot cache runbook](caching/shopping-copilot-dod-evidence-runbook.md)
- [Shopping Copilot Mem0 integration](memory/shopping-copilot-mem0-integration-plan.md)
- [Directive #23 — normative requirement](MANDATE-23-genai-caching-memory.md)
