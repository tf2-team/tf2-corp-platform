# Backlog: Public ALB Ingress cho frontend-proxy

## Bối cảnh
Với sự ra đời của tính năng public ALB Ingress cho `frontend-proxy`, storefront của TechX Corp sẽ được expose công khai ra Internet. Hệ thống Envoy proxy trong repository `techx-corp-platform` đóng vai trò là API Gateway nội bộ, do đó cần được rà soát kỹ lưỡng về mặt định tuyến và hướng dẫn vận hành để đảm bảo an toàn thông tin khi public.

## Vấn đề
Hiện tại, Envoy định cấu hình rất nhiều đường dẫn nội bộ phục vụ cho phát triển cục bộ và debug (như `/grafana`, `/jaeger`, `/loadgen`, v.v.). Khi tiến hành expose hệ thống qua ALB công cộng, chúng ta phải xác định rõ phạm vi bảo vệ của ứng dụng ở mức platform. Chúng ta cần cập nhật tài liệu vận hành và cung cấp quy trình kiểm thử khói (smoke-test) để đảm bảo không có rò rỉ thông tin nhạy cảm.

## Giải pháp đề xuất
Thực hiện các công việc sau trong repo `techx-corp-platform`:
1. Rà soát danh sách định tuyến trên Envoy proxy và xác định rõ "Public Surface" cần thiết cho storefront (chỉ bao gồm `/`, `/api/*`, và `/images/*`).
2. Cập nhật tài liệu hướng dẫn vận hành của frontend-proxy (`frontend-proxy-guide.md` hoặc tài liệu tương đương) để bổ sung hướng dẫn triển khai ALB Ingress công cộng.
3. Tài liệu hóa hướng dẫn chuyển đổi từ môi trường phát triển cục bộ (sử dụng port-forward) sang môi trường production chạy trên ALB công cộng.
4. Thêm checklist kiểm thử khói (smoke-test checklist) phục vụ cho vận hành viên kiểm tra sau khi deploy.
5. Ghi chú rõ ràng trong tài liệu rằng cấu hình HTTP hiện tại (HTTP-first) chỉ mang tính chất thử nghiệm/tạm thời, bước tiếp theo bắt buộc phải triển khai cấu hình HTTPS và tích hợp chứng chỉ ACM (AWS Certificate Manager).

## Acceptance Criteria
- Cập nhật hướng dẫn vận hành mô tả rõ cách thức hoạt động của public ALB Ingress và các điều kiện tiên quyết.
- Storefront hoạt động bình thường qua DNS của ALB (hiển thị trang chủ, tải ảnh từ `/images/*` và lấy dữ liệu API từ `/api/*`).
- Các đường dẫn nội bộ và quản trị bị chặn hoàn toàn và trả về mã lỗi `403 Forbidden` khi truy cập qua ALB DNS.
- Tài liệu vận hành ghi nhận rõ ràng lộ trình nâng cấp lên HTTPS/ACM trong tương lai gần để đảm bảo an toàn dữ liệu truyền trên mạng internet công cộng.

## Kiểm thử / xác minh
1. Xác minh tài liệu hướng dẫn vận hành đã được cập nhật đầy đủ thông tin về ALB Ingress.
2. Kiểm tra khói (Smoke-test) sau khi deploy bằng cách gửi yêu cầu trực tiếp qua DNS của ALB:
   - Truy cập trang chủ storefront: `curl -i http://<ALB_DNS_NAME>/` (kết quả mong đợi: `200 OK`).
   - Truy cập ảnh logo: `curl -i http://<ALB_DNS_NAME>/images/logo.png` (kết quả mong đợi: `200 OK`).
   - Truy cập Grafana: `curl -i http://<ALB_DNS_NAME>/grafana` (kết quả mong đợi: `403 Forbidden`).
   - Truy cập Jaeger UI: `curl -i http://<ALB_DNS_NAME>/jaeger` (kết quả mong đợi: `403 Forbidden`).

## Rủi ro & rollback
- **Rủi ro**: Lộ lọt thông tin nhạy cảm nếu cấu hình Envoy proxy hoặc ALB Ingress bỏ sót các route nội bộ quan trọng. Lỗi HTTP không mã hóa dữ liệu truyền tải làm tăng nguy cơ tấn công Man-in-the-Middle.
- **Rollback**: Gỡ bỏ Ingress công cộng và chuyển hướng người dùng quay lại sử dụng các kênh truy cập nội bộ (VPN/port-forward) cho đến khi sự cố được khắc phục hoặc chứng chỉ SSL được cài đặt.

---

## English Summary
This backlog tracks the route exposure review, deployment guide updates, and operational documentation in the `techx-corp-platform` repository following the public ALB configuration. It defines the public surface to only allow `/`, `/api/*`, and `/images/*`, provides a smoke-test checklist, and documents that HTTP-first is temporary, with HTTPS/ACM integration planned as the next step.
