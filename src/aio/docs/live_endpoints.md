# Live endpoint inventory (AWS EKS via port-forward)

Inventory này được kiểm tra với namespace `techx-corp-prod` ngày 2026-07-16. Các URL
`localhost` là tunnel tới workload thật trên EKS, không phải mock service.

## Endpoint bắt buộc

| Integration | Cluster target | URL/API dùng khi smoke test | Authentication |
|---|---|---|---|
| Prometheus | `svc/prometheus:9090` | `GET http://localhost:9090/api/v1/query`, `/api/v1/query_range`, `/api/v1/targets` | Không cần token qua port-forward |
| Grafana health | `svc/grafana:80` | `GET http://localhost:3000/api/health` | Không cần credential |
| Grafana webhook inbound | AIOps local process | `POST http://localhost:8000/api/v1/events/grafana` | Header `X-AIOps-Grafana-Secret` |
| Jaeger | `svc/jaeger:16686` | `GET http://localhost:16686/jaeger/ui/api/services`, `/api/traces` | Không cần token qua port-forward |
| OpenSearch | `svc/opensearch:9200` | `GET https://localhost:9200/`, `/_cat/indices`; `POST /<index>/_search` | HTTPS + Basic Auth bắt buộc |
| Kubernetes API | `kubectl proxy :8001` | `GET http://localhost:8001/api/v1/namespaces/techx-corp-prod/pods`; deployments API | Dùng credential của kubeconfig; không cần bearer token riêng |
| Notification | External receiver | `POST $AIOPS_NOTIFICATION_WEBHOOK_URL` | Tùy receiver; URL là bắt buộc, bearer token là tùy chọn |

## Secret/config còn thiếu

Không ghi giá trị secret vào repository hoặc terminal log. Chỉ tên nguồn được ghi ở
đây.

| Biến | Trạng thái | Nguồn/việc cần làm |
|---|---|---|
| `AIOPS_OPENSEARCH_USERNAME` | Bắt buộc | Kubernetes Secret `techx-corp-opensearch`, key `username` |
| `AIOPS_OPENSEARCH_PASSWORD` | Bắt buộc, hiện còn placeholder | Kubernetes Secret `techx-corp-opensearch`, key `password` |
| `AIOPS_NOTIFICATION_WEBHOOK_URL` | Bắt buộc, hiện còn placeholder | Cần một JSON webhook receiver tương thích. Secret `techx-corp-grafana-discord`/`webhook-url` chỉ là candidate; Discord cần adapter/payload riêng trước khi tái sử dụng trực tiếp |
| `AIOPS_NOTIFICATION_TOKEN` | Tùy chọn | Chỉ cần nếu receiver yêu cầu Bearer Auth |
| `AIOPS_GRAFANA_WEBHOOK_SECRET` | Bắt buộc | Tự sinh shared secret và cấu hình cùng giá trị ở AIOps và Grafana contact point |
| Grafana admin username/password | Chỉ cần khi provision contact point bằng Grafana API | Kubernetes Secret `techx-corp-grafana-admin` |

Prometheus token, Jaeger token và Kubernetes bearer token được để trống có chủ đích
khi chạy qua `kubectl port-forward`/`kubectl proxy`.

## Blocker của Grafana webhook end-to-end

Cluster hiện chưa có Deployment hoặc Service AIOps. Vì vậy Grafana trong EKS không
thể gọi `localhost:8000` trên máy developer. Test hiện tại xác minh hai phần độc lập:

1. Grafana thật trả health OK qua tunnel.
2. Payload Grafana-compatible được POST vào AIOps local với shared-secret auth.

Để nghiệm thu end-to-end, cần deploy AIOps thành ClusterIP Service (ví dụ
`http://aiops:8000/api/v1/events/grafana`) và provision Grafana contact point trỏ tới
Service đó.

## Cách chạy

Từ thư mục `src/aio`:

```powershell
Copy-Item .env.live.example .env.live
powershell -File scripts/port_forward.ps1
```

Trong terminal thứ hai, chạy AIOps bằng file live mà không copy secret vào `.env`
đang được Git track:

```powershell
$env:AIOPS_ENV_FILE = ".env.live"
python -m uvicorn aiops.api.app:create_app --factory --port 8000
```

Trong terminal thứ ba:

```powershell
python -B tests/smoke_test_live.py
python -B tests/smoke_test_live.py TestPrometheus
```

Smoke suite là strict: missing config, `401`, non-2xx và endpoint không kết nối được
đều trả exit code khác `0`; không có đường SKIP ngầm.
