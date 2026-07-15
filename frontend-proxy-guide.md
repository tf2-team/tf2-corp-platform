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

## 6. Storefront edge (CloudFront + internal ALB)

Production storefront traffic does **not** use an internet-facing ALB. Path:

```
Browser (HTTPS) → CloudFront → VPC origin → Internal ALB (scheme=internal) → frontend-proxy
```

* Chart overlay: `values-public-alb.yaml` (`scheme: internal`, `blockSensitivePaths: false`).
* Public HTTPS + sensitive-path **403**s: CloudFront Function (`techx-corp-infra` `docs/cloudfront.md`).
* Internal ALB forwards **all** paths to Envoy (including admin routes).

### Public vs admin surfaces

| Path | CloudFront (public) | Internal ALB (private / Client VPN) |
|---|---|---|
| `/`, `/api/*`, `/images/*` | Allowed | Allowed |
| `/grafana`, `/jaeger`, `/loadgen`, `/feature`, `/flagservice`, `/otlp-http` | **403** when edge blocking on | **Open** (app auth still applies) |

### Operator admin access (Client VPN)

Do **not** turn off CloudFront path blocking for day-to-day Grafana/Jaeger access. Connect **AWS Client VPN**, then use the **internal ALB** hostname:

* Runbook: `techx-corp-infra/docs/client-vpn.md`
* Example: `http://<INTERNAL_ALB_DNS>/grafana/` after VPN connect

Port-forward (section 5) remains valid for cluster-side debugging without VPN.

---

### Verification / smoke-test commands

1. **Ingress / internal ALB hostname**:
   ```cmd
   kubectl -n techx-corp get ingress frontend-proxy-public
   ```

2. **Public storefront via CloudFront** (expect `200` on `/` and `/images/*`):
   ```cmd
   curl -i https://<cloudfront-alias>/
   curl -i https://<cloudfront-alias>/images/logo.png
   ```

3. **Admin blocked at edge** (expect `403`):
   ```cmd
   curl -i https://<cloudfront-alias>/grafana/
   curl -i https://<cloudfront-alias>/jaeger/
   curl -i https://<cloudfront-alias>/loadgen/
   ```

4. **Admin via Client VPN + internal ALB** (expect not edge 403):
   ```cmd
   curl -i http://<INTERNAL_ALB_DNS>/grafana/
   ```

---

### Security notes

* Public edge HTTPS is terminated at **CloudFront** (ACM in `us-east-1`). The internal ALB listens HTTP:80 for VPC origin and private clients.
* Grafana/Jaeger credentials remain separate (ESO/Secrets Manager); Client VPN is network access only.
