# Ghi chú môi trường kiểm thử AIOps

> Cập nhật: 2026-07-16  
> Môi trường: AWS EKS, namespace `techx-corp-prod`  
> Phương thức kết nối: `kubectl port-forward` và `kubectl proxy`

## 1. Tổng quan

Các integration có thể kiểm tra khi chưa có credential thật đã được chuẩn hóa để
kết nối tới workload đang chạy trên EKS. Smoke test hiện chạy ở chế độ strict:
không còn trường hợp endpoint bị bỏ qua nhưng toàn bộ suite vẫn trả kết quả thành
công.

Prometheus, Jaeger, Kubernetes API và Grafana health không cần credential dịch vụ
riêng khi kết nối qua port-forward hoặc Kubernetes proxy. OpenSearch đã có Basic Auth
hợp lệ và vượt qua toàn bộ smoke test. Grafana inbound webhook và notification vẫn
thiếu cấu hình bắt buộc.

## 2. Trạng thái credential và secret

| Biến/thông tin | Mức độ | Trạng thái và nguồn |
|---|---|---|
| `AIOPS_OPENSEARCH_PASSWORD` | Bắt buộc | Đã cấu hình; smoke test xác nhận Basic Auth hợp lệ. Không ghi giá trị vào tài liệu |
| `AIOPS_OPENSEARCH_USERNAME` | Bắt buộc | Đã cấu hình; smoke test xác nhận Basic Auth hợp lệ. Không ghi giá trị vào tài liệu |
| `AIOPS_NOTIFICATION_WEBHOOK_URL` | Bắt buộc | Còn placeholder; cần JSON webhook receiver tương thích với `NotificationMessage` |
| `AIOPS_NOTIFICATION_TOKEN` | Tùy chọn | Chỉ cần khi notification receiver yêu cầu Bearer Auth |
| Grafana admin credential | Có điều kiện | Chỉ cần khi provision contact point bằng Grafana API; nguồn: Secret `techx-corp-grafana-admin` |
| `AIOPS_GRAFANA_WEBHOOK_SECRET` | Bắt buộc | Chưa cấu hình; cần dùng cùng một secret tại Grafana contact point và AIOps |

Secret `techx-corp-grafana-discord`, key `webhook-url`, chỉ là candidate cho
notification. Discord yêu cầu payload riêng nên không dùng trực tiếp với normalized
`NotificationMessage` nếu chưa có adapter.

Không có giá trị Secret nào được đọc, ghi vào repository hoặc in ra terminal trong
quá trình kiểm tra.

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
| Prometheus | **PASS 3/3** | Instant query có 28 series, range query có 65 series, 23 active targets |
| Jaeger | **PASS 2/2** | Có 19 services; truy vấn `frontend` trả về 1 trace |
| OpenSearch | **PASS 3/3** | Cluster `demo-cluster` phiên bản `3.2.0`, 6 indices; `otel-logs-*` tìm thấy 10.000 hits |
| Kubernetes API | **PASS 2/2** | 49/49 pod đang Running; Deployment `checkout` ready `2/2` |
| Grafana | **PASS 1/2** | Health PASS (`database=ok`, version `13.0.1`); inbound webhook FAIL vì thiếu `AIOPS_GRAFANA_WEBHOOK_SECRET` |
| Notification | **FAIL 0/1** | Thiếu `AIOPS_NOTIFICATION_WEBHOOK_URL`; request chưa được gửi |

Tổng kết live smoke suite: **11/13 PASS, 2/13 FAIL**. Hai lỗi đều xảy ra ở bước
kiểm tra cấu hình trước khi gửi request, không phải lỗi kết nối hoặc HTTP response.

Các unit test bị tác động đều thành công:

- Integration client: **5/5 PASS**
- Settings: **3/3 PASS**
- API/schema: **4/4 PASS**
- PowerShell syntax và `git diff --check`: **PASS**

Full unit suite hiện đạt **34/36**. Hai test RCA còn lại không chạy được vì Python
environment hiện tại chưa cài package `baro` từ dependency `fse-baro`; đây không
phải regression từ thay đổi integration.

## 5. Cách chạy

Chạy các lệnh sau từ thư mục `src/aio`.

### 5.1. Chuẩn bị file live

Chỉ copy template nếu `.env.live` chưa tồn tại để tránh ghi đè cấu hình local:

```powershell
if (-not (Test-Path .env.live)) {
    Copy-Item .env.live.example .env.live
}
```

Điền credential được cấp vào `.env.live`. File này đã nằm trong `.gitignore` và
không được commit.

### 5.2. Mở tunnel tới EKS

```powershell
powershell -File scripts/port_forward.ps1
```

### 5.3. Chạy AIOps local cho Grafana inbound test

Trong terminal thứ hai:

```powershell
$env:AIOPS_ENV_FILE = ".env.live"
python -m uvicorn aiops.api.app:create_app --factory --port 8000
```

### 5.4. Chạy smoke test

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

## 6. Blocker còn lại

1. **Notification receiver:** cần một JSON webhook URL tương thích và token nếu
   receiver yêu cầu.
2. **Grafana inbound webhook:** cần cấu hình `AIOPS_GRAFANA_WEBHOOK_SECRET` ở AIOps
   và cùng giá trị tại Grafana contact point.
3. **Grafana webhook end-to-end:** cluster chưa có Deployment/Service AIOps.
   Grafana trong EKS không thể gọi `localhost:8000` trên máy developer.
4. **RCA unit test environment:** cần cài dependency `fse-baro` để chạy đủ 36 test.

Để nghiệm thu Grafana webhook end-to-end, cần deploy AIOps thành ClusterIP Service
và cấu hình Grafana contact point trỏ tới endpoint tương tự:

```text
http://aiops:8000/api/v1/events/grafana
```
