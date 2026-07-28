# Self-heal Executor API Contract

Contract này dành cho CDO implement một executor service để AI runtime gọi khi có quyết định remediation.
AI runtime không nhận Kubernetes write permission và không tự self-heal trực tiếp.
Quyền mutate hệ thống nằm trong executor do CDO vận hành, có allowlist, policy, audit, idempotency và rollback.

## Nguyên tắc bắt buộc

- AI chỉ gọi HTTP API bằng JSON, không gọi `kubectl`, không mount kubeconfig write.
- Executor phải tự kiểm tra lại policy, allowlist, protected target, dry-run, idempotency và cooldown.
- `POST /v1/actions/plan` không được mutate.
- `POST /v1/actions/execute` chỉ mutate khi action đã được CDO/policy cho phép.
- Mọi action mutating phải có verification và rollback token.
- Nếu thiếu dữ liệu an toàn, executor trả `allowed=false`, không throw lỗi 500 cho lỗi nghiệp vụ dự đoán được.

## Authentication

CDO chọn một trong các cơ chế sau:

- mTLS/service mesh policy.
- ServiceAccount token nội bộ.
- Bearer token qua Secret.

Header bắt buộc nếu dùng token:

```http
Authorization: Bearer <token>
X-AIOPS-Account: <account>
X-Request-Id: <uuid>
```

## Endpoints

| Method | Path | Mục đích |
| --- | --- | --- |
| `GET` | `/healthz` | Liveness đơn giản |
| `GET` | `/readyz` | Readiness, kiểm tra store/policy/kubernetes client |
| `GET` | `/v1/actions/catalog` | Trả allowlist action executor đang chấp nhận |
| `POST` | `/v1/actions/plan` | Dry-run plan, snapshot before-state, plan hash |
| `POST` | `/v1/actions/execute` | Execute đúng plan đã tạo |
| `GET` | `/v1/actions/{execution_id}` | Đọc trạng thái execution |
| `POST` | `/v1/actions/{execution_id}/rollback` | Rollback bằng rollback token |

## JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://techx.local/schemas/self-heal-executor-api.json",
  "title": "Self-heal Executor API",
  "type": "object",
  "$defs": {
    "ActionRequest": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "request_id",
        "incident_id",
        "action_id",
        "action_type",
        "target",
        "target_kind",
        "namespace",
        "policy_id",
        "policy_approved",
        "idempotency_key",
        "reason",
        "requested_by",
        "dry_run"
      ],
      "properties": {
        "request_id": { "type": "string", "minLength": 8 },
        "incident_id": { "type": "string", "minLength": 1 },
        "action_id": { "type": "string", "minLength": 1 },
        "action_type": {
          "type": "string",
          "enum": ["scale_deployment", "restore_deployment_replicas", "restart_deployment", "page"]
        },
        "target": { "type": "string", "minLength": 1 },
        "target_kind": { "type": "string", "enum": ["Deployment", "OnCall"] },
        "namespace": { "type": "string", "minLength": 1 },
        "replicas": { "type": "integer", "minimum": 0 },
        "policy_id": { "type": "string", "minLength": 1 },
        "policy_approved": { "type": "boolean" },
        "approval_id": { "type": ["string", "null"] },
        "plan_hash": { "type": ["string", "null"] },
        "rollback_token": { "type": ["string", "null"] },
        "idempotency_key": { "type": "string", "minLength": 16 },
        "reason": { "type": "string", "minLength": 1 },
        "requested_by": { "type": "string", "enum": ["aiops-runtime"] },
        "dry_run": { "type": "boolean" },
        "root_cause": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "service": { "type": "string" },
            "score": { "type": "number", "minimum": 0 },
            "metrics": {
              "type": "array",
              "items": { "type": "string" }
            },
            "evidence_scores": {
              "type": "object",
              "additionalProperties": { "type": "number" }
            }
          }
        },
        "safety": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "protected_targets": { "type": "array", "items": { "type": "string" } },
            "blast_radius_services": { "type": "array", "items": { "type": "string" } },
            "cost_status_current": { "type": "boolean" }
          }
        }
      }
    },
    "ActionResponse": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "ok",
        "allowed",
        "executed",
        "status",
        "action_id",
        "target",
        "message",
        "reasons"
      ],
      "properties": {
        "ok": { "type": "boolean" },
        "allowed": { "type": "boolean" },
        "executed": { "type": "boolean" },
        "status": {
          "type": "string",
          "enum": ["planned", "running", "succeeded", "failed", "blocked", "rolled_back"]
        },
        "execution_id": { "type": ["string", "null"] },
        "action_id": { "type": "string" },
        "target": { "type": "string" },
        "message": { "type": "string" },
        "reasons": {
          "type": "array",
          "items": { "type": "string" }
        },
        "plan_hash": { "type": ["string", "null"] },
        "expires_at": { "type": ["string", "null"], "format": "date-time" },
        "before": { "type": ["object", "null"] },
        "after": { "type": ["object", "null"] },
        "verification": {
          "type": "object",
          "additionalProperties": false,
          "required": ["defined", "passed"],
          "properties": {
            "defined": { "type": "boolean" },
            "passed": { "type": ["boolean", "null"] },
            "query_id": { "type": ["string", "null"] },
            "message": { "type": ["string", "null"] }
          }
        },
        "rollback": {
          "type": "object",
          "additionalProperties": false,
          "required": ["defined"],
          "properties": {
            "defined": { "type": "boolean" },
            "rollback_token": { "type": ["string", "null"] },
            "action_id": { "type": ["string", "null"] }
          }
        }
      }
    }
  }
}
```

## `POST /v1/actions/plan`

Request dùng schema `ActionRequest` với `dry_run=true`.

Executor phải:

- Resolve `action_id` từ allowlist nội bộ.
- Chụp `before` snapshot.
- Tính `plan_hash`.
- Trả `rollback_token` nếu action mutating có thể rollback.
- Không mutate hệ thống.

Ví dụ request:

```json
{
  "request_id": "req-20260728-0001",
  "incident_id": "inc-payment-001",
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "replicas": 3,
  "policy_id": "phase3-scale-policy-v1",
  "policy_approved": true,
  "approval_id": "adr-live-001",
  "plan_hash": null,
  "rollback_token": null,
  "idempotency_key": "sha256:incident-action-plan-001",
  "reason": "cpu_saturation",
  "requested_by": "aiops-runtime",
  "dry_run": true,
  "root_cause": {
    "service": "product-catalog",
    "score": 0.81,
    "metrics": ["cpu_millicores"],
    "evidence_scores": {
      "weighted_rrf": 0.91,
      "shape_correlation": 0.12,
      "support": 0.71
    }
  },
  "safety": {
    "protected_targets": ["postgresql", "kafka", "valkey-cart", "payment"],
    "blast_radius_services": ["frontend", "checkout"],
    "cost_status_current": true
  }
}
```

Ví dụ response:

```json
{
  "ok": true,
  "allowed": true,
  "executed": false,
  "status": "planned",
  "execution_id": null,
  "action_id": "scale_product_catalog",
  "target": "product-catalog",
  "message": "dry-run scale deployment/product-catalog from 2 to 3 replicas",
  "reasons": [],
  "plan_hash": "sha256:plan-abc123",
  "expires_at": "2026-07-28T10:30:00Z",
  "before": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "product-catalog",
    "replicas": 2,
    "resource_version": "912345"
  },
  "after": {
    "replicas": 3
  },
  "verification": {
    "defined": true,
    "passed": null,
    "query_id": "product-catalog.p95_latency_5m",
    "message": null
  },
  "rollback": {
    "defined": true,
    "rollback_token": "rb:inc-payment-001:scale_product_catalog:912345",
    "action_id": "restore_deployment_replicas"
  }
}
```

## `POST /v1/actions/execute`

Request dùng schema `ActionRequest` với:

- `dry_run=false`
- `plan_hash` lấy từ response plan
- `rollback_token` lấy từ response plan
- cùng `idempotency_key` hoặc một key execute ổn định do AI runtime tạo

Executor phải reject nếu current resource state khác `before.resource_version`.

Ví dụ request:

```json
{
  "request_id": "req-20260728-0002",
  "incident_id": "inc-payment-001",
  "action_id": "scale_product_catalog",
  "action_type": "scale_deployment",
  "target": "product-catalog",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "replicas": 3,
  "policy_id": "phase3-scale-policy-v1",
  "policy_approved": true,
  "approval_id": "adr-live-001",
  "plan_hash": "sha256:plan-abc123",
  "rollback_token": "rb:inc-payment-001:scale_product_catalog:912345",
  "idempotency_key": "sha256:incident-action-execute-001",
  "reason": "cpu_saturation",
  "requested_by": "aiops-runtime",
  "dry_run": false
}
```

Ví dụ response:

```json
{
  "ok": true,
  "allowed": true,
  "executed": true,
  "status": "running",
  "execution_id": "exec-20260728-0001",
  "action_id": "scale_product_catalog",
  "target": "product-catalog",
  "message": "scale submitted",
  "reasons": [],
  "plan_hash": "sha256:plan-abc123",
  "expires_at": null,
  "before": {
    "replicas": 2,
    "resource_version": "912345"
  },
  "after": {
    "replicas": 3
  },
  "verification": {
    "defined": true,
    "passed": null,
    "query_id": "product-catalog.p95_latency_5m",
    "message": "verification pending"
  },
  "rollback": {
    "defined": true,
    "rollback_token": "rb:inc-payment-001:scale_product_catalog:912345",
    "action_id": "restore_deployment_replicas"
  }
}
```

## `GET /v1/actions/{execution_id}`

Ví dụ response:

```json
{
  "ok": true,
  "allowed": true,
  "executed": true,
  "status": "succeeded",
  "execution_id": "exec-20260728-0001",
  "action_id": "scale_product_catalog",
  "target": "product-catalog",
  "message": "verification passed",
  "reasons": [],
  "plan_hash": "sha256:plan-abc123",
  "expires_at": null,
  "before": {
    "replicas": 2,
    "resource_version": "912345"
  },
  "after": {
    "replicas": 3,
    "ready_replicas": 3
  },
  "verification": {
    "defined": true,
    "passed": true,
    "query_id": "product-catalog.p95_latency_5m",
    "message": "latency and ready pods recovered"
  },
  "rollback": {
    "defined": true,
    "rollback_token": "rb:inc-payment-001:scale_product_catalog:912345",
    "action_id": "restore_deployment_replicas"
  }
}
```

## `POST /v1/actions/{execution_id}/rollback`

Request:

```json
{
  "request_id": "req-20260728-0003",
  "incident_id": "inc-payment-001",
  "rollback_token": "rb:inc-payment-001:scale_product_catalog:912345",
  "reason": "verification_failed",
  "requested_by": "aiops-runtime",
  "idempotency_key": "sha256:incident-action-rollback-001"
}
```

Response dùng schema `ActionResponse`.

Ví dụ response:

```json
{
  "ok": true,
  "allowed": true,
  "executed": true,
  "status": "rolled_back",
  "execution_id": "exec-20260728-0001",
  "action_id": "restore_deployment_replicas",
  "target": "product-catalog",
  "message": "replicas restored from 3 to 2",
  "reasons": [],
  "plan_hash": "sha256:plan-abc123",
  "expires_at": null,
  "before": {
    "replicas": 3
  },
  "after": {
    "replicas": 2
  },
  "verification": {
    "defined": true,
    "passed": true,
    "query_id": "product-catalog.workload_ready_pods",
    "message": "rollback verified"
  },
  "rollback": {
    "defined": true,
    "rollback_token": null,
    "action_id": null
  }
}
```

## Blocking response chuẩn

Executor trả HTTP `200` hoặc `409` đều được, nhưng body phải cùng shape để AI runtime ghi audit dễ dàng.

```json
{
  "ok": true,
  "allowed": false,
  "executed": false,
  "status": "blocked",
  "execution_id": null,
  "action_id": "scale_product_catalog",
  "target": "product-catalog",
  "message": "policy blocked action",
  "reasons": ["missing_approval", "plan_expired"],
  "plan_hash": null,
  "expires_at": null,
  "before": null,
  "after": null,
  "verification": {
    "defined": true,
    "passed": null,
    "query_id": null,
    "message": null
  },
  "rollback": {
    "defined": true,
    "rollback_token": null,
    "action_id": "restore_deployment_replicas"
  }
}
```

## Audit event bắt buộc

Mỗi transition phải ghi append-only audit event:

```json
{
  "event_id": "evt-20260728-0001",
  "timestamp": "2026-07-28T10:01:00Z",
  "request_id": "req-20260728-0002",
  "incident_id": "inc-payment-001",
  "execution_id": "exec-20260728-0001",
  "action_id": "scale_product_catalog",
  "event_type": "execute_submitted",
  "actor_type": "service",
  "actor_id": "aiops-runtime",
  "policy_id": "phase3-scale-policy-v1",
  "allowed": true,
  "executed": true,
  "reasons": [],
  "target": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "product-catalog"
  }
}
```

## Acceptance criteria cho CDO

- `plan` cùng input phải idempotent trong thời gian plan chưa hết hạn.
- `execute` cùng `idempotency_key` không được mutate lần hai.
- Mutating action trên protected target phải bị block.
- Mutating action thiếu rollback hoặc verification phải bị block.
- State đổi sau plan phải bị block bằng `resource_version_mismatch`.
- Rollback phải restore đúng snapshot trước action.
- Audit log đủ để truy vết `incident_id -> plan -> execute -> verify -> rollback`.
