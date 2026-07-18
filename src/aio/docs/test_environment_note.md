# Ghi chú môi trường kiểm thử AIOps

> Cập nhật: 2026-07-17
> Môi trường: AWS EKS, namespace `techx-corp-prod`  
> Phương thức kết nối: `kubectl port-forward` và `kubectl proxy`

## 1. Tổng quan

Các integration có thể kiểm tra khi chưa có credential thật đã được chuẩn hóa để
kết nối tới workload đang chạy trên EKS. Smoke test hiện chạy ở chế độ strict:
không còn trường hợp endpoint bị bỏ qua nhưng toàn bộ suite vẫn trả kết quả thành
công.

Prometheus, Jaeger, Kubernetes API và Grafana health không cần credential dịch vụ
riêng khi kết nối qua port-forward hoặc Kubernetes proxy. OpenSearch đã có Basic Auth
hợp lệ và vượt qua toàn bộ smoke test. Notification đã PASS. Grafana inbound
webhook còn FAIL vì chưa có AIOps process lắng nghe tại `localhost:8000`.

## 2. Trạng thái credential và secret

| Biến/thông tin | Mức độ | Trạng thái và nguồn |
|---|---|---|
| `AIOPS_OPENSEARCH_PASSWORD` | Bắt buộc | Đã cấu hình; smoke test xác nhận Basic Auth hợp lệ. Không ghi giá trị vào tài liệu |
| `AIOPS_OPENSEARCH_USERNAME` | Bắt buộc | Đã cấu hình; smoke test xác nhận Basic Auth hợp lệ. Không ghi giá trị vào tài liệu |
| `AIOPS_NOTIFICATION_WEBHOOK_URL` | Bắt buộc | Đã cấu hình và smoke test PASS; không ghi URL vào tài liệu |
| `AIOPS_NOTIFICATION_PROVIDER` | Tùy chọn | `auto` tự nhận diện Discord URL; hỗ trợ ép `generic` hoặc `discord` |
| `AIOPS_NOTIFICATION_TOKEN` | Tùy chọn | Chỉ cần khi notification receiver yêu cầu Bearer Auth |
| Grafana admin credential | Có điều kiện | Chỉ cần khi provision contact point bằng Grafana API; nguồn: Secret `techx-corp-grafana-admin` |
| `AIOPS_GRAFANA_WEBHOOK_SECRET` | Bắt buộc | Đã cấu hình; cần dùng cùng một secret tại Grafana contact point và AIOps |

Secret `techx-corp-grafana-discord`, key `webhook-url`, có thể dùng trực tiếp qua
Discord notification adapter.

`.env` và `.env.live` chỉ được `Settings` load trong test. Không có nội dung hoặc
giá trị Secret nào được hiển thị, ghi vào repository hoặc in ra terminal.

## 3. Các thay đổi đã thực hiện

- Bổ sung danh sách endpoint, authentication mode và secret source tại
  [live_endpoints.md](./live_endpoints.md).
- Bổ sung template port-forward không chứa secret tại
  [.env.live.example](../.env.live.example).
- Hỗ trợ load cấu hình mặc định từ `.env` và override bằng
  `AIOPS_ENV_FILE=.env.live` tại
  [settings.py](../aiops/config/settings.py).
- Sửa OpenSearch client để dùng HTTPS + Basic Auth; TLS verification chỉ được tắt
  cho tunnel `localhost` thông qua `AIOPS_OPENSEARCH_VERIFY_TLS=false`.
- Sửa Jaeger client để dùng đúng base path `/jaeger/ui`.
- Sửa HTTP/notification client để chấp nhận response thành công không có JSON,
  chẳng hạn HTTP `204 No Content`.
- Chuẩn hóa thông báo lỗi HTTP để không in request URL. Việc này ngăn Discord
  webhook token trong URL bị lộ khi receiver trả non-2xx hoặc không kết nối được.
- Bổ sung success/failure contract test riêng cho Prometheus, Grafana webhook,
  Jaeger, OpenSearch, Kubernetes, cost, notification và live executor.
- Cập nhật [smoke_test_live.py](../tests/smoke_test_live.py):

  - Dùng cùng integration client với runtime.
  - Không còn đường `SKIP` ngầm.
  - Missing config, HTTP `401`, non-2xx và endpoint không kết nối được đều là FAIL.
  - Kiểm tra Grafana health thật và AIOps inbound webhook riêng biệt.
  - Trả exit code khác `0` khi có bất kỳ test bắt buộc nào thất bại.

- Cập nhật [port_forward.ps1](../scripts/port_forward.ps1):

  - Kiểm tra `kubectl`, context, namespace và service trước khi mở tunnel.
  - Kiểm tra xung đột local port và chờ endpoint sẵn sàng.
  - Hiển thị đúng OpenSearch là HTTPS.
  - Chỉ dừng các background job do chính script tạo.

## 4. Kết quả kiểm tra live trên EKS

| Integration | Kết quả | Chi tiết |
|---|---:|---|
| Prometheus | **PASS 3/3** | Instant query có 23 series, range query có 28 series, 23 active targets |
| Jaeger | **PASS 2/2** | Có 21 services; truy vấn `frontend` trả về 1 trace |
| OpenSearch | **PASS 3/3** | Cluster `demo-cluster` phiên bản `3.2.0`, 7 indices; `otel-logs-*` tìm thấy 10.000 hits |
| Kubernetes API | **PASS 2/2** | 49/49 pod đang Running; Deployment `checkout` ready `2/2` |
| Grafana | **PASS 1/2** | Health PASS (`database=ok`, version `13.0.1`); inbound webhook bị connection refused vì chưa có AIOps listener tại `localhost:8000` |
| Notification | **PASS 1/1** | Receiver trả HTTP `204` |

Tổng kết live smoke suite: **12/13 PASS, 1/13 FAIL**. Kết quả được ghi từ lần chạy
do operator cung cấp ngày 2026-07-17; không có giá trị secret nào trong output.

## 5. Kết quả contract smoke cho integration client

Chạy bằng `.env` và `.env.live`; test không in nội dung hoặc giá trị secret từ hai
file này:

```powershell
python -B -m unittest tests.test_integrations tests.test_api_and_schemas -v
```

Kết quả ngày 2026-07-17 khi load `.env` và `.env.live`:

- Focused integration/API suite: **25/25 PASS**.
- Full unit suite: **52/52 PASS**.
- `git diff --check`: **PASS**.

| Integration | Success path | Failure path |
|---|---:|---:|
| Prometheus | PASS | PASS (`503`) |
| Grafana webhook | PASS | PASS (sai shared secret trả `401`) |
| Jaeger | PASS | PASS (`401`) |
| OpenSearch | PASS | PASS (`403`) |
| Kubernetes | PASS | PASS (`500`) |
| Cost | PASS | PASS (`503`) |
| Notification | PASS | PASS (`500`) |
| Live executor | PASS (mocked `dry-run`, không gửi action thật) | PASS (`409`) |

Test redaction riêng cũng PASS: HTTP error output chỉ giữ exception type/status,
không chứa request URL, Discord webhook token hoặc bearer token.

## 6. Cách chạy

Chạy các lệnh sau từ thư mục `src/aio`.

### 6.1. Chuẩn bị file live

Chỉ copy template nếu `.env.live` chưa tồn tại để tránh ghi đè cấu hình local:

```powershell
if (-not (Test-Path .env.live)) {
    Copy-Item .env.live.example .env.live
}
```

Điền credential được cấp vào `.env.live`. File này đã nằm trong `.gitignore` và
không được commit.

### 6.2. Mở tunnel tới EKS

```powershell
powershell -File scripts/port_forward.ps1
```

### 6.3. Chạy AIOps local cho Grafana inbound test

Trong terminal thứ hai:

```powershell
$env:AIOPS_ENV_FILE = ".env.live"
python -m uvicorn aiops.api.app:create_app --factory --port 8000
```

### 6.4. Chạy smoke test

Trong terminal thứ ba:

```powershell
# Chạy toàn bộ integration bắt buộc
python -B tests/smoke_test_live.py

# Hoặc chạy riêng từng nhóm
python -B tests/smoke_test_live.py TestPrometheus
python -B tests/smoke_test_live.py TestJaeger
python -B tests/smoke_test_live.py TestOpenSearch
python -B tests/smoke_test_live.py TestKubernetes
python -B tests/smoke_test_live.py TestGrafana
python -B tests/smoke_test_live.py TestNotification
```

## 7. Blocker còn lại

1. **Grafana inbound webhook local:** cần start AIOps process tại port `8000` để
   test thứ 13 kết nối được.
2. **Grafana webhook end-to-end:** cluster chưa có Deployment/Service AIOps.
   Grafana trong EKS không thể gọi `localhost:8000` trên máy developer.
3. **Cost/live executor live endpoint:** contract tests đã PASS, nhưng chưa có
   endpoint thật được cấp để chạy live. Không gửi action live chỉ để smoke test;
   việc đó cần approval và execution boundary riêng.

Để nghiệm thu Grafana webhook end-to-end, cần deploy AIOps thành ClusterIP Service
và cấu hình Grafana contact point trỏ tới endpoint tương tự:

```text
http://aiops:8000/api/v1/events/grafana
```
