# Backlog: REL-08 - Thiết kế rollback và rollout safety chuẩn hơn

## Bối cảnh
Khi nâng cấp hoặc vá lỗi cho các dịch vụ ứng dụng TechX Corp, hạ tầng Kubernetes chỉ kiểm tra tính sẵn sàng ở mức mạng/tiến trình (liveness/readiness probes). Để đảm bảo ứng dụng thực sự hoạt động bình thường về mặt nghiệp vụ sau khi deploy, chúng ta cần một kịch bản kiểm thử nhanh (smoke test) tự động để xác nhận các luồng nghiệp vụ cốt lõi từ Storefront.

## Vấn đề
- Hệ thống hiện tại thiếu cơ chế smoke test tự động để xác thực tính toàn vẹn của ứng dụng từ góc nhìn người dùng (end-to-end flow).
- Nếu luồng tích hợp giữa `frontend` và các dịch vụ gRPC phía sau (như `checkout`, `cart`, `payment`) bị hỏng nhưng tiến trình của chúng vẫn chạy bình thường, Kubernetes vẫn đánh dấu Pod là sẵn sàng (Ready), dẫn đến việc deploy phiên bản lỗi nghiệp vụ nghiêm trọng ra production.
- Khi bật Public ALB Ingress cho `frontend-proxy`, chưa có công cụ kiểm tra tự động xem các quy tắc chặn đường dẫn quản trị nhạy cảm đã hoạt động chính xác hay chưa.

## Giải pháp đề xuất
1. **Xây dựng kịch bản Smoke Test tự động**: Viết một file shell script `smoke-test.sh` đặt tại thư mục `scripts/` trong chart để chạy kiểm tra ngay sau khi deploy.
2. **Xác lập luồng kiểm thử nghiệp vụ cốt lõi**:
   - **Homepage Check**: Gửi request `GET /` đến storefront để đảm bảo trang chủ trả về HTTP 200.
   - **Product Catalog Check**: Gửi request `GET /api/products` để đảm bảo API danh mục sản phẩm hoạt động bình thường, đồng thời trích xuất động một `productId` có sẵn.
   - **Add to Cart Flow**: Giả lập việc thêm sản phẩm vào giỏ hàng bằng cách gửi request `POST /api/cart` với payload định dạng:
     ```json
     {
       "userId": "smoke-test-user-id",
       "item": {
         "productId": "PRODUCT_ID_THUC_TE",
         "quantity": 2
       }
     }
     ```
   - **Checkout Flow**: Giả lập quy trình thanh toán bằng cách gửi request `POST /api/checkout` sử dụng thông tin người dùng và thẻ tín dụng mẫu:
     ```json
     {
       "userId": "smoke-test-user-id",
       "email": "smoke-test@example.com",
       "address": {
         "streetAddress": "1600 Amphitheatre Parkway",
         "city": "Mountain View",
         "state": "CA",
         "country": "United States",
         "zipCode": "94043"
       },
       "userCurrency": "USD",
       "creditCard": {
         "creditCardNumber": "4432-8015-6152-0454",
         "creditCardCvv": 672,
         "creditCardExpirationYear": 2030,
         "creditCardExpirationMonth": 1
       }
     }
     ```
3. **Kiểm tra route chặn của Public ALB**: Nếu script được gọi với tham số `--alb-host`, script sẽ gửi yêu cầu thử tới các đường dẫn nhạy cảm (`/grafana`, `/jaeger`, `/loadgen`, `/feature`, `/flagservice`, `/otlp-http`) và đảm bảo toàn bộ đều trả về mã lỗi HTTP 403 Forbidden.

## Acceptance Criteria
- Kịch bản smoke test chạy độc lập bằng Bash trên môi trường CI/CD hoặc máy của vận hành viên.
- Nếu chỉ cung cấp tham số `--namespace`, script sẽ tự động tạo kết nối cổng tạm thời (`kubectl port-forward`) tới `frontend-proxy` để kiểm thử từ xa, sau đó tự dọn dẹp tiến trình.
- Quy trình smoke test phải đi qua toàn bộ 4 bước: trang chủ, danh sách sản phẩm, thêm giỏ hàng, và đặt hàng thành công (trả về mã HTTP 200 và có chứa `orderId` hợp lệ).
- Khi chạy với `--alb-host`, script phải kiểm tra và xác nhận hành vi chặn truy cập các path nhạy cảm trả về HTTP 403.

## Kiểm thử / xác minh
1. Triển khai chart lên namespace chỉ định (ví dụ: `techx-corp`).
2. Chạy kịch bản smoke test:
   ```sh
   bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp
   ```
3. Chạy kiểm tra Public ALB (nếu có):
   ```sh
   bash techx-corp-chart/scripts/smoke-test.sh --alb-host <DNS-CUA-ALB>
   ```

## Rủi ro & rollback
- **Rủi ro**: Tạo ra các đơn hàng giả lập (order rác) trong cơ sở dữ liệu telemetry/accounting. Để giảm thiểu, script sẽ sử dụng ID người dùng có tiền tố là `smoke-test-user-`.
- **Rollback**: Dừng chạy hoặc vô hiệu hóa bước kiểm tra smoke test trong pipeline CI/CD nếu script gặp lỗi logic không mong muốn.

---

## English Summary
This backlog item tracks the application smoke-test and health behavior implementation for the REL-08 task in the `techx-corp-platform` repository. It outlines the test suite requirements for storefront homepage validation, product listing extraction, adding items to the cart, completing the checkout flow via `/api/checkout` using standard JSON request payloads, and verifying route-blocking mechanisms (HTTP 403) on public ALBs.
