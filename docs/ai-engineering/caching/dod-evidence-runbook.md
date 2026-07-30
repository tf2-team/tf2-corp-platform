# A1.3 DoD Evidence Pack — Summary Bot Hybrid Cache

**Status:** Measured evidence
**Date:** 2026-07-27
**Surface:** Review Summary (`product-reviews`) hybrid cache (exact + semantic KNN on Valkey)
**Model (miss path):** Amazon Bedrock `us.amazon.nova-2-lite-v1:0` · region `us-east-1` · `LLM_PROVIDER=bedrock`
**Cache config at measure time:**

```text
AI_CACHE_ENABLED=true          # false only during baseline run
AI_CACHE_ADDR=valkey-ai-cache:6379
AI_CACHE_TTL_SECONDS=3600
AI_CACHE_MAX_DISTANCE=0.40
AI_CACHE_USER_HMAC_SECRET=local-only-cache-scope-secret
```

**Compose:** `docker-compose.yml` + `docker-compose.ai-dev.yml`
**Replay tool:** `src/product-reviews/scripts/replay_summary_cache.py`
**Artifact root:** [`evidence/a1.3-cache/`](../../../evidence/a1.3-cache/)

---

## 1. Gói artifact (nộp kèm)

| # | File | Mục đích DoD |
|---|---|---|
| 01 | [01-tests-output.txt](../../../evidence/a1.3-cache/01-tests-output.txt) | Unit/integration logic (HMAC, source_hash, exact/semantic, fail-open, store GROUNDED only) |
| 02 | [02-valkey-index.txt](../../../evidence/a1.3-cache/02-valkey-index.txt) | Valkey sống + RediSearch index `ai_summary_cache_idx` |
| 03 | [03-replay-baseline.jsonl](../../../evidence/a1.3-cache/03-replay-baseline.jsonl) | Baseline: cache OFF — mọi request miss, gọi model |
| 04 | [04-replay-cache-enabled.jsonl](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | **Bằng chứng chính:** exact hit, semantic hit, product/user isolation, anonymous bypass |
| 07 | [07-summary-table.md](../../../evidence/a1.3-cache/07-summary-table.md) | Bảng so sánh baseline vs cache + latency / model-call proxy |
| 08 | [08-ttl-check.txt](../../../evidence/a1.3-cache/08-ttl-check.txt) | Mỗi entry cache có TTL ~3600s |
| 09 | [09-fail-open.txt](../../../evidence/a1.3-cache/09-fail-open.txt) | Valkey down → service vẫn trả lời, không crash |
| 10 | [10-source-invalidation.txt](../../../evidence/a1.3-cache/10-source-invalidation.txt) | Review đổi → source_hash đổi → cache miss |

Optional (không bắt buộc trong gói này): Grafana scrape `05`/`06`, screenshots `11/`.

---

## 2. Ma trận DoD → PASS

| # | Definition of Done | Artifact | Cách đọc bằng chứng | PASS? |
|---|---|---|---|---|
| 1 | Lặp request → hit, không gọi model lần 2 | [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | `user_alice` + `OLJCESPC7Z` + cùng question: `attempt=1` → `miss`; `attempt=2` → `hit` + `exact`. Latency hit ~1.5s vs miss ~4–18s | **PASS** |
| 2 | Paraphrase → semantic hit | [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | `"What do customers think about this product?"` → `hit` + `semantic`, `cache_distance≈0.349` ≤ `0.40` | **PASS** |
| 3 | Khác product → miss | [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | Cùng question, `product_id=L9ECAV7KIM` → `miss` | **PASS** |
| 4 | User khác → miss (isolation) | [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | Cùng product+question, `user_bob` → `miss` | **PASS** |
| 5 | Anonymous không share cache | [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | `anonymous` × 2 → cả hai `miss` | **PASS** |
| 6 | Review đổi → miss | [10](../../../evidence/a1.3-cache/10-source-invalidation.txt) | A=`miss`, B=`hit exact`, SQL UPDATE, D=`miss` | **PASS** |
| 7 | Entry có TTL | [08](../../../evidence/a1.3-cache/08-ttl-check.txt) | 3 keys `ai:cache:summary:*`, TTL 3556–3567 ≈ 3600 | **PASS** |
| 8 | Valkey down fail-open | [09](../../../evidence/a1.3-cache/09-fail-open.txt) + unit [01](../../../evidence/a1.3-cache/01-tests-output.txt) | `VALKEY_DOWN` → `GROUNDED`, `cache_status=miss`, không crash | **PASS** |
| 9 | Replay có `cache_status` | [03](../../../evidence/a1.3-cache/03-replay-baseline.jsonl), [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) | Mọi dòng JSONL có `cache_status`, `cache_match`, `latency_ms` | **PASS** |
| 10 | Bảng baseline vs cache | [07](../../../evidence/a1.3-cache/07-summary-table.md) | Hit-rate 0% → 28.6%; model-call proxy 7 → 5; hit ~5× nhanh hơn miss | **PASS** |

---

## 3. Môi trường & lệnh chuẩn bị

Working directory: root repo `tf2-corp-platform`.

### 3.1 Start stack

```powershell
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml up -d `
  valkey-ai-cache ai-cache-bootstrap postgresql product-catalog product-reviews
```

**Kết quả:** containers `valkey-ai-cache` (healthy), `product-reviews`, `postgresql`, `product-catalog` Up.
Index bootstrap tạo `ai_summary_cache_idx` (và `ai_copilot_cache_idx` nếu có).

### 3.2 Lấy port host của product-reviews (không hardcode)

```powershell
$port = ((docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml port product-reviews 3551) -split ":")[-1]
Write-Host "PRODUCT_REVIEWS host port = $port"
```

Port đo lần này thay đổi sau mỗi recreate (ví dụ `64676` baseline, `64827` cache-on). Luôn lấy lại bằng lệnh trên.

### 3.3 Env cache (`.env`)

```text
AI_CACHE_ENABLED=true|false   # theo bước
AI_CACHE_MAX_DISTANCE=0.40
AI_CACHE_TTL_SECONDS=3600
AWS_PROFILE / Bedrock creds đã map volume ~/.aws → container
```

Sau khi đổi `AI_CACHE_ENABLED`:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml up -d --force-recreate product-reviews
# chờ ~40–50s model load
```

---

## 4. Evidence chi tiết:

### 4.1 Unit tests → `01-tests-output.txt`

**Validation Goal:** Logic cache đúng ở tầng code (HMAC user scope, source_hash, exact/semantic threshold, fail-open mock Valkey, chỉ store GROUNDED).

**Command:**

```powershell
$env:PYTHONPATH = "src/ai-common;src/product-reviews"
python -m pytest `
  src/ai-common/tests/test_semantic_cache.py `
  src/product-reviews/tests/test_summary_cache.py -v `
  | Tee-Object evidence/a1.3-cache/01-tests-output.txt
```

**Output kỳ vọng / thực tế:** pytest PASS (32+ cases), gồm `TestUserScope`, `TestComputeSourceHash`, `TestExactLookup`, `TestSemanticKNNLookup`, `TestFailOpen`, …

**File:** [01-tests-output.txt](../../../evidence/a1.3-cache/01-tests-output.txt)

---

### 4.2 Valkey + index → `02-valkey-index.txt`

**Validation Goal:** Backend cache sẵn sàng; RediSearch index semantic tồn tại.

**Command:**

```powershell
docker exec valkey-ai-cache valkey-cli PING `
  | Out-File evidence/a1.3-cache/02-valkey-index.txt -Encoding utf8
docker exec valkey-ai-cache valkey-cli FT._LIST `
  | Out-File evidence/a1.3-cache/02-valkey-index.txt -Append -Encoding utf8
docker exec valkey-ai-cache valkey-cli INFO keyspace `
  | Out-File evidence/a1.3-cache/02-valkey-index.txt -Append -Encoding utf8
```

**Output thực tế (rút gọn):**

```text
PONG
ai_copilot_cache_idx
ai_summary_cache_idx
# Keyspace
db0:keys=3,expires=3,avg_ttl=3567622,...
```

**File:** [02-valkey-index.txt](../../../evidence/a1.3-cache/02-valkey-index.txt)

---

### 4.3 Baseline cache OFF → `03-replay-baseline.jsonl`

**Validation Goal:** Khi tắt cache, **không có hit**; mọi request đi miss path (gọi Bedrock). Đây là mốc so sánh cost/latency.

**Command:**

```powershell
# .env: AI_CACHE_ENABLED=false  → force-recreate product-reviews, đợi healthy
$port = ((docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml port product-reviews 3551) -split ":")[-1]
$env:PYTHONPATH = "src/ai-common;src/product-reviews"
python src/product-reviews/scripts/replay_summary_cache.py `
  --host localhost --port $port `
  --output evidence/a1.3-cache/03-replay-baseline.jsonl
```

**Stdout tóm tắt (thực tế):**

```text
Total requests:        7
Cache hits:            0  (0.0%)
Cache misses:          7
Mean latency (all):    ~5160 ms
```

**JSONL:** 7 dòng, mỗi dòng `cache_status=miss`.
**File:** [03-replay-baseline.jsonl](../../../evidence/a1.3-cache/03-replay-baseline.jsonl)

---

### 4.4 Cache ON + cache rỗng → `04-replay-cache-enabled.jsonl` (bằng chứng chính)

**Validation Goal:** Exact hit, semantic hit, isolation product/user, anonymous bypass — đúng contract A1.3.

**Quy trình quan trọng (tránh cache bẩn / mất index):**

```powershell
# .env: AI_CACHE_ENABLED=true, AI_CACHE_MAX_DISTANCE=0.40
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml up -d --force-recreate product-reviews
# đợi ~50s

# Xóa data + TẠO LẠI index (FLUSHDB xóa cả index RediSearch)
docker exec valkey-ai-cache valkey-cli FLUSHDB
docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml up ai-cache-bootstrap

$port = ((docker compose -f docker-compose.yml -f docker-compose.ai-dev.yml port product-reviews 3551) -split ":")[-1]
$env:PYTHONPATH = "src/ai-common;src/product-reviews"
python src/product-reviews/scripts/replay_summary_cache.py `
  --host localhost --port $port `
  --output evidence/a1.3-cache/04-replay-cache-enabled.jsonl
```

**Stdout tóm tắt (thực tế):**

```text
[ miss] user_alice  attempt=1  match=none      ~18707 ms  "Is this product good?"
[  hit] user_alice  attempt=2  match=exact     ~ 1531 ms  "Is this product good?"
[  hit] user_alice  attempt=1  match=semantic  ~ 1461 ms  "What do customers think..."
[ miss] product=L9ECAV7K                 match=none      ~ 4735 ms  (khác product)
[ miss] user_bob                         match=none      ~ 4535 ms  (user isolation)
[ miss] anonymous × 2                    match=none      (bypass)

Cache hits:     2  (28.6%)  — exact: 1, semantic: 1
Cache misses:   5
Mean hit:    ~1496 ms
Mean miss:   ~7641 ms
```

**Cách chứng minh từng dòng DoD trong JSONL:**

| Scenario trong script | Dòng kỳ vọng | Kết quả đo |
|---|---|---|
| Cùng user/product/question × 2 | attempt1 miss, attempt2 hit exact | **Đúng** |
| Paraphrase | hit + semantic + distance ∈ (0, 0.40] | **Đúng** (`0.349…`) |
| Product khác | miss | **Đúng** |
| User khác | miss | **Đúng** |
| anonymous × 2 | miss, không share | **Đúng** |

**File:** [04-replay-cache-enabled.jsonl](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl)

**Giải thích “không gọi model khi hit”:**
Hit path latency ~1.5s vs miss ~4–18s. Miss path gọi Bedrock thật (volume AWS credentials). Hit path trả từ Valkey; model-call proxy trên set 7 request: 7 → 5 (giảm 2 lời gọi tương ứng 2 hits). Chi tiết bảng: [07-summary-table.md](../../../evidence/a1.3-cache/07-summary-table.md).

---

### 4.5 TTL → `08-ttl-check.txt`

**Validation Goal:** Mỗi entry được set expire; không cache vĩnh viễn.

**Lệnh (sau khi đã có store từ replay cache-on):**

```powershell
docker exec valkey-ai-cache valkey-cli --scan --pattern "ai:cache:summary:*"
# với mỗi key:
docker exec valkey-ai-cache valkey-cli TTL "ai:cache:summary:<sha...>"
```

**Output thực tế:**

```text
KEY=ai:cache:summary:8117b915... TTL=3556
KEY=ai:cache:summary:15799d89... TTL=3563
KEY=ai:cache:summary:839cc8e1... TTL=3567
# AI_CACHE_TTL_SECONDS=3600 → TTL > 0 và ≈ 3600
```

**File:** [08-ttl-check.txt](../../../evidence/a1.3-cache/08-ttl-check.txt)

---

### 4.6 Fail-open → `09-fail-open.txt`

**Validation Goal:** Valkey lỗi/stop → Summary Bot vẫn trả lời (GROUNDED/ABSTAINED/…), không 500/crash; cache fail-open thành miss.

**Command:**

```powershell
# 1) Request khi Valkey healthy (gRPC AskProductAIAssistant)
# 2) docker stop valkey-ai-cache
# 3) Request lại cùng product/question (user khác để không phụ thuộc exact key)
# 4) docker start valkey-ai-cache
# 5) docker compose ... up ai-cache-bootstrap
```

**Output thực tế:**

```text
BEFORE_STOP ok  cache_status=miss response_status=GROUNDED latency_ms=5493.2
VALKEY_DOWN ok  cache_status=miss response_status=GROUNDED latency_ms=11381.5
preview=Perfect for camping trips...   # vẫn có answer, không crash
RESTORED: valkey + bootstrap done
```

**File:** [09-fail-open.txt](../../../evidence/a1.3-cache/09-fail-open.txt)
**Bổ sung unit:** `TestFailOpen` trong [01-tests-output.txt](../../../evidence/a1.3-cache/01-tests-output.txt).

---

### 4.7 Source invalidation → `10-source-invalidation.txt`

**Validation Goal:** Đổi review nguồn → `source_hash` đổi → không tái sử dụng answer cũ (miss sau khi trước đó đã hit).

**Command:**

```powershell
# 0) FLUSHDB + ai-cache-bootstrap (cache sạch)
# 1) Ask (user_invalidation, OLJCESPC7Z, "Is this product good?") → miss + store
# 2) Ask y hệt → hit exact
# 3) SQL:
docker exec postgresql psql -U root -d otel -c "
UPDATE reviews.productreviews
SET description = LEFT(description || ' [edited for cache invalidation test]', 1024)
WHERE id = (
  SELECT id FROM reviews.productreviews
  WHERE product_id = 'OLJCESPC7Z' ORDER BY id LIMIT 1
);
"
# 4) Ask y hệt → miss
```

**Output thực tế:**

```text
STEP_A_FIRST       cache_status=miss  response_status=GROUNDED
STEP_B_HIT         cache_status=hit   cache_match=exact
STEP_C             UPDATE 1  (description tail chứa [edited INV...])
STEP_D_AFTER_EDIT  cache_status=miss  response_status=GROUNDED
```

**File:** [10-source-invalidation.txt](../../../evidence/a1.3-cache/10-source-invalidation.txt)

---

### 4.8 Bảng so sánh → `07-summary-table.md`

**Validation Goal:** Tổng hợp số liệu baseline vs cache-enabled cho handoff (hit-rate, latency, proxy model calls).

**Nguồn số:** parse [03](../../../evidence/a1.3-cache/03-replay-baseline.jsonl) + [04](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl).

| Metric | Baseline OFF | Cache ON | Ghi chú |
|---|---:|---:|---|
| Requests | 7 | 7 | cùng scenario set |
| Cache hits | 0 | 2 | 1 exact + 1 semantic |
| Hit-rate | 0% | 28.6% | |
| Misses | 7 | 5 | |
| Mean latency hit (ms) | — | 1495.9 | skip LLM |
| Mean latency miss (ms) | 5160.3 | 7640.8 | Bedrock |
| Model-call proxy | 7 | 5 | −28.6% invocations trên set này |

**File đầy đủ:** [07-summary-table.md](../../../evidence/a1.3-cache/07-summary-table.md)

**Cost USD:** JSONL không log token. Proxy = số miss (= số lần miss path gọi model). Để điền USD mentor, nhân token metrics (nếu scrape Prometheus/Grafana) với Bedrock price card `us.amazon.nova-2-lite-v1:0` / `us-east-1`.

---

## 5. Scenario map của replay script

Script: [`src/product-reviews/scripts/replay_summary_cache.py`](../../../src/product-reviews/scripts/replay_summary_cache.py)

| # | product_id | question | user_id | repeats | DoD |
|---|---|---|---|---|---|
| 1 | `OLJCESPC7Z` | Is this product good? | user_alice | 2 | exact hit lần 2 |
| 2 | `OLJCESPC7Z` | What do customers think about this product? | user_alice | 1 | semantic hit |
| 3 | `L9ECAV7KIM` | Is this product good? | user_alice | 1 | khác product → miss |
| 4 | `OLJCESPC7Z` | Is this product good? | user_bob | 1 | user isolation → miss |
| 5 | `OLJCESPC7Z` | How is the quality? | anonymous | 2 | bypass, không share |

Mỗi dòng JSONL có: `product_id`, `question`, `user_id`, `attempt`, `cache_status`, `cache_match`, `cache_distance`, `response_status`, `latency_ms`, `answer_preview`.

---

## 6. Lưu ý tái tạo (pitfalls đã gặp & đã xử lý)

| Hiện tượng | Nguyên nhân | Cách xử lý trong evidence run |
|---|---|---|
| Toàn `[error]` | Port host đổi sau recreate | Luôn `docker compose port product-reviews 3551` |
| Semantic luôn miss dù distance OK | `FLUSHDB` xóa index; hoặc query KNN lỗi | Sau FLUSHDB luôn `up ai-cache-bootstrap`; code KNN không dùng `SORTBY dist` thừa |
| Toàn `hit exact` kể cả user_bob | Cache bẩn từ run trước | FLUSHDB + bootstrap **trước** đo `04` |
| Sửa Python nhưng container không đổi | Không hot-reload image | `--force-recreate` / `docker restart product-reviews` |
| Semantic distance ~0.35 | Threshold 0.12 quá chặt | Đo với `AI_CACHE_MAX_DISTANCE=0.40` (ghi rõ trong bảng) |

---

## 7. Checklist
- [x] [01-tests-output.txt](../../../evidence/a1.3-cache/01-tests-output.txt) — pytest xanh
- [x] [02-valkey-index.txt](../../../evidence/a1.3-cache/02-valkey-index.txt) — PONG + `ai_summary_cache_idx`
- [x] [03-replay-baseline.jsonl](../../../evidence/a1.3-cache/03-replay-baseline.jsonl) — 0% hit
- [x] [04-replay-cache-enabled.jsonl](../../../evidence/a1.3-cache/04-replay-cache-enabled.jsonl) — exact + semantic + isolation
- [x] [07-summary-table.md](../../../evidence/a1.3-cache/07-summary-table.md) — bảng so sánh
- [x] [08-ttl-check.txt](../../../evidence/a1.3-cache/08-ttl-check.txt) — TTL ≈ 3600
- [x] [09-fail-open.txt](../../../evidence/a1.3-cache/09-fail-open.txt) — fail-open runtime
- [x] [10-source-invalidation.txt](../../../evidence/a1.3-cache/10-source-invalidation.txt) — source_hash invalidation
