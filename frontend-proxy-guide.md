# PHÂN TÍCH KIẾN TRÚC: VAI TRÒ CỦA FRONTEND-PROXY (API GATEWAY)

*(Tài liệu chia sẻ nội bộ cho thành viên Task Force)*

Trong kiến trúc Microservices của TechX Corp, **`frontend-proxy`** đóng vai trò là **API Gateway** hay **Reverse Proxy (Proxy ngược)** sử dụng công nghệ **Envoy Proxy**.

## 4. Cơ chế DNS nội bộ khi triển khai tách biệt (Cross-Namespace)

Khi chúng ta tách biệt môi trường (Dịch vụ giám sát nằm ở namespace `techx-observability`, ứng dụng chính nằm ở namespace `techx-tf2`):

* Để `frontend-proxy` (chạy ở `techx-tf2`) có thể chuyển tiếp request `/grafana/` và `/jaeger/` sang namespace giám sát, nó phải dùng đường dẫn DNS đầy đủ dạng FQDN (Fully Qualified Domain Name) của Kubernetes:
  * Trỏ Grafana: `grafana.techx-observability.svc.cluster.local`
  * Trỏ Jaeger: `jaeger.techx-observability.svc.cluster.local`
* Cơ chế này giúp các dịch vụ ở các Namespace khác nhau vẫn có thể kết nối với nhau một cách an toàn và tường minh.

---

## 5. Cấu Hình Ghi Đè Thực Tế & Danh Sách URL Truy Cập

Phương án định tuyến chéo namespace (cross-namespace routing) đã được áp dụng trực tiếp vào cấu hình deploy:

* **File cấu hình:** **phase3/deploy/values-app-stamp.yaml**
* **Khối cấu hình bổ sung:**

  ```yaml
  components:
    frontend-proxy:
      envOverrides:
        - name: GRAFANA_HOST
          value: grafana.techx-observability.svc.cluster.local
        - name: JAEGER_HOST
          value: jaeger.techx-observability.svc.cluster.local
  ```

### 🚀 Cách truy cập tập trung qua 1 Port (Cổng 8080)

Khi bạn chạy lệnh port-forward cho cổng Gateway duy nhất của ứng dụng:

```bash
kubectl -n techx-tf2 port-forward svc/frontend-proxy 8080:8080
```

Bạn có thể truy cập toàn bộ các dịch vụ (cả ứng dụng chính lẫn giám sát) thông qua các URL sau trên trình duyệt Web:

1. **Trang bán hàng (Storefront):**
   👉 `http://localhost:8080/`
2. **Hệ thống giám sát chỉ số (Grafana):**
   👉 `http://localhost:8080/grafana/`
3. **Theo dõi luồng yêu cầu (Jaeger Tracing UI):**
   👉 `http://localhost:8080/jaeger/ui/` (hoặc `http://localhost:8080/jaeger/`)
4. **Trang quản lý sinh tải kiểm thử (Locust Loadgen):**
   👉 `http://localhost:8080/loadgen/`
5. **Giao diện console quản lý Feature Flag (Flagd-UI):**
   👉 `http://localhost:8080/feature/`
6. **API cung cấp ảnh sản phẩm (Image Provider):**
   👉 `http://localhost:8080/images/`
7. **Cổng kiểm tra API của Feature Flag (Flagd API):**
   👉 `http://localhost:8080/flagservice/`
8. **Cổng thu nhận metrics qua HTTP (Collector OTLP):**
   👉 `http://localhost:8080/otlp-http/`

---

## 6. Public ALB Ingress (Production Environment)

To expose the storefront publicly on EKS, an opt-in public ALB-backed Ingress can be deployed. This routes public traffic to `frontend-proxy` while securing internal administrative and telemetry interfaces at the platform level.

### 🛡️ Public vs. Blocked Surfaces

When the public ALB is active, the following access control routing rules are enforced:

* **Public Surface (ALLOWED - Returns 200 OK)**:
  * `http://<ALB_DNS_NAME>/` (Storefront main page)
  * `http://<ALB_DNS_NAME>/api/*` (API backend services)
  * `http://<ALB_DNS_NAME>/images/*` (Product images)

* **Blocked Surfaces (FORBIDDEN - Returns 403 Access Denied)**:
  * `/grafana` (Grafana Dashboards)
  * `/jaeger` (Jaeger Tracing UI)
  * `/loadgen/` (Locust Load Generator UI)
  * `/feature` (Flagd feature flag UI)
  * `/flagservice/` (Flagd API gateway)
  * `/otlp-http/` (OpenTelemetry Collector ingestion endpoint)

---

### 🔍 Verification / Smoke-Test Commands

After deploying or updating the Helm chart with the public ALB enabled, operators should execute the following smoke-tests to ensure proper routing and access controls are in place.

1. **Verify the Ingress resource and fetch the ALB Hostname**:
   ```bash
   kubectl -n techx-tf2 get ingress frontend-proxy-public
   ```
   *(Note: AWS Load Balancer creation and DNS registration may take 2-5 minutes.)*

2. **Verify public storefront access**:
   * Access the home page (expect `200 OK`):
     ```bash
     curl -i http://<ALB_DNS_NAME>/
     ```
   * Access a static asset/image (expect `200 OK`):
     ```bash
     curl -i http://<ALB_DNS_NAME>/images/logo.png
     ```

3. **Verify blocked endpoints are rejected with `403 Forbidden`**:
   * Test Grafana (expect `403 Forbidden`):
     ```bash
     curl -i http://<ALB_DNS_NAME>/grafana/
     ```
   * Test Jaeger UI (expect `403 Forbidden`):
     ```bash
     curl -i http://<ALB_DNS_NAME>/jaeger/
     ```
   * Test Load Generator (expect `403 Forbidden`):
     ```bash
     curl -i http://<ALB_DNS_NAME>/loadgen/
     ```

---

### ⚠️ Security Warning & Hardening Roadmap

> [!WARNING]
> **HTTP-Only Access is Temporary**: The current public ALB is configured for HTTP (Port 80) access only. This HTTP-first setup is intended strictly for initial deployment validation and integration smoke-testing.
> 
> **Production Hardening Next Step**: Before deploying to production, you must implement HTTPS and integrate an AWS Certificate Manager (ACM) SSL/TLS certificate. Running an unencrypted HTTP endpoint exposes raw storefront and API transmission to Man-in-the-Middle (MitM) attacks.
