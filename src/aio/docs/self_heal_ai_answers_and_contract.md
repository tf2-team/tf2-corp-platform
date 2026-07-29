# Self-heal: câu trả lời AI và contract CDO

Tài liệu này chốt câu trả lời cho CDO dựa trên runtime hiện tại trong `aio/` và gom contract thành JSON Schema có ví dụ ngay bên dưới từng schema.

Kết luận P0: runtime hiện tại vẫn là `dry-run`/`page_oncall`. Seed/history chỉ hỗ trợ decision engine; không thay thế executor, post-action verification, rollback verification, idempotency/cooldown persistent và audit append-only.

## 1. Câu trả lời cần chốt

| # | Câu hỏi | Trả lời |
| --- | --- | --- |
| 1 | Runtime path/source of truth | Repo/path đúng là `tf2-corp-platform/src/aio`. Trong workspace hiện tại, path tương đối là `aio/...`. |
| 2 | `actions.json` ở đâu? | Đã có tại `aio/config/actions.json`, runtime load qua `AIOPS_ACTIONS_CATALOG_PATH=config/actions.json`. |
| 3 | Schema `IncidentHistoryRecord` | `aio/aiops/schemas/domain.py`, import bằng `from aiops.schemas import IncidentHistoryRecord`. |
| 4 | Golden action target | Chọn `product-catalog` cho P0 nếu platform owner xác nhận cluster/namespace được phép mutate. |
| 5 | Namespace | Runtime topology hiện khai báo `techx-corp-prod`; chỉ dùng live nếu đây là dev/demo đã approve. Nếu có namespace demo riêng thì dùng namespace đó. |
| 6 | Min/max replica | P0: `min_replicas=2`, `max_replicas=3`, mỗi execution chỉ tăng `+1`, rollback restore replica count trước action. |
| 7 | Allowlist | P0 chỉ allowlist `["product-catalog"]`. |
| 8 | Protected list | Block DB/Kafka/cache/flagd/AIO/observability/system namespace/payment/stateful/high-risk target. |
| 9 | Policy | `phase3-scale-policy-v1`, pre-approved versioned policy, scope chỉ cho golden action/target, expiry đề xuất `2026-08-31T23:59:59Z`. Owner cuối cùng cần platform owner ký. |
| 10 | Executor auth | P0 dùng bearer token nội bộ từ Kubernetes Secret + NetworkPolicy. Nếu có mesh thì thêm mTLS/mesh policy. |
| 11 | Persistent store | SQLite WAL trên PVC riêng của executor. |
| 12 | Audit log | Append-only trong SQLite/PVC executor, retention P0: 30 ngày. |
| 13 | `LiveExecutorClient` API | Runtime hiện chỉ có `POST /actions`. Executor nên hỗ trợ endpoint này và thêm `/v1/actions/plan`, `/execute`, `/status`, `/rollback`. |
| 14 | Post-action verification | AIO runtime sở hữu verification bằng telemetry mới hơn `executed_at`; executor chỉ trả metadata/snapshot. |
| 15 | Page/escalate | Nếu chưa có kênh thật, `page_oncall.py` là no-op/page-only có audit rõ, không giả lập đã page thật. |
| 16 | Smoke tests | Golden scale success, protected target fallback, stale telemetry/resourceVersion reject/rollback/escalate. |
| 17 | `restart_*` semantics | P0 giữ `restart_*` ở dry-run/page. Live action đầu tiên là `scale_deployment`. |
| 18 | Chart executor | Nằm trong repo chart ngang hàng `tf2-corp-chart/`, đề xuất `charts/aiops-live-executor/` hoặc template trong umbrella chart hiện có. |
| 19 | Môi trường test mutate | Chỉ cluster/context dev/demo đã approve, đúng namespace và đúng `Deployment/product-catalog`. Không production/shared critical namespace. |

## 2. Incident history seed schema

Schema này dành cho file CDO quản lý:

```text
aio/config/incidents_history.seed.json
```

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/incident-history-seed.schema.json",
  "title": "IncidentHistorySeedFile",
  "type": "array",
  "items": { "$ref": "#/$defs/IncidentHistorySeedRecord" },
  "$defs": {
    "IncidentHistorySeedRecord": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "incident_id",
        "affected_services",
        "log_signatures",
        "trace_signatures",
        "metric_ratios",
        "actions_taken"
      ],
      "properties": {
        "case": { "type": "string", "minLength": 1 },
        "description": { "type": "string" },
        "owner": { "type": "string" },
        "source": { "type": "string" },
        "notes": { "type": "string" },
        "incident_id": {
          "type": "string",
          "pattern": "^(seed|hist)-[a-z0-9][a-z0-9_.:-]*$"
        },
        "affected_services": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1 }
        },
        "log_signatures": {
          "type": "array",
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1, "maxLength": 128 }
        },
        "trace_signatures": {
          "type": "array",
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1, "maxLength": 128 }
        },
        "metric_ratios": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": {
            "type": "number",
            "exclusiveMinimum": 0
          }
        },
        "actions_taken": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/HistoryAction" }
        }
      }
    },
    "HistoryAction": {
      "type": "object",
      "additionalProperties": false,
      "required": ["action_id", "target", "outcome"],
      "properties": {
        "action_id": { "type": "string", "minLength": 1 },
        "target": { "type": "string", "minLength": 1 },
        "outcome": { "type": "string", "enum": ["success", "partial", "failed"] }
      }
    }
  }
}
```

Ví dụ:

```json
[
  {
    "case": "fault_cpu_saturation",
    "description": "product-catalog CPU tăng bất thường trong khi request rate bình thường",
    "owner": "catalog-oncall",
    "source": "reviewed-replay",
    "incident_id": "seed-product-catalog-cpu-001",
    "affected_services": ["product-catalog"],
    "log_signatures": ["cpu_saturation"],
    "trace_signatures": [],
    "metric_ratios": {
      "product_catalog_cpu_millicores": 2.0,
      "product_catalog_request_rate_5m": 1.0
    },
    "actions_taken": [
      {
        "action_id": "restart_product_catalog",
        "target": "product-catalog",
        "outcome": "success"
      }
    ]
  }
]
```

## 3. Runtime incident history schema

Schema này là output runtime:

```text
aio/config/incidents_history.json
```

Runtime đang load bằng `IncidentHistoryStore.load()` và schema Pydantic `IncidentHistoryRecord`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/incident-history-runtime.schema.json",
  "title": "IncidentHistoryRuntimeFile",
  "type": "array",
  "items": { "$ref": "#/$defs/IncidentHistoryRecord" },
  "$defs": {
    "IncidentHistoryRecord": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "incident_id",
        "affected_services",
        "log_signatures",
        "trace_signatures",
        "metric_ratios",
        "actions_taken"
      ],
      "properties": {
        "incident_id": { "type": "string", "minLength": 1 },
        "affected_services": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1 }
        },
        "log_signatures": {
          "type": "array",
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1, "maxLength": 128 }
        },
        "trace_signatures": {
          "type": "array",
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1, "maxLength": 128 }
        },
        "metric_ratios": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": {
            "type": "number",
            "exclusiveMinimum": 0
          }
        },
        "actions_taken": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/HistoryAction" }
        }
      }
    },
    "HistoryAction": {
      "type": "object",
      "additionalProperties": false,
      "required": ["action_id", "target", "outcome"],
      "properties": {
        "action_id": { "type": "string", "minLength": 1 },
        "target": { "type": "string", "minLength": 1 },
        "outcome": { "type": "string", "enum": ["success", "partial", "failed"] }
      }
    }
  }
}
```

Ví dụ:

```json
[
  {
    "incident_id": "seed-product-catalog-cpu-001",
    "affected_services": ["product-catalog"],
    "log_signatures": ["cpu_saturation"],
    "trace_signatures": [],
    "metric_ratios": {
      "product_catalog_cpu_millicores": 2.0,
      "product_catalog_request_rate_5m": 1.0
    },
    "actions_taken": [
      {
        "action_id": "restart_product_catalog",
        "target": "product-catalog",
        "outcome": "success"
      }
    ]
  }
]
```

Validation thêm ngoài JSON Schema:

- `action_id` phải tồn tại trong `aio/config/actions.json`.
- `target` trong history phải khớp target của action catalog.
- `metric_ratios` là ratio so với baseline/threshold, không phải raw value.
- Không chứa secret, token, email cá nhân, customer id, raw log dài hoặc stacktrace dài.
- Output deterministic: sort theo `incident_id`, JSON indent 2, UTF-8.

## 4. Action catalog schema

File hiện có:

```text
aio/config/actions.json
```

Runtime schema tương ứng `ActionCatalogItem` trong `aio/aiops/schemas/domain.py`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/action-catalog.schema.json",
  "title": "ActionCatalogFile",
  "type": "array",
  "items": { "$ref": "#/$defs/ActionCatalogItem" },
  "$defs": {
    "ActionCatalogItem": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "action_id",
        "action_type",
        "target",
        "target_kind",
        "cost_min",
        "downtime_min",
        "blast_radius_services"
      ],
      "properties": {
        "action_id": { "type": "string", "minLength": 1 },
        "action_type": {
          "type": "string",
          "enum": ["restart", "scale_deployment", "restore_deployment_replicas", "page"]
        },
        "target": { "type": "string", "minLength": 1 },
        "target_kind": {
          "type": "string",
          "enum": ["Deployment", "OnCall"]
        },
        "cost_min": { "type": "number", "minimum": 0 },
        "downtime_min": { "type": "number", "minimum": 0 },
        "blast_radius_services": {
          "type": "array",
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1 }
        },
        "replicas": { "type": "integer", "minimum": 0 },
        "verification_defined": { "type": "boolean", "default": true },
        "rollback_defined": { "type": "boolean", "default": true },
        "approved": { "type": "boolean", "default": false }
      }
    }
  }
}
```

Ví dụ golden action cần bổ sung cho P0 live:

```json
{
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "cost_min": 2.0,
  "downtime_min": 0.0,
  "blast_radius_services": ["frontend", "recommendation", "product-reviews", "checkout"],
  "replicas": 3,
  "verification_defined": true,
  "rollback_defined": true,
  "approved": true
}
```

Ghi chú: `approved=true` trong catalog chưa đủ để execute. Executor vẫn phải kiểm tra policy id, expiry, allowlist, cooldown, idempotency, plan hash và Kubernetes `resourceVersion`.

## 5. Action script context schema

Các script Python bắt buộc:

```text
aio/runbooks/actions/plan_scale_deployment.py
aio/runbooks/actions/scale_deployment.py
aio/runbooks/actions/restore_deployment_replicas.py
aio/runbooks/actions/page_oncall.py
```

Mỗi script expose:

```python
def run(context: dict) -> dict:
    ...
```

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/action-script-context.schema.json",
  "title": "ActionScriptContext",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "incident_id",
    "action_id",
    "action_type",
    "target",
    "target_kind",
    "namespace",
    "dry_run",
    "policy_id",
    "policy_approved",
    "idempotency_key",
    "reason",
    "root_cause_metrics"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "incident_id": { "type": "string", "pattern": "^inc-[a-zA-Z0-9_.:-]+$" },
    "action_id": { "type": "string", "minLength": 1 },
    "action_type": {
      "type": "string",
      "enum": ["scale_deployment", "restore_deployment_replicas", "page"]
    },
    "target": { "type": "string", "minLength": 1 },
    "target_kind": { "type": "string", "enum": ["Deployment", "OnCall"] },
    "namespace": { "type": "string", "minLength": 1 },
    "dry_run": { "type": "boolean" },
    "policy_id": { "type": "string", "minLength": 1 },
    "policy_approved": { "type": "boolean" },
    "policy_expires_at": { "type": "string", "format": "date-time" },
    "idempotency_key": { "type": "string", "pattern": "^sha256:[a-fA-F0-9]{64}$" },
    "reason": { "type": "string", "minLength": 1 },
    "root_cause_metrics": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "requested_at": { "type": "string", "format": "date-time" },
    "plan_id": { "type": "string" },
    "plan_hash": { "type": "string", "pattern": "^sha256:[a-fA-F0-9]{64}$" },
    "rollback_token": { "type": "string" }
  }
}
```

Ví dụ:

```json
{
  "schema_version": "1.0",
  "incident_id": "inc-123",
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "dry_run": true,
  "policy_id": "phase3-scale-policy-v1",
  "policy_approved": true,
  "policy_expires_at": "2026-08-31T23:59:59Z",
  "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "reason": "cpu_saturation",
  "root_cause_metrics": ["product_catalog_cpu_millicores"],
  "requested_at": "2026-07-27T00:00:00Z"
}
```

Executor phải resolve namespace/target/min/max replica từ allowlist theo `action_id`; không tin target tùy ý do caller truyền vào.

## 6. Action script response schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/action-script-response.schema.json",
  "title": "ActionScriptResponse",
  "type": "object",
  "additionalProperties": false,
  "required": ["ok", "executed", "action_id", "target", "message", "verification", "rollback"],
  "properties": {
    "ok": { "type": "boolean" },
    "executed": { "type": "boolean" },
    "action_id": { "type": "string" },
    "action_type": { "type": "string" },
    "target": { "type": "string" },
    "target_kind": { "type": "string" },
    "namespace": { "type": "string" },
    "message": { "type": "string" },
    "plan": { "type": "object" },
    "execution_id": { "type": "string" },
    "rollback_id": { "type": "string" },
    "executed_at": { "type": "string", "format": "date-time" },
    "before": { "type": "object" },
    "after": { "type": "object" },
    "rollback_token": { "type": "string" },
    "verification": {
      "type": "object",
      "additionalProperties": true,
      "required": ["defined"],
      "properties": {
        "defined": { "type": "boolean" },
        "passed": { "type": ["boolean", "null"] },
        "owner": { "type": "string" },
        "fresh_after": { "type": "string", "format": "date-time" }
      }
    },
    "rollback": {
      "type": "object",
      "additionalProperties": true,
      "required": ["defined"],
      "properties": {
        "defined": { "type": "boolean" },
        "action_type": { "type": "string" },
        "target_replicas": { "type": "integer" }
      }
    }
  }
}
```

Ví dụ dry-run/plan:

```json
{
  "ok": true,
  "executed": false,
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "dry-run scale deployment/product-catalog from 2 to 3 replicas",
  "plan": {
    "plan_id": "plan-123",
    "plan_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "expires_at": "2026-07-27T00:10:00Z",
    "before": {
      "replicas": 2,
      "ready_replicas": 2,
      "resource_version": "12345"
    },
    "after": {
      "replicas": 3
    },
    "blast_radius_services": ["frontend", "recommendation", "product-reviews", "checkout"]
  },
  "verification": {
    "defined": true,
    "passed": null,
    "owner": "aiops-runtime"
  },
  "rollback": {
    "defined": true,
    "action_type": "restore_deployment_replicas",
    "target_replicas": 2
  }
}
```

Ví dụ execute:

```json
{
  "ok": true,
  "executed": true,
  "execution_id": "exec-123",
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "scaled deployment/product-catalog from 2 to 3 replicas",
  "executed_at": "2026-07-27T00:01:00Z",
  "before": {
    "replicas": 2,
    "resource_version": "12345"
  },
  "after": {
    "replicas": 3,
    "resource_version": "12346"
  },
  "rollback_token": "rbt-123",
  "verification": {
    "defined": true,
    "fresh_after": "2026-07-27T00:01:00Z"
  },
  "rollback": {
    "defined": true,
    "action_type": "restore_deployment_replicas",
    "target_replicas": 2
  }
}
```

Ví dụ rollback:

```json
{
  "ok": true,
  "executed": true,
  "rollback_id": "rb-123",
  "execution_id": "exec-123",
  "action_id": "restore_deployment_replicas",
  "action_type": "restore_deployment_replicas",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "restored deployment/product-catalog replicas from 3 to 2",
  "executed_at": "2026-07-27T00:08:00Z",
  "before": {
    "replicas": 3,
    "resource_version": "12346"
  },
  "after": {
    "replicas": 2,
    "resource_version": "12347"
  },
  "verification": {
    "defined": true,
    "passed": null,
    "owner": "aiops-runtime"
  },
  "rollback": {
    "defined": true,
    "target_replicas": 2
  }
}
```

## 7. Executor API schema

Runtime hiện tại mới có `LiveExecutorClient.submit_action()` gọi `POST /actions`. Executor nên hỗ trợ endpoint cũ này và API versioned bên dưới.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/executor-request.schema.json",
  "title": "ExecutorActionRequest",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "incident_id",
    "action_id",
    "policy_id",
    "idempotency_key",
    "requested_at"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "incident_id": { "type": "string", "pattern": "^inc-[a-zA-Z0-9_.:-]+$" },
    "action_id": { "type": "string", "enum": ["scale_product_catalog"] },
    "policy_id": { "type": "string", "const": "phase3-scale-policy-v1" },
    "idempotency_key": { "type": "string", "pattern": "^sha256:[a-fA-F0-9]{64}$" },
    "reason": { "type": "string" },
    "root_cause_metrics": {
      "type": "array",
      "items": { "type": "string" }
    },
    "requested_at": { "type": "string", "format": "date-time" },
    "plan_id": { "type": "string" },
    "plan_hash": { "type": "string", "pattern": "^sha256:[a-fA-F0-9]{64}$" },
    "rollback_token": { "type": "string" }
  }
}
```

Endpoint:

```text
POST /actions
POST /v1/actions/plan
POST /v1/actions/execute
GET  /v1/actions/{execution_id}
POST /v1/actions/{execution_id}/rollback
```

Ví dụ plan request:

```json
{
  "schema_version": "1.0",
  "incident_id": "inc-123",
  "action_id": "scale_product_catalog",
  "policy_id": "phase3-scale-policy-v1",
  "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "reason": "cpu_saturation",
  "root_cause_metrics": ["product_catalog_cpu_millicores"],
  "requested_at": "2026-07-27T00:00:00Z"
}
```

Ví dụ execute request:

```json
{
  "schema_version": "1.0",
  "incident_id": "inc-123",
  "action_id": "scale_product_catalog",
  "policy_id": "phase3-scale-policy-v1",
  "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "plan_id": "plan-123",
  "plan_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "requested_at": "2026-07-27T00:01:00Z"
}
```

Ví dụ rollback request:

```json
{
  "schema_version": "1.0",
  "incident_id": "inc-123",
  "action_id": "scale_product_catalog",
  "policy_id": "phase3-scale-policy-v1",
  "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "rollback_token": "rbt-123",
  "requested_at": "2026-07-27T00:08:00Z"
}
```

## 8. Verification result schema

AIO runtime sở hữu verification. Verification chỉ bắt đầu sau khi executor trả `executed=true`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/post-action-verification.schema.json",
  "title": "PostActionVerificationResult",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "incident_id",
    "execution_id",
    "status",
    "fresh_after",
    "checked_at",
    "reason"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "incident_id": { "type": "string" },
    "execution_id": { "type": "string" },
    "status": { "type": "string", "enum": ["pass", "fail", "inconclusive"] },
    "fresh_after": { "type": "string", "format": "date-time" },
    "checked_at": { "type": "string", "format": "date-time" },
    "deadline_seconds": { "type": "integer", "minimum": 30, "maximum": 1800 },
    "poll_interval_seconds": { "type": "integer", "minimum": 5, "maximum": 300 },
    "min_fresh_samples": { "type": "integer", "minimum": 1 },
    "consecutive_passes": { "type": "integer", "minimum": 1 },
    "reason": { "type": "string" },
    "signals": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["signal_id", "status"],
        "properties": {
          "signal_id": { "type": "string" },
          "status": { "type": "string", "enum": ["pass", "fail", "missing", "stale"] },
          "fresh_samples": { "type": "integer", "minimum": 0 }
        }
      }
    }
  }
}
```

Ví dụ:

```json
{
  "schema_version": "1.0",
  "incident_id": "inc-123",
  "execution_id": "exec-123",
  "status": "pass",
  "fresh_after": "2026-07-27T00:01:00Z",
  "checked_at": "2026-07-27T00:07:00Z",
  "deadline_seconds": 600,
  "poll_interval_seconds": 30,
  "min_fresh_samples": 3,
  "consecutive_passes": 2,
  "reason": "fresh telemetry passed consecutive rule",
  "signals": [
    {
      "signal_id": "product_catalog_cpu_millicores",
      "status": "pass",
      "fresh_samples": 4
    }
  ]
}
```

Rule bắt buộc:

- Missing telemetry là `inconclusive`.
- Stale telemetry là `inconclusive`.
- Feature snapshot cùng cycle với detection không được tính là verification.
- `fail`, timeout hoặc `inconclusive` sau live mutation phải rollback.

## 9. Audit event schema

Audit là append-only JSON event, lưu trong SQLite WAL/PVC của executor và có thể export.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/aiops/self-heal/audit-event.schema.json",
  "title": "SelfHealAuditEvent",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "event_id",
    "event_type",
    "incident_id",
    "action_id",
    "target",
    "actor",
    "created_at"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "event_id": { "type": "string", "minLength": 1 },
    "event_type": {
      "type": "string",
      "enum": [
        "plan_requested",
        "plan_succeeded",
        "plan_rejected",
        "execute_requested",
        "execute_succeeded",
        "execute_rejected",
        "execute_failed",
        "verification_started",
        "verification_passed",
        "verification_failed",
        "verification_inconclusive",
        "rollback_requested",
        "rollback_succeeded",
        "rollback_failed",
        "escalation_requested",
        "escalation_succeeded"
      ]
    },
    "incident_id": { "type": "string" },
    "execution_id": { "type": "string" },
    "action_id": { "type": "string" },
    "target": { "type": "string" },
    "namespace": { "type": "string" },
    "actor": { "type": "string", "enum": ["aiops-runtime", "aiops-live-executor"] },
    "policy_id": { "type": "string" },
    "idempotency_key": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "details": { "type": "object" }
  }
}
```

Ví dụ:

```json
{
  "schema_version": "1.0",
  "event_id": "audit-123",
  "event_type": "execute_succeeded",
  "incident_id": "inc-123",
  "execution_id": "exec-123",
  "action_id": "scale_product_catalog",
  "target": "product-catalog",
  "namespace": "techx-corp-prod",
  "actor": "aiops-live-executor",
  "policy_id": "phase3-scale-policy-v1",
  "idempotency_key": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "created_at": "2026-07-27T00:01:00Z",
  "details": {
    "from_replicas": 2,
    "to_replicas": 3,
    "resource_version_before": "12345",
    "resource_version_after": "12346"
  }
}
```

## 10. Guardrail bắt buộc

Executor phải block mutation nếu:

- `action_id` không nằm trong allowlist.
- Target là protected/stateful/system namespace hoặc không phải `Deployment`.
- `dry_run=true`.
- Policy thiếu, hết hạn, sai scope hoặc chưa pre-approve.
- Plan thiếu, hết hạn hoặc `plan_hash` không khớp.
- Kubernetes `resourceVersion` đã đổi sau dry-run.
- Thiếu verification hoặc rollback.
- Replica hiện tại ngoài `[2, 3]`.
- Desired replica vượt `3` hoặc tăng hơn `+1`.
- Cùng idempotency key đã execute.
- Target đang cooldown hoặc có execution active.
- Vượt max attempt/action budget.
- Kubernetes API timeout/lỗi không xác định.

Log không được chứa secret, token, kubeconfig, bearer token, raw customer data, email, raw log dài hoặc stacktrace dài.

## 11. Acceptance criteria

Data handoff đạt khi:

- `aio/config/incidents_history.json` load được bằng `IncidentHistoryStore.load()`.
- Mọi `action_id` trong history tồn tại trong `aio/config/actions.json`.
- Generator `--check` pass và in summary: số record, action hợp lệ, case count, lỗi.
- Seed không có PII/secret/raw log.
- 3 smoke incident trả đúng nhóm action/fallback.

Functional Phase 3 đạt khi:

- AIO runtime vẫn Kubernetes read-only.
- Executor riêng có RBAC write tối thiểu cho đúng golden Deployment.
- Golden action đi qua dry-run, policy, plan hash, idempotency, cooldown và budget.
- Execute chỉ đổi `/spec/replicas` tối đa `+1`.
- Verification dùng fresh telemetry sau `executed_at`.
- Fail/timeout/inconclusive tự rollback.
- Rollback restore replica count trước action và được verify.
- Retry/restart không tạo duplicate action.
- Protected target bị block và escalate.
- Full lifecycle có append-only audit.

## 12. Không làm trong P0

- Không live execute `restart_*`.
- Không auto-heal DB/Kafka/cache/disk/flagd/AIO/observability.
- Không generate hàng nghìn incident synthetic.
- Không cấp Kubernetes write RBAC cho AIO runtime.
- Không coi seed/history là hoàn thành Phase 3.
