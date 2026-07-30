# Self-heal Live Executor Scale Smoke Test Report

- Ngày kiểm thử: 2026-07-30
- Môi trường: `techx-corp-prod` trên EKS `techx-tf2-prod`
- Namespace: `techx-corp-prod`
- Executor: `Deployment/aiops-live-executor`

Action kiểm thử chính: `scale_cart`

## 1. Tóm tắt kết quả

CDO đã kiểm thử thành công luồng live self-heal scale theo đường giống thực tế mà AI runtime sẽ gọi:

```text
AI runtime -> HTTP executor endpoint -> policy/approval/allowlist -> Kubernetes API -> HPA/Deployment mutation -> rollback
```

Kết quả chức năng:

- `GET /healthz` trả `200`.
- `GET /readyz` trả `200`.
- `POST /v1/actions/plan` tạo plan hợp lệ với `allowed=true`.
- `POST /v1/actions/execute` scale live thành công `cart`.
- HPA `cart` đã tăng `MINPODS` từ `2` lên `3`.
- `POST /v1/actions/{execution_id}/rollback` rollback thành công.
- HPA `cart` đã về lại `MINPODS=2`.

Kết luận: đường executor live scale/rollback đã chạy thật trên Kubernetes. Phần còn thiếu là escalation tự động khi rollback fail; hiện việc đó chưa được implement end-to-end.

## 2. Phạm vi kiểm thử

Action được test live:

- `scale_cart`

Các action cùng nhóm đã được support bởi executor nhưng chưa ghi nhận trong test này:

- `scale_frontend_proxy`
- `scale_frontend`
- `scale_checkout`
- `scale_product_catalog`

Target live:

- `HorizontalPodAutoscaler/cart`
- `Deployment/cart`
- Pods có label `app.kubernetes.io/name=cart`

## 3. Điều kiện trước khi test

### 3.1. Secret executor

Kubernetes Secret phải có đủ 2 key:

- `token`
- `approval-id`

Lệnh kiểm tra:

```bash
kubectl -n techx-corp-prod get secret aiops-live-executor-token -o json | jq -r '.data | keys[]'
```

Kết quả:

```text
approval-id
token
```

ExternalSecret phải sync thành công:

```bash
kubectl -n techx-corp-prod get externalsecret aiops-live-executor-token \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{" "}{.status.conditions[?(@.type=="Ready")].reason}{" "}{.status.conditions[?(@.type=="Ready")].message}{"\n"}'
```

Kết quả:

```text
True SecretSynced secret synced
```

Ghi chú: AWS Secrets Manager secret đúng là `techx-corp/production/aiops-live-executor-token` ở region `us-east-1`, account `493499579600`, với JSON shape:

```json
{
  "token": "<executor-token>",
  "approval_id": "<signed-approval-id>"
}
```

### 3.2. Executor pod readiness

Lệnh kiểm tra:

```bash
kubectl -n techx-corp-prod get deploy aiops-live-executor
kubectl -n techx-corp-prod get pods -l app.kubernetes.io/name=aiops-live-executor -o wide
```

Kết quả:

```text
NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
aiops-live-executor   1/1     1            1           15h
NAME                                   READY   STATUS    RESTARTS   AGE   IP            NODE                         NOMINATED NODE   READINESS GATES
aiops-live-executor-7b58545f5f-wv7b2   2/2     Running   0          37m   10.0.24.101   ip-10-0-16-39.ec2.internal   <none>           <none>
```

### 3.3. Linkerd/Kubernetes API readiness fix

Khi live mode bật, `/readyz` gọi Kubernetes API để snapshot các Deployment allowlist. Pod executor cần bypass Linkerd outbound port `443` để không làm hỏng TLS tới `https://kubernetes.default.svc`.

Annotation kỳ vọng trên pod template:

```text
config.linkerd.io/skip-outbound-ports: "443,10000,9901"
```

Lệnh kiểm tra:

```bash
kubectl -n techx-corp-prod get deploy aiops-live-executor \
  -o jsonpath='{.spec.template.metadata.annotations.config\.linkerd\.io/skip-outbound-ports}{"\n"}'
```

Kết quả:

```text
443,10000,9901
```

### 3.4. Executor env

Không in token thật vào report. Chỉ kiểm tra các env non-secret và có approval id.

```bash
kubectl -n techx-corp-prod exec deploy/aiops-live-executor -c aiops-live-executor -- printenv \
  | sort \
  | grep '^AIOPS_' \
  | sed 's/AIOPS_LIVE_EXECUTOR_TOKEN=.*/AIOPS_LIVE_EXECUTOR_TOKEN=<redacted>/'
```

Các giá trị quan trọng:

- `AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY=true`
- `AIOPS_LIVE_EXECUTOR_APPROVAL_ID=adr-live-001`
- `AIOPS_LIVE_EXECUTOR_POLICY_ID=phase3-scale-policy-v1`
- `AIOPS_LIVE_EXECUTOR_POLICY_EXPIRES_AT=2026-08-31T23:59:59Z`

## 4. Port-forward và health/readiness

Terminal 1:

```bash
kubectl -n techx-corp-prod port-forward svc/aiops-live-executor 8080:8080
```

Kết quả:

```text
Forwarding from 127.0.0.1:8080 -> 8000
Forwarding from [::1]:8080 -> 8000
Handling connection for 8080
```

Terminal 2:

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

Kết quả:

```text
{"status":"ok"}{"status":"ready"}
```

Tiêu chí pass:

```json
{"status":"ok"}
{"status":"ready"}
```

## 5. Lấy token test

Không ghi token thật vào report.

```bash
TOKEN=$(kubectl -n techx-corp-prod get secret aiops-live-executor-token -o jsonpath='{.data.token}' | base64 -d)
```

## 6. Kiểm tra action catalog

```bash
curl -fsS http://127.0.0.1:8080/v1/actions/catalog \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-AIOps-Account: techx-corp-prod" \
  -H "X-Request-ID: smoke-catalog-001" | jq
```

Kết quả:

```json
[
  {
    "action_id": "restart_payment",
    "action_type": "restart",
    "target": "payment",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": true,
    "blocked": true,
    "blocked_reason": "payment is a protected target; CDO executor must not mutate it",
    "blast_radius_services": [
      "checkout"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "restart_checkout",
    "action_type": "restart",
    "target": "checkout",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend",
      "frontend-proxy"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "scale_checkout",
    "action_type": "scale_deployment",
    "target": "checkout",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": true,
    "live_execute_supported": true,
    "rollback_supported": true,
    "rollback_action_id": "restore_deployment_replicas",
    "verification_query_id": "checkout_p95_latency_5m",
    "policy_id": "phase3-scale-policy-v1",
    "policy_approval_required": true,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend",
      "frontend-proxy",
      "cart",
      "payment",
      "shipping",
      "email"
    ],
    "min_replicas": 1,
    "max_replicas": 3,
    "target_replicas": 3,
    "owner": "checkout-owner",
    "live_execute_capable": true
  },
  {
    "action_id": "restart_cart",
    "action_type": "restart",
    "target": "cart",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "checkout",
      "frontend"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "scale_cart",
    "action_type": "scale_deployment",
    "target": "cart",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": true,
    "live_execute_supported": true,
    "rollback_supported": true,
    "rollback_action_id": "restore_deployment_replicas",
    "verification_query_id": "cart_error_rate_5m",
    "policy_id": "phase3-scale-policy-v1",
    "policy_approval_required": true,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "checkout",
      "frontend"
    ],
    "min_replicas": 1,
    "max_replicas": 3,
    "target_replicas": 3,
    "owner": "cart-owner",
    "live_execute_capable": true
  },
  {
    "action_id": "restart_frontend",
    "action_type": "restart",
    "target": "frontend",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend-proxy"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "scale_frontend",
    "action_type": "scale_deployment",
    "target": "frontend",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": true,
    "live_execute_supported": true,
    "rollback_supported": true,
    "rollback_action_id": "restore_deployment_replicas",
    "verification_query_id": "frontend_p95_latency_5m",
    "policy_id": "phase3-scale-policy-v1",
    "policy_approval_required": true,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend-proxy",
      "checkout",
      "product-catalog",
      "cart"
    ],
    "min_replicas": 1,
    "max_replicas": 3,
    "target_replicas": 3,
    "owner": "frontend-owner",
    "live_execute_capable": true
  },
  {
    "action_id": "restart_frontend_proxy",
    "action_type": "restart",
    "target": "frontend-proxy",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend",
      "checkout",
      "product-catalog",
      "cart"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "scale_frontend_proxy",
    "action_type": "scale_deployment",
    "target": "frontend-proxy",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": true,
    "live_execute_supported": true,
    "rollback_supported": true,
    "rollback_action_id": "restore_deployment_replicas",
    "verification_query_id": "frontend_proxy_p95_latency_5m",
    "policy_id": "phase3-scale-policy-v1",
    "policy_approval_required": true,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend",
      "checkout",
      "product-catalog",
      "cart"
    ],
    "min_replicas": 1,
    "max_replicas": 3,
    "target_replicas": 3,
    "owner": "platform-edge-owner",
    "live_execute_capable": true
  },
  {
    "action_id": "restart_product_catalog",
    "action_type": "restart",
    "target": "product-catalog",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": false,
    "recommendation_only": true,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "blast_radius_services": [
      "frontend",
      "recommendation",
      "product-reviews",
      "checkout"
    ],
    "live_execute_capable": false
  },
  {
    "action_id": "scale_product_catalog",
    "action_type": "scale_deployment",
    "target": "product-catalog",
    "target_kind": "Deployment",
    "namespace": "techx-corp-prod",
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": false,
    "dry_run_supported": true,
    "execute_supported": true,
    "live_execute_supported": true,
    "rollback_supported": true,
    "rollback_action_id": "restore_deployment_replicas",
    "verification_query_id": "product_catalog_cpu_millicores",
    "policy_id": "phase3-scale-policy-v1",
    "policy_approval_required": true,
    "protected": false,
    "blocked": false,
    "blocked_reason": null,
    "min_replicas": 2,
    "max_replicas": 12,
    "target_replicas": 3,
    "blast_radius_services": [
      "frontend",
      "recommendation",
      "product-reviews",
      "checkout"
    ],
    "owner": "product-catalog-owner",
    "live_execute_capable": true
  },
  {
    "action_id": "page_data_oncall",
    "action_type": "page",
    "target": "data-platform-oncall",
    "target_kind": "OnCall",
    "namespace": null,
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": true,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": "page actions are audit-only and do not call a real paging provider",
    "blast_radius_services": [],
    "live_execute_capable": false
  },
  {
    "action_id": "page_oncall",
    "action_type": "page",
    "target": "platform-team",
    "target_kind": "OnCall",
    "namespace": null,
    "executor_supported": true,
    "recommendation_only": false,
    "audit_only": true,
    "dry_run_supported": true,
    "execute_supported": false,
    "live_execute_supported": false,
    "rollback_supported": false,
    "verification_query_id": null,
    "policy_id": null,
    "policy_approval_required": false,
    "protected": false,
    "blocked": false,
    "blocked_reason": "page actions are audit-only and do not call a real paging provider",
    "blast_radius_services": [],
    "live_execute_capable": false
  }
]
```

Tiêu chí pass:

- Có `scale_cart`.
- `scale_cart.live_execute_supported=true` khi live overlay bật.
- Có các action executable khác: `scale_frontend_proxy`, `scale_frontend`, `scale_checkout`, `scale_product_catalog`.

## 7. Baseline trước khi scale

```bash
kubectl -n techx-corp-prod get hpa cart
kubectl -n techx-corp-prod get deploy cart
kubectl -n techx-corp-prod get pods -l app.kubernetes.io/name=cart
```

Kết quả:

```text
NAME   REFERENCE         TARGETS                          MINPODS   MAXPODS   REPLICAS   AGE
cart   Deployment/cart   cpu: 23%/70%, 17914m/150 (avg)   2         12        2          16d
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
cart   2/2     2            2           16d
NAME                    READY   STATUS    RESTARTS   AGE
cart-5b75485cdc-7ch4k   2/2     Running   0          11h
cart-5b75485cdc-7j272   2/2     Running   0          11h
```

Baseline kỳ vọng trước test:

- HPA `cart` có `MINPODS=2`.
- Deployment `cart` có `2/2`.
- Có 2 pod `cart` running.

## 8. Plan live scale

Lưu ý quan trọng:

- `idempotency_key` phải có format `sha256:<64 hex chars>`.
- `plan` và `execute` nên chạy sát nhau. Nếu resourceVersion của HPA/Deployment đổi giữa 2 bước, executor sẽ block bằng `resource_version_mismatch`.
- Chỉ chạy `execute` khi `plan` trả `allowed=true` và `plan_hash` không phải `null`.

Tạo request plan:

```bash
REQ_ID="smoke-scale-cart-$(date +%s)"
PLAN_KEY="sha256:$(openssl rand -hex 32)"
EXEC_KEY="sha256:$(openssl rand -hex 32)"

cat > /tmp/aiops-scale-cart.json <<EOF
{
  "schema_version": "1.0",
  "request_id": "$REQ_ID-plan",
  "incident_id": "smoke-live-scale-cart",
  "action_id": "scale_cart",
  "action_type": "scale_deployment",
  "target": "cart",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "replicas": 3,
  "policy_id": "phase3-scale-policy-v1",
  "policy_approved": true,
  "policy_expires_at": "2026-08-31T23:59:59Z",
  "approval_id": "adr-live-001",
  "idempotency_key": "$PLAN_KEY",
  "reason": "live smoke test for AI runtime executor path",
  "requested_by": "aiops-runtime",
  "dry_run": false,
  "safety": {
    "protected_targets": [],
    "blast_radius_services": ["cart"],
    "cost_status_current": true
  }
}
EOF
```

Gọi plan:

```bash
curl -fsS http://127.0.0.1:8080/v1/actions/plan \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-AIOps-Account: techx-corp-prod" \
  -H "X-Request-ID: $REQ_ID-plan" \
  -H "Content-Type: application/json" \
  --data @/tmp/aiops-scale-cart.json | tee /tmp/aiops-plan.json | jq
```

Kết quả:

```json
{
  "ok": true,
  "allowed": true,
  "executed": false,
  "status": "planned",
  "execution_id": null,
  "executed_at": null,
  "action_id": "scale_cart",
  "action_type": "scale_deployment",
  "target": "cart",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "dry-run scale deployment/cart from 2 to 3 replicas",
  "reasons": [],
  "plan_hash": "sha256:bc3bd3e17e72a410e91cb37c5da61f3f4bf25b022168c852a1f94de4153a8b27",
  "expires_at": "2026-07-29T17:17:46Z",
  "before": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "cart",
    "replicas": 2,
    "ready_replicas": 2,
    "scaling_controller": "HorizontalPodAutoscaler",
    "control_replicas": 2,
    "resource_version": "12100331",
    "autoscaler_max_replicas": 12,
    "autoscaler_name": "cart",
    "deployment_resource_version": "11982434"
  },
  "after": {
    "replicas": 3,
    "control_replicas": 3,
    "scaling_controller": "HorizontalPodAutoscaler"
  },
  "verification": {
    "defined": true,
    "passed": null,
    "query_id": "cart_error_rate_5m",
    "message": null
  },
  "rollback": {
    "defined": true,
    "rollback_token": "rbt:b86ee3f85fd64ac3013aca20360e0ebffa71d88137e9b828c1183958f316722e",
    "action_id": "restore_deployment_replicas"
  },
  "incident_id": "smoke-live-scale-cart"
}
```

Tiêu chí pass:

- `allowed=true`
- `executed=false`
- `status=planned`
- Có `plan_hash`
- Có `rollback.rollback_token`
- `before` ghi nhận baseline.
- `after` ghi nhận target scale.

## 9. Execute live scale

Tạo execute request từ plan vừa tạo:

```bash
PLAN_HASH=$(jq -r '.plan_hash' /tmp/aiops-plan.json)
ROLLBACK_TOKEN=$(jq -r '.rollback.rollback_token' /tmp/aiops-plan.json)

jq \
  --arg request_id "$REQ_ID-execute" \
  --arg idempotency_key "$EXEC_KEY" \
  --arg plan_hash "$PLAN_HASH" \
  --arg rollback_token "$ROLLBACK_TOKEN" \
  '. + {
    request_id: $request_id,
    idempotency_key: $idempotency_key,
    plan_hash: $plan_hash,
    rollback_token: $rollback_token
  }' \
  /tmp/aiops-scale-cart.json > /tmp/aiops-execute-cart.json
```

Gọi execute:

```bash
curl -fsS http://127.0.0.1:8080/v1/actions/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-AIOps-Account: techx-corp-prod" \
  -H "X-Request-ID: $REQ_ID-execute" \
  -H "Content-Type: application/json" \
  --data @/tmp/aiops-execute-cart.json | tee /tmp/aiops-execute.json | jq
```

Kết quả:

```json
{
  "ok": true,
  "allowed": true,
  "executed": true,
  "status": "running",
  "execution_id": "exec-201848f72b383d99",
  "executed_at": "2026-07-29T17:07:47Z",
  "action_id": "scale_cart",
  "action_type": "scale_deployment",
  "target": "cart",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "scaled deployment/cart from 2 to 2 replicas",
  "reasons": [],
  "plan_hash": "sha256:bc3bd3e17e72a410e91cb37c5da61f3f4bf25b022168c852a1f94de4153a8b27",
  "expires_at": null,
  "before": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "cart",
    "replicas": 2,
    "ready_replicas": 2,
    "scaling_controller": "HorizontalPodAutoscaler",
    "control_replicas": 2,
    "resource_version": "12100331",
    "autoscaler_max_replicas": 12,
    "autoscaler_name": "cart",
    "deployment_resource_version": "11982434"
  },
  "after": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "cart",
    "replicas": 2,
    "ready_replicas": 2,
    "scaling_controller": "HorizontalPodAutoscaler",
    "control_replicas": 3,
    "resource_version": "12100458",
    "autoscaler_max_replicas": 12,
    "autoscaler_name": "cart",
    "deployment_resource_version": "11982434",
    "requested_replicas": 3
  },
  "verification": {
    "defined": true,
    "passed": null,
    "query_id": "cart_error_rate_5m",
    "message": null
  },
  "rollback": {
    "defined": true,
    "rollback_token": "rbt:b86ee3f85fd64ac3013aca20360e0ebffa71d88137e9b828c1183958f316722e",
    "action_id": "restore_deployment_replicas"
  },
  "incident_id": "smoke-live-scale-cart"
}
```

Tiêu chí pass:

- `allowed=true`
- `executed=true`
- Có `execution_id`
- Có `rollback.rollback_token` hoặc `rollback_token` phục vụ rollback.
- `after` phản ánh Kubernetes state sau mutation.

## 10. Xác nhận scale live

```bash
kubectl -n techx-corp-prod get hpa cart
kubectl -n techx-corp-prod get deploy cart
kubectl -n techx-corp-prod get pods -l app.kubernetes.io/name=cart
```

Kết quả:

```text
NAME   REFERENCE         TARGETS                          MINPODS   MAXPODS   REPLICAS   AGE
cart   Deployment/cart   cpu: 30%/70%, 12756m/150 (avg)   3         12        3          16d
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
cart   2/3     3            2           16d
NAME                    READY   STATUS    RESTARTS   AGE
cart-5b75485cdc-7ch4k   2/2     Running   0          11h
cart-5b75485cdc-7j272   2/2     Running   0          11h
cart-5b75485cdc-zp2d6   2/2     Running   0          21s
```

Tiêu chí pass:

- HPA `cart` có `MINPODS=3`.
- Deployment/pods tiến tới 3 replicas theo controller.

## 11. Rollback về baseline

Lấy execution id và rollback token:

```bash
EXECUTION_ID=$(jq -r '.execution_id' /tmp/aiops-execute.json)
ROLLBACK_TOKEN=$(jq -r '.rollback.rollback_token // .rollback_token' /tmp/aiops-execute.json)
ROLLBACK_REQ_ID="smoke-rollback-cart-$(date +%s)"
ROLLBACK_KEY="sha256:$(openssl rand -hex 32)"

echo "EXECUTION_ID=$EXECUTION_ID"
echo "ROLLBACK_TOKEN=$ROLLBACK_TOKEN"
```

Kết quả:

```text
EXECUTION_ID=exec-201848f72b383d99
ROLLBACK_TOKEN=rbt:b86ee3f85fd64ac3013aca20360e0ebffa71d88137e9b828c1183958f316722e
```

Gọi rollback:

```bash
curl -fsS http://127.0.0.1:8080/v1/actions/$EXECUTION_ID/rollback \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-AIOps-Account: techx-corp-prod" \
  -H "X-Request-ID: $ROLLBACK_REQ_ID" \
  -H "Content-Type: application/json" \
  --data "{
    \"request_id\":\"$ROLLBACK_REQ_ID\",
    \"incident_id\":\"smoke-live-scale-cart\",
    \"rollback_token\":\"$ROLLBACK_TOKEN\",
    \"reason\":\"rollback after live smoke test\",
    \"requested_by\":\"aiops-runtime\",
    \"idempotency_key\":\"$ROLLBACK_KEY\"
  }" | tee /tmp/aiops-rollback.json | jq
```

Kết quả:

```json
{
  "ok": true,
  "allowed": true,
  "executed": true,
  "status": "rolled_back",
  "execution_id": "exec-201848f72b383d99",
  "executed_at": "2026-07-29T17:10:23Z",
  "action_id": "restore_deployment_replicas",
  "action_type": "restore_deployment_replicas",
  "target": "cart",
  "target_kind": "Deployment",
  "namespace": "techx-corp-prod",
  "message": "restored deployment/cart replicas from 2 to 2",
  "reasons": [],
  "plan_hash": null,
  "expires_at": null,
  "before": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "cart",
    "replicas": 2,
    "ready_replicas": 2,
    "scaling_controller": "HorizontalPodAutoscaler",
    "control_replicas": 2,
    "resource_version": "12102177",
    "autoscaler_max_replicas": 12,
    "autoscaler_name": "cart",
    "deployment_resource_version": "12102106"
  },
  "after": {
    "kind": "Deployment",
    "namespace": "techx-corp-prod",
    "name": "cart",
    "replicas": 2,
    "ready_replicas": 2,
    "scaling_controller": "HorizontalPodAutoscaler",
    "control_replicas": 2,
    "resource_version": "12102177",
    "autoscaler_max_replicas": 12,
    "autoscaler_name": "cart",
    "deployment_resource_version": "12102106"
  },
  "verification": {
    "defined": true,
    "passed": true,
    "query_id": "scaling_controller_and_ready_replicas",
    "message": "rollback replica snapshot restored"
  },
  "rollback": {
    "defined": true,
    "rollback_token": null,
    "action_id": "restore_deployment_replicas"
  },
  "rollback_id": "rb-b9816c8c67bdbe7f",
  "incident_id": "smoke-live-scale-cart"
}
```

Tiêu chí pass:

- `allowed=true`
- `executed=true`
- `status=rolled_back`

## 12. Xác nhận rollback live

```bash
kubectl -n techx-corp-prod get hpa cart
kubectl -n techx-corp-prod get deploy cart
kubectl -n techx-corp-prod get pods -l app.kubernetes.io/name=cart
```

Kết quả:

```text
NAME   REFERENCE         TARGETS                          MINPODS   MAXPODS   REPLICAS   AGE
cart   Deployment/cart   cpu: 32%/70%, 19605m/150 (avg)   2         12        2          16d
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
cart   2/2     2            2           16d
NAME                    READY   STATUS    RESTARTS   AGE
cart-5b75485cdc-7ch4k   2/2     Running   0          11h
cart-5b75485cdc-7j272   2/2     Running   0          11h
```

Tiêu chí pass:

- HPA `cart` về `MINPODS=2`.
- Deployment/pods scale down về baseline theo controller.

## 13. Các lỗi đã gặp trong quá trình test và cách xử lý

### 13.1. Thiếu `approval-id` trong Kubernetes Secret

Triệu chứng:

```text
CreateContainerConfigError
Error: couldn't find key approval-id in Secret techx-corp-prod/aiops-live-executor-token
```

Nguyên nhân:

- Chart yêu cầu Secret key `approval-id`.
- ExternalSecret đọc property `approval_id` từ AWS Secrets Manager.
- AWS secret ban đầu chỉ có `token`, chưa có `approval_id`.

Cách xử lý:

- Update AWS Secrets Manager secret `techx-corp/production/aiops-live-executor-token` ở `us-east-1` với JSON chứa cả `token` và `approval_id`.
- Force sync ExternalSecret.

Lệnh force sync:

```bash
kubectl -n techx-corp-prod annotate externalsecret aiops-live-executor-token force-sync="$(date +%s)" --overwrite
```

### 13.2. `/readyz` trả `503`

Triệu chứng:

```text
GET /healthz -> 200
GET /readyz -> 503
```

Nguyên nhân chi tiết:

- Live executor readiness gọi Kubernetes API để snapshot allowlisted deployments.
- Pod đang được Linkerd inject.
- Outbound HTTPS tới `https://kubernetes.default.svc` qua Linkerd bị lỗi TLS:

```text
SSL: UNEXPECTED_EOF_WHILE_READING
```

Cách xử lý:

- Bypass Linkerd outbound port `443` cho riêng pod executor:

```text
config.linkerd.io/skip-outbound-ports: "443,10000,9901"
```

Kết quả sau fix:

```text
<điền kết quả>
```

### 13.3. `invalid_idempotency_key`

Triệu chứng:

```json
{
  "allowed": false,
  "reasons": ["invalid_idempotency_key"]
}
```

Nguyên nhân:

- `idempotency_key` không đúng format policy yêu cầu.

Format đúng:

```text
sha256:<64 hex chars>
```

Cách tạo:

```bash
IDEMPOTENCY_KEY="sha256:$(openssl rand -hex 32)"
```

### 13.4. `rollback_token_mismatch`

Triệu chứng:

```json
{
  "allowed": false,
  "reasons": ["rollback_token_mismatch"]
}
```

Nguyên nhân:

- Execute request chỉ có `plan_hash` nhưng thiếu `rollback_token`, hoặc dùng rollback token không khớp với plan.
- Cũng có thể do retry execute bằng cùng `idempotency_key` của lần block trước, khiến executor trả response cached.

Cách xử lý:

- Lấy `rollback.rollback_token` từ response plan.
- Gửi cả `plan_hash` và `rollback_token` trong execute request.
- Dùng `idempotency_key` mới cho execute.

### 13.5. `resource_version_mismatch`

Triệu chứng:

```json
{
  "allowed": false,
  "reasons": ["resource_version_mismatch"]
}
```

Nguyên nhân:

- Executor dùng optimistic concurrency.
- ResourceVersion ở thời điểm execute khác resourceVersion snapshot tại plan.
- Với HPA, resourceVersion có thể đổi nhanh do controller/status update.

Cách xử lý trong test:

- Tạo plan mới.
- Execute ngay sau plan.
- Không reuse plan cũ.

Ghi chú kỹ thuật:

- Nếu lỗi này lặp lại thường xuyên trong vận hành thật, cần cân nhắc refine guardrail để validate đúng spec/control resource thay vì fail vì status-only update.

## 14. Trạng thái escalation khi rollback fail

Yêu cầu vận hành mong muốn:

- Nếu rollback fail, hệ thống phải dừng retry nguy hiểm, ghi audit/error, và escalate tới con người/on-call.

Trạng thái hiện tại:

- Executor đã có cơ chế trả response nghiệp vụ khi action/rollback bị block hoặc fail, ví dụ `allowed=false`, `status=blocked`, `reasons=[...]`.
- Executor có audit/store phục vụ truy vết.
- Tuy nhiên, escalation tự động khi rollback fail hiện **chưa được implement end-to-end**.
- AI runtime phía AI team hiện cũng chưa triển khai runtime gọi executor và xử lý nhánh rollback failure.
- Chưa có bước tự động page/on-call/ticket khi rollback trả `allowed=false`, HTTP error, timeout, hoặc Kubernetes mutation error.

Gap cần làm tiếp:

- AI runtime phải detect rollback failure:
  - HTTP non-2xx;
  - `allowed=false`;
  - `executed=false`;
  - `status=blocked` hoặc `status=failed`;
  - response có `reasons` nghiêm trọng.
- AI runtime phải tạo escalation event/ticket/page kèm:
  - `incident_id`;
  - `execution_id`;
  - `action_id`;
  - `target`;
  - `plan_hash`;
  - `rollback_token` đã dùng, nếu được phép log dạng redacted;
  - `reasons`;
  - before/after snapshots;
  - link dashboard/logs.
- CDO cần xác định endpoint/kênh escalation chính thức: PagerDuty, Slack, Discord, Ops ticket, hoặc endpoint nội bộ.

Đánh giá rủi ro:

- Live scale và rollback thủ công qua API đã chứng minh được.
- Rollback fail escalation chưa có nên chưa thể tuyên bố self-heal production-ready hoàn chỉnh.
- Trước khi AI runtime tự động gọi live action, nhánh rollback-fail-escalate phải được implement và test.

## 15. Kết luận

Smoke test live scale cho `scale_cart` đã thành công:

- Executor ready.
- Auth/policy/approval pass.
- Plan pass.
- Execute scale live pass.
- HPA `cart` minPods tăng lên 3.
- Rollback pass.
- HPA `cart` minPods về lại 2.

Trạng thái còn lại:

- Cần merge chart fix để giữ Linkerd bypass port `443` qua GitOps, tránh drift từ patch live.
- Cần implement nhánh escalation tự động nếu rollback fail.
- Cần AI runtime implement client gọi executor contract và xử lý đầy đủ plan/execute/verify/rollback/escalate.
