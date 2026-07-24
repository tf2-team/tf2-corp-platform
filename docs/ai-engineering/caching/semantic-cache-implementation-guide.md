# Valkey 9.0 Semantic Cache Implementation Guide

Tài liệu này hướng dẫn triển khai semantic cache bằng Amazon ElastiCache for
Valkey 9.0 cho hai service:

- `product-reviews`: cache câu trả lời của Product Reviews AI Assistant.
- `shopping-copilot`: cache các kết quả AI chỉ đọc, đặc biệt là review Q&A.

Hai bot dùng chung một Valkey cluster dành riêng cho AI, nhưng dùng index và
key prefix khác nhau. Không thay đổi cluster `valkey-cart` và không thay
`VALKEY_ADDR` đang được cart, rate limiter và pending cart action sử dụng.

## 1. Implementation Order

Thực hiện theo thứ tự sau:

1. Chạy Valkey Search 9.0 riêng trong môi trường local.
2. Tạo ElastiCache Valkey 9.0 riêng trong `tf2-corp-infra`.
3. Đồng bộ endpoint và password vào hai bot qua `tf2-corp-chart`.
4. Viết một semantic cache adapter trong `src/ai-common`.
5. Tích hợp `product-reviews` và hoàn thành kiểm thử.
6. Tái sử dụng adapter cho `shopping-copilot`.
7. Thêm cache metadata, replay API và metrics.

Không triển khai hai bot song song. Hoàn thành và đo được `product-reviews`
trước, sau đó mới tích hợp `shopping-copilot`.

## 2. Change Map

Các thay đổi tập trung ở những file sau:

| Repository | File | Change |
|---|---|---|
| `tf2-corp-platform` | `.env` | Thêm image và cấu hình AI cache local |
| `tf2-corp-platform` | `docker-compose.yml` | Thêm service `valkey-ai-cache` |
| `tf2-corp-platform` | `src/ai-common/techx_ai_common/semantic_cache.py` | Adapter dùng chung |
| `tf2-corp-platform` | `src/ai-common/techx_ai_common/retrieval.py` | Dùng lại embedding model hiện có |
| `tf2-corp-platform` | `src/product-reviews/product_reviews_server.py` | Lookup/store Summary cache |
| `tf2-corp-platform` | `src/shopping-copilot/intent_parser.py` | Cache intent read-only |
| `tf2-corp-platform` | `src/shopping-copilot/review_tool.py` | Cache review-grounded answer |
| `tf2-corp-platform` | `src/shopping-copilot/copilot_graph.py` | Truyền cache metadata |
| `tf2-corp-platform` | `src/shopping-copilot/copilot_server.py` | Trả cache metadata |
| `tf2-corp-platform` | `pb/demo.proto` | Thêm cache metadata vào response |
| `tf2-corp-platform` | `src/frontend/pages/api/ai/replay.ts` | Cửa replay cho hai bot |
| `tf2-corp-infra` | `modules/ai-cache/*` | ElastiCache Valkey 9.0 riêng |
| `tf2-corp-infra` | `environments/production/*` | Khởi tạo module và export output |
| `tf2-corp-chart` | `values.yaml`, `values-prod.yaml` | Inject `AI_CACHE_*` |
| `tf2-corp-chart` | `secrets-chart/*` | Đồng bộ password và HMAC secret |

Không tạo thêm cache service riêng cho từng bot. Một cluster và một shared
adapter là đủ; sự cô lập nằm ở index, prefix và filter.

## 3. Local Search Runtime

Image `valkey/valkey:9.0.1-alpine3.23` hiện tại không kèm Valkey Search module.
Giữ image này cho `valkey-cart`. Thêm image bundle riêng trong `.env`:

```dotenv
AI_CACHE_IMAGE=valkey/valkey-bundle:9.0.4-alpine
AI_CACHE_ADDR=valkey-ai-cache:6379
AI_CACHE_ENABLED=true
AI_CACHE_TLS=false
AI_CACHE_TTL_SECONDS=3600
AI_CACHE_MAX_DISTANCE=0.12
AI_CACHE_USER_HMAC_SECRET=local-only-cache-scope-secret
```

Thêm service vào `docker-compose.yml`:

```yaml
services:
  valkey-ai-cache:
    image: ${AI_CACHE_IMAGE}
    container_name: valkey-ai-cache
    restart: unless-stopped
    ports:
      - "6380:6379"
    volumes:
      - valkey-ai-cache-data:/data
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  valkey-ai-cache-data:
```

Inject các biến `AI_CACHE_*` vào `product-reviews` và `shopping-copilot`.
Không đổi biến `VALKEY_ADDR` của hai service vì biến đó đang phục vụ rate
limiter và pending cart action.

Khởi động và xác nhận Search module:

```powershell
docker compose up ai-cache-bootstrap
docker exec valkey-ai-cache valkey-cli INFO modules
docker exec valkey-ai-cache valkey-cli FT._LIST
```

`ai-cache-bootstrap` tạo idempotent hai index `ai_summary_cache_idx` và
`ai_copilot_cache_idx`; member không cần chạy script thủ công. Kết quả
`INFO modules` phải có `module:name=search`. Nếu `FT._LIST` trả
`unknown command`, container đang dùng nhầm image `valkey/valkey`.

## 4. Production Infrastructure

Tạo module mới `tf2-corp-infra/modules/ai-cache`. Không sửa resource
`aws_elasticache_replication_group.cart` trong `modules/commerce-ha`.

### 4.1 Module Inputs

Tạo `modules/ai-cache/variables.tf`:

```hcl
variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "eks_client_security_group_id" {
  type = string
}

variable "node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

### 4.2 Module Resources

Tạo `modules/ai-cache/main.tf` với các resource tối thiểu:

```hcl
resource "aws_kms_key" "this" {
  description             = "Encrypt AI semantic cache for ${var.name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = var.tags
}

resource "random_password" "auth" {
  length  = 48
  special = false
}

resource "random_password" "user_hmac" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "auth" {
  name                    = "${var.name}/ai-cache"
  recovery_window_in_days = 7
  kms_key_id              = aws_kms_key.this.arn
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "auth" {
  secret_id = aws_secretsmanager_secret.auth.id
  secret_string = jsonencode({
    password         = random_password.auth.result
    user_hmac_secret = random_password.user_hmac.result
  })
}

resource "aws_security_group" "this" {
  name   = "${var.name}-ai-cache"
  vpc_id = var.vpc_id

  ingress {
    protocol        = "tcp"
    from_port       = 6379
    to_port         = 6379
    security_groups = [var.eks_client_security_group_id]
  }

  tags = var.tags
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-ai-cache"
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

resource "aws_elasticache_parameter_group" "this" {
  name   = "${var.name}-ai-cache-valkey9"
  family = "valkey9"

  parameter {
    name  = "reserved-memory-percent"
    value = "30"
  }

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  tags = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name}-ai-cache"
  description          = "Valkey 9 semantic cache for AI services"

  engine               = "valkey"
  engine_version       = "9.0"
  node_type            = var.node_type
  port                 = 6379
  parameter_group_name = aws_elasticache_parameter_group.this.name

  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.this.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.auth.result
  auth_token_update_strategy = "SET"

  apply_immediately = true
  tags              = var.tags
}
```

`cache.t4g.small` cần `reserved-memory-percent=30` khi dùng Search. Không dùng
node có data tiering. Nếu load test cho thấy thiếu memory, tăng node type thay
vì giảm memory reserve.

### 4.3 Module Outputs

Tạo `modules/ai-cache/outputs.tf`:

```hcl
output "primary_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "auth_secret_arn" {
  value = aws_secretsmanager_secret.auth.arn
}
```

### 4.4 Production Wiring

Trong `environments/production/main.tf`, khởi tạo module:

```hcl
module "ai_cache" {
  source = "../../modules/ai-cache"

  name                         = var.project_name
  vpc_id                       = module.vpc.vpc_id
  private_subnet_ids           = module.vpc.private_subnet_ids_list
  eks_client_security_group_id = module.eks.cluster_security_group_id
  node_type                    = var.ai_cache_node_type
  tags                         = var.tags
}
```

Thêm `module.ai_cache.auth_secret_arn` vào danh sách `secret_arns` của module
External Secrets hiện có. Thêm variable:

```hcl
variable "ai_cache_node_type" {
  type    = string
  default = "cache.t4g.small"
}
```

Thêm output:

```hcl
output "ai_cache_primary_endpoint" {
  value = module.ai_cache.primary_endpoint
}

output "ai_cache_auth_secret_arn" {
  value = module.ai_cache.auth_secret_arn
}
```

Chạy:

```powershell
terraform -chdir=environments/production fmt -recursive
terraform -chdir=environments/production validate
terraform -chdir=environments/production plan
```

Trong plan chỉ được có resource `ai_cache` mới. Không được replace hoặc update
`module.commerce_ha.aws_elasticache_replication_group.cart`.

## 5. Secret and Chart Wiring

Thêm target mới trong `tf2-corp-chart/secrets-chart/values.yaml`:

```yaml
targets:
  aiCache: techx-corp-ai-cache

aiCache:
  enabled: false
  remoteKey: ""
```

Trong `secrets-chart/values-prod.yaml`:

```yaml
aiCache:
  enabled: true
  remoteKey: techx-prod-tf2/ai-cache
```

Thêm `ExternalSecret` vào
`secrets-chart/templates/externalsecrets.yaml` để ánh xạ:

```yaml
data:
  - secretKey: AI_CACHE_PASSWORD
    remoteRef:
      key: {{ .Values.aiCache.remoteKey }}
      property: password
  - secretKey: AI_CACHE_USER_HMAC_SECRET
    remoteRef:
      key: {{ .Values.aiCache.remoteKey }}
      property: user_hmac_secret
```

Trong `tf2-corp-chart/values.yaml`, thêm vào env của cả `product-reviews` và
`shopping-copilot`:

```yaml
- name: AI_CACHE_ENABLED
  value: "false"
- name: AI_CACHE_ADDR
  value: valkey-ai-cache:6379
- name: AI_CACHE_TLS
  value: "false"
- name: AI_CACHE_TTL_SECONDS
  value: "3600"
- name: AI_CACHE_MAX_DISTANCE
  value: "0.12"
```

Trong `values-prod.yaml`, append các entry sau vào `envOverrides` hiện có của
từng component. Không tạo block `envOverrides` thứ hai và không xóa các
override LLM đang có của `product-reviews`:

```yaml
components:
  product-reviews:
    envOverrides:
      # Keep the existing LLM_BASE_URL and LLM_MODEL entries above.
      - name: AI_CACHE_ENABLED
        value: "true"
      - name: AI_CACHE_ADDR
        value: "<ai_cache_primary_endpoint>:6379"
      - name: AI_CACHE_TLS
        value: "true"
      - name: AI_CACHE_PASSWORD
        valueFrom:
          secretKeyRef:
            name: techx-corp-ai-cache
            key: AI_CACHE_PASSWORD
      - name: AI_CACHE_USER_HMAC_SECRET
        valueFrom:
          secretKeyRef:
            name: techx-corp-ai-cache
            key: AI_CACHE_USER_HMAC_SECRET
  shopping-copilot:
    envOverrides:
      - name: AI_CACHE_ENABLED
        value: "true"
      - name: AI_CACHE_ADDR
        value: "<ai_cache_primary_endpoint>:6379"
      - name: AI_CACHE_TLS
        value: "true"
      - name: AI_CACHE_PASSWORD
        valueFrom:
          secretKeyRef:
            name: techx-corp-ai-cache
            key: AI_CACHE_PASSWORD
      - name: AI_CACHE_USER_HMAC_SECRET
        valueFrom:
          secretKeyRef:
            name: techx-corp-ai-cache
            key: AI_CACHE_USER_HMAC_SECRET
```

`<ai_cache_primary_endpoint>` lấy từ:

```powershell
terraform -chdir=environments/production output -raw ai_cache_primary_endpoint
```

Nếu chart chưa có component `shopping-copilot`, thêm component dùng image đã
có trong `docker-bake.hcl`, service port `3552`, và các env đang có trong
`docker-compose.yml`. Đây là điều kiện để Copilot thật sự chạy trên EKS và
truy cập được AI cache.

## 6. Shared Semantic Cache

Không thêm thư viện cache mới. Cả hai bot đã có `valkey==6.1.0`, và
`src/ai-common` đã có `sentence-transformers` cùng model
`all-MiniLM-L6-v2`. Dùng `execute_command` cho các lệnh `FT.*`.

### 6.1 Embedding Reuse

Trong `src/ai-common/techx_ai_common/retrieval.py`, expose một hàm dùng lại
model singleton hiện có:

```python
EMBEDDING_VERSION = "all-MiniLM-L6-v2:v1"
EMBEDDING_DIM = 384


def encode_text(text: str) -> bytes:
    vector = _get_model().encode(text, normalize_embeddings=True)
    return vector.astype("float32").tobytes()
```

Không khởi tạo thêm một `SentenceTransformer` trong cache adapter vì mỗi bot
sẽ giữ hai bản model trong memory.

### 6.2 Cache Record

Tạo `src/ai-common/techx_ai_common/semantic_cache.py`. Mỗi entry là một HASH
có TTL:

```text
kind
user_scope
product_scope
source_hash
prompt_scope
model_scope
embedding_scope
embedding
response_payload
created_at
```

Không lưu raw `user_id`, raw question hoặc raw reviews. Tạo scope như sau:

```python
def user_scope(user_id: str, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        user_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def product_scope(product_id: str) -> str:
    return hashlib.sha256(product_id.encode()).hexdigest()


def version_scope(version: str) -> str:
    return hashlib.sha256(version.encode()).hexdigest()
```

Tạo `source_hash` từ dữ liệu đã qua `sanitize_reviews`, sắp xếp theo
`source_id`, và chỉ dùng `source_id`, `text`, `score`:

```python
def review_source_hash(safe_reviews) -> str:
    rows = [
        {
            "source_id": review.source_id,
            "text": review.text,
            "score": str(review.score or ""),
        }
        for review in sorted(safe_reviews.reviews, key=lambda item: item.source_id)
    ]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

Khi description hoặc score trong database thay đổi, `source_hash` mới không
khớp entry cũ nên lookup trả miss. Entry cũ tự biến mất theo TTL; không cần
quét và xóa toàn bộ index.

### 6.3 Cache Connection

Adapter đọc kết nối từ `AI_CACHE_*`:

```python
def make_cache_client():
    if os.getenv("AI_CACHE_ENABLED", "false").lower() != "true":
        return None

    host, port = os.environ["AI_CACHE_ADDR"].rsplit(":", 1)
    use_tls = os.getenv("AI_CACHE_TLS", "false").lower() == "true"
    tls_options = (
        {"ssl": True, "ssl_cert_reqs": "required"}
        if use_tls
        else {}
    )
    return valkey.Valkey(
        host=host,
        port=int(port),
        password=os.getenv("AI_CACHE_PASSWORD"),
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=False,
        **tls_options,
    )
```

Mọi exception từ cache phải được catch và trả về cache miss. Cache hỏng không
được làm hỏng đường gọi model hiện tại.

### 6.4 Index Creation

Tạo hai index:

```text
ai_summary_cache_idx  -> ai:cache:summary:
ai_copilot_cache_idx  -> ai:cache:copilot:
```

Lệnh tạo index cho mỗi prefix:

```python
client.execute_command(
    "FT.CREATE", index_name,
    "ON", "HASH",
    "PREFIX", "1", key_prefix,
    "SCHEMA",
    "kind", "TAG",
    "user_scope", "TAG",
    "product_scope", "TAG",
    "source_hash", "TAG",
    "prompt_scope", "TAG",
    "model_scope", "TAG",
    "embedding_scope", "TAG",
    "embedding", "VECTOR", "HNSW", "6",
    "TYPE", "FLOAT32",
    "DIM", "384",
    "DISTANCE_METRIC", "COSINE",
)
```

Gọi `FT._LIST` trước khi tạo và catch lỗi `Index already exists` vì nhiều pod
có thể startup cùng lúc. Không drop/recreate index khi pod khởi động.

### 6.5 Hybrid Lookup

Lookup phải filter exact trước khi KNN:

```python
query = (
    f"@kind:{{{kind}}} "
    f"@user_scope:{{{user_scope}}} "
    f"@product_scope:{{{product_scope}}} "
    f"@source_hash:{{{source_hash}}} "
    f"@prompt_scope:{{{version_scope(prompt_version)}}} "
    f"@model_scope:{{{version_scope(model_version)}}} "
    f"@embedding_scope:{{{version_scope(EMBEDDING_VERSION)}}}"
    f"=>[KNN 1 @embedding $query_vector AS distance]"
)

result = client.execute_command(
    "FT.SEARCH", index_name,
    query,
    "PARAMS", "2", "query_vector", encode_text(question),
    "SORTBY", "distance", "ASC",
    "RETURN", "2", "response_payload", "distance",
    "DIALECT", "2",
)
```

COSINE trả distance, nên số càng thấp càng giống. Chỉ trả hit khi:

```python
distance <= float(os.getenv("AI_CACHE_MAX_DISTANCE", "0.12"))
```

Ví dụ “Tóm tắt review của A123” và “Cho tôi bản tóm tắt đánh giá A124” có thể
có vector gần nhau, nhưng `product_scope` khác nhau nên không thể hit chéo.

### 6.6 Cache Store

Chỉ store response sau grounding và output guardrail:

```python
client.hset(
    key,
    mapping={
        "kind": kind,
        "user_scope": user_scope,
        "product_scope": product_scope,
        "source_hash": source_hash,
        "prompt_scope": version_scope(prompt_version),
        "model_scope": version_scope(model_version),
        "embedding_scope": version_scope(EMBEDDING_VERSION),
        "embedding": encode_text(question),
        "response_payload": response_payload,
        "created_at": str(int(time.time())),
    },
)
client.expire(key, ttl_seconds)
```

Key dùng prefix theo bot và SHA-256 của các scope cùng normalized question:

```text
ai:cache:summary:<sha256>
ai:cache:copilot:<sha256>
```

Không store các status `BLOCKED`, `FALLBACK`, `RATE_LIMITED`, response chưa
grounded hoặc response có pending action token.

## 7. Product Reviews Integration

Điểm tích hợp là
`ProductReviewService.AskProductAIAssistant()` trong
`src/product-reviews/product_reviews_server.py`.

Thứ tự xử lý:

1. Lấy `user_id` từ gRPC metadata `x-session-id`.
2. Chạy request guardrail hiện có.
3. Fetch reviews theo `request.product_id`.
4. Chạy `sanitize_reviews`.
5. Tính `source_hash`.
6. Lookup `ai_summary_cache_idx`.
7. Nếu hit, dựng `AskProductAIAssistantResponse` từ payload và không gọi LLM.
8. Nếu miss, chạy model rate limiter hiện có rồi chạy pipeline hiện tại.
9. Chỉ store khi response cuối có status `GROUNDED`.

Di chuyển `check_rate_limit()` xuống sau cache miss. Nếu giữ cooldown trước
lookup như code hiện tại, request lặp ngay lập tức sẽ trả `RATE_LIMITED` thay
vì cache hit. Rate limit ở vị trí mới bảo vệ phần gọi model tốn chi phí; rate
limit tổng request tiếp tục đặt ở gateway/ingress.

Để tránh fetch reviews hai lần, refactor
`get_ai_assistant_response()` nhận optional `safe_reviews`. Các nhánh Bedrock
và OpenAI dùng lại giá trị này thay vì gọi database lần nữa.

Các tham số của Summary cache:

```python
kind = "answer"
product_id = request.product_id
prompt_version = "product-review-system-prompt:v1"
model_version = os.environ["LLM_MODEL"]
```

Response cache hit vẫn phải đi qua bước deserialize/schema validation. Nếu
payload hỏng hoặc thiếu field, coi là miss và gọi model.

## 8. Shopping Copilot Integration

Copilot có hai model call riêng: intent parsing và review-grounded generation.
Cache đúng tại từng model boundary thay vì cache toàn bộ
`CopilotSearchResponse`.

### 8.1 Exact Intent Cache

Trong `intent_parser.py`, cache exact `ShoppingIntent` đã validate bằng
Pydantic. Intent không dùng semantic lookup vì một câu thêm cụm “add to cart”
có thể rất gần một câu read-only nhưng mang hành động khác.

```python
kind = "intent"
prompt_version = "shopping-intent-system-prompt:v1"
model_version = os.environ["LLM_MODEL"]
```

Key exact gồm:

```text
user_scope + normalized_message + prompt_scope + model_scope
```

Đọc/ghi bằng `GET` và `SETEX`. Chỉ store intent khi
`is_shopping_related=true`, `wants_add_to_cart=false` và kết quả đã validate
thành `ShoppingIntent`.

Khi hit, parse `response_payload` lại bằng
`ShoppingIntent.model_validate_json()`. Không dùng payload chưa validate.
Request lặp chính xác sẽ không gọi intent model; semantic cache vẫn được dùng
cho Summary và Copilot review answer.

### 8.2 Review Answer Cache

Trong `review_tool.answer_with_reviews()` đã có đúng cache boundary:

1. `product_id` đã được resolve từ catalog result.
2. Product ID đã được kiểm tra trong `allowed_product_ids`.
3. Reviews đã được fetch và sanitize.
4. Chưa gọi `generate_grounded_summary`.

Tại đây:

```python
kind = "review-answer"
product_id = resolved_product_id
source_hash = review_source_hash(safe_reviews)
prompt_version = "copilot-review-grounding-prompt:v1"
model_version = os.environ["LLM_MODEL"]
```

Lookup trước `generate_bedrock_grounded_summary()` hoặc
`generate_grounded_summary()`. Store `GroundedResponse.model_dump_json()` sau
`validate_grounded_summary()`.

Nếu review-answer miss, gọi `check_rate_limit()` trước model generation. Bỏ
rate limiter khỏi đầu `input_guardrail_node`; nếu không, request có exact
intent hit và semantic review hit vẫn bị cooldown chặn trước khi tới cache.

Không cache toàn bộ Copilot response vì response đó có thể chứa catalog data
mới hoặc `pending_action_token`. Catalog vẫn được đọc ở request hiện tại;
phần tốn model token được lấy từ semantic cache.

### 8.3 Request Cache Status

Thêm các field vào `CopilotState`:

```python
cache_status: str
cache_match: str
cache_distance: Optional[float]
```

Quy tắc tổng hợp:

- `hit`: mọi model boundary được dùng trong request đều hit.
- `miss`: có ít nhất một model boundary phải gọi model.
- Request không cacheable, bị block hoặc có cart mutation trả `miss` với
  `cache_match=none`.
- `cache_match=semantic` nếu request có semantic hit; nếu chỉ có exact intent
  hit thì trả `cache_match=exact`.

`copilot_server.py` chỉ chuyển ba field này sang protobuf response.

## 9. Response Contract

Thêm message vào `pb/demo.proto`:

```protobuf
message CacheMetadata {
  // hit | miss
  string status = 1;
  // exact | semantic | none
  string match = 2;
  float distance = 3;
}
```

Thêm field mới, không đổi số field cũ:

```protobuf
message AskProductAIAssistantResponse {
  string response = 1;
  string status = 2;
  string reason = 3;
  repeated GroundedClaim claims = 4;
  CacheMetadata cache = 5;
}

message CopilotSearchResponse {
  // Existing fields 1..7 remain unchanged.
  CacheMetadata cache = 8;
}
```

Regenerate protobuf:

```powershell
make docker-generate-protobuf
```

Frontend API trả metadata ở cùng cấp với payload:

```json
{
  "cache": "hit",
  "cache_match": "semantic",
  "cache_distance": 0.03
}
```

Không đưa `user_scope`, cache key, raw question hoặc source content vào
response.

## 10. Replay Endpoint

Tạo `src/frontend/pages/api/ai/replay.ts` và nhận:

```json
{
  "surface": "summary",
  "request": {
    "product_id": "OLJCESPC7Z",
    "question": "Summarize the reviews"
  },
  "user_id": "mentor-user-a",
  "session_id": "mentor-session-1"
}
```

Dispatch:

- `surface=summary` gọi `ProductReviewService.askProductAIAssistant`.
- `surface=copilot` gọi `ShoppingCopilotService.search`.

Response tối thiểu:

```json
{
  "surface": "summary",
  "cache": "hit",
  "cache_match": "semantic",
  "cache_distance": 0.01,
  "latency_ms": 24,
  "response": {}
}
```

`user_id` phải được truyền vào gRPC metadata để tạo `user_scope`. Không đưa
`session_id` vào semantic cache key; cùng user được phép dùng cache qua phiên.
Cửa replay phải được bảo vệ bằng authentication hiện có hoặc chỉ bật trong
môi trường verification.

## 11. Metrics

Tạo metric trong shared adapter:

```text
ai_cache_requests_total{surface,outcome,match}
ai_cache_lookup_duration_ms{surface,outcome}
ai_cache_embedding_duration_ms{surface}
ai_cache_model_calls_total{surface}
ai_cache_tokens_saved_total{surface}
```

Label chỉ dùng các giá trị hữu hạn:

```text
surface = summary | copilot
outcome = hit | miss | bypass | error
match = exact | semantic | none
```

Không dùng `user_id`, `product_id`, question hoặc cache key làm metric label.

Mỗi request ghi một structured log:

```json
{
  "event": "ai_cache_lookup",
  "surface": "summary",
  "outcome": "hit",
  "match": "semantic",
  "distance": 0.03,
  "lookup_ms": 8
}
```

## 12. Automated Tests

### 12.1 Shared Adapter Tests

Tạo `src/ai-common/tests/test_semantic_cache.py`:

- Cùng user, product, source và câu hỏi gần nhau trả hit.
- Khác `user_id` trả miss.
- Khác `product_id` trả miss.
- Khác `source_hash` trả miss.
- Distance lớn hơn threshold trả miss.
- Entry hết TTL trả miss.
- Valkey timeout/error trả miss, không raise ra bot.
- Payload sai schema trả miss.

### 12.2 Product Reviews Tests

Thêm test vào `src/product-reviews/tests`:

1. Request đầu gọi model và trả `cache=miss`.
2. Request giống hệt lần hai không gọi model và trả `cache=hit`.
3. Request paraphrase cùng product trả semantic hit.
4. Request cùng câu nhưng product khác trả miss.
5. Request cùng câu nhưng user khác trả miss.
6. Thay description/score của review làm `source_hash` đổi và trả miss.
7. Response `BLOCKED` hoặc `FALLBACK` không được store.

### 12.3 Shopping Copilot Tests

Thêm test vào `src/shopping-copilot/tests`:

1. Intent read-only lặp chính xác được lấy từ exact cache.
2. Intent có `wants_add_to_cart=true` luôn bypass.
3. Review answer cùng user/product/source trả hit.
4. Review answer khác product hoặc user trả miss.
5. Thay review source làm review-answer miss.
6. Cache hit không bao giờ tái sử dụng `pending_action_token`.

### 12.4 Integration Tests

Chạy test integration với `valkey-ai-cache` thật:

```powershell
docker compose up -d valkey-ai-cache
docker exec valkey-ai-cache valkey-cli FT._LIST
python -m pytest src/ai-common/tests/test_semantic_cache.py -v
python -m pytest src/product-reviews/tests -v
python -m pytest src/shopping-copilot/tests -v
```

Không mock `FT.SEARCH` trong bài integration. Hit phải đến từ entry được tạo
bởi request đầu.

## 13. Manual Verification

Dùng record kiểm thử có thể sửa:

```text
product_id = OLJCESPC7Z
username   = stargazer_mike
```

Chạy lần lượt:

1. Gửi một request Summary: phải `miss`.
2. Gửi lại đúng request: phải `hit`.
3. Gửi câu paraphrase cùng product: phải `hit` nếu distance đạt threshold.
4. Gửi cùng câu với user khác: phải `miss`.
5. Gửi câu tương tự cho product khác: phải `miss`.
6. Sửa description hoặc score của record trên.
7. Gửi lại request cũ: phải `miss` và response phản ánh source mới.
8. Gửi lại một lần nữa: phải `hit`.

Lặp lại cho Copilot review Q&A. Lưu response JSON, latency và model-call
counter của từng lần.

Tính số tổng:

```text
hit_rate = hit / (hit + miss)
latency_saved_ms = model_path_latency_ms - cache_hit_latency_ms
model_calls_saved = cache_hits_that_bypassed_model
estimated_cost_saved = saved_input_tokens * input_price
                       + saved_output_tokens * output_price
```

## 14. Rollout

Rollout bằng `AI_CACHE_ENABLED`:

1. Deploy Valkey 9.0 và xác nhận `FT.CREATE`/`FT.SEARCH`.
2. Deploy hai bot với `AI_CACHE_ENABLED=false`.
3. Bật cho `product-reviews`, chạy toàn bộ replay cases.
4. Bật cho `shopping-copilot`, chạy lại cases read-only và cart bypass.
5. Theo dõi hit-rate, cache error, eviction và model-call counter.

Nếu cache gây lỗi, đặt `AI_CACHE_ENABLED=false`. Hai bot phải quay về đường
gọi model hiện tại mà không cần rollback Valkey hoặc thay đổi `valkey-cart`.

## 15. Implementation Checklist

- [ ] Local dùng `valkey-bundle` và `FT._LIST` hoạt động.
- [ ] ElastiCache Valkey 9.0 riêng đã được tạo.
- [ ] Terraform không thay đổi `valkey-cart`.
- [ ] Hai bot nhận `AI_CACHE_*`; `VALKEY_ADDR` cũ giữ nguyên.
- [ ] Hai index và hai prefix được tạo idempotent.
- [ ] Lookup luôn filter user, product, source và version trước KNN.
- [ ] Summary bot bỏ qua model khi semantic cache hit.
- [ ] Copilot chỉ cache model output read-only.
- [ ] Không cache blocked, fallback hoặc pending action token.
- [ ] TTL và source-hash invalidation hoạt động.
- [ ] Replay response luôn có `cache=hit|miss`.
- [ ] Cross-user và cross-product tests pass.
- [ ] Metrics không chứa raw PII hoặc high-cardinality identifiers.
