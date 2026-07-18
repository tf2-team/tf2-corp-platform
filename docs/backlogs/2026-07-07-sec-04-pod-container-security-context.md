# Backlog: SEC-04 - Chuẩn hóa pod/container security context (Platform level - Custom Images)

## Bối cảnh
Để đáp ứng yêu cầu vận hành an toàn trên Kubernetes tuân thủ Restricted Pod Security Standards, toàn bộ các Dockerfile ứng dụng tự phát triển trong `techx-corp-platform/src` cần được thiết kế và đóng gói để chạy dưới dạng non-root user và tương thích với hệ thống tập tin chỉ đọc (read-only root filesystem).

## Vấn đề
Một số lượng lớn các custom images của dự án (`ad`, `cart`, `currency`, `email`, `llm`, `load-generator`, `product-reviews`, `recommendation`, và `flagd-ui`) chưa chỉ định tài khoản phi-root (`USER`) ở bước chạy runtime (release stage) hoặc chạy dưới quyền root mặc định. Ngoài ra, một số service có cơ chế tự động kết xuất/ghi đè file cấu hình động khi khởi chạy (ví dụ như `frontend-proxy` tạo file cấu hình Envoy và `image-provider` sinh cấu hình Nginx). Khi chạy với chính sách filesystem read-only, các dịch vụ này sẽ crash ngay lập tức do không thể ghi tệp cấu hình vào thư mục gốc.

## Giải pháp đề xuất
1. **Chuẩn hóa runtime user trong Dockerfiles:**
   - Chỉnh sửa Dockerfile của 9 service chưa chuẩn hóa để tạo group và user phi-root với UID/GID cố định `10001:10001` (dùng cho các app-owned images).
   - Thực hiện `chown` chuyển quyền sở hữu toàn bộ mã nguồn ứng dụng và thư mục chạy runtime (`WORKDIR`) cho user phi-root trước khi khai báo chỉ lệnh `USER 10001`.
2. **Bảo toàn các UID đặc thù đã biết:**
   - Giữ nguyên thiết kế UID của các ứng dụng bên thứ ba hoặc distroless: `frontend-proxy` và `image-provider` (UID 101), `quote` (UID 33), các distroless images (UID `65532` hoặc `nonroot`).
3. **Cấu hình đường dẫn ghi cấu hình động:**
   - Cập nhật lệnh `ENTRYPOINT` của `frontend-proxy` để lưu config được render qua `envsubst` vào `/tmp/envoy.yaml` thay vì WORKDIR.
   - Cập nhật `CMD` của `image-provider` để ghi file config render vào `/tmp/nginx.conf` và chạy nginx với cờ `-c /tmp/nginx.conf`.
   - Sửa tệp cấu hình Nginx mẫu `nginx.conf.template` để đổi `include mime.types;` thành `include /etc/nginx/mime.types;` (sử dụng đường dẫn tuyệt đối) tránh việc Nginx tìm kiếm file mime tương đối tại thư mục cấu hình `/tmp`.
4. **Kiểm tra quyền truy cập thư mục tạm:**
   - Đảm bảo các runtime Node/Python/Ruby/Java được cấp quyền ghi đầy đủ vào thư mục `/tmp` thông qua cấu hình volume gắn ngoài từ Helm.

## Acceptance Criteria
- Mọi custom Dockerfile của ứng dụng tự phát triển đều chứa chỉ thị `USER <non-root-uid>` ở stage runtime cuối cùng.
- Các ứng dụng tự sinh file cấu hình lúc startup (`frontend-proxy`, `image-provider`) thực hiện ghi và đọc file từ thư mục tạm `/tmp` thành công.
- Các custom image được phân quyền đầy đủ đối với thư mục runtime mà không cần dùng tài khoản đặc quyền.
- Quá trình chạy thử ứng dụng (smoke test) cho luồng storefront, checkout, và giám sát telemetry hoạt động bình thường mà không phát sinh lỗi phân quyền ghi tập tin.

## Kiểm thử / xác minh
1. Thực hiện build thử các docker image cục bộ:
   ```sh
   # Ví dụ build và chạy thử dưới nonroot user
   docker build -t techx-corp-ad:test -f src/ad/Dockerfile .
   docker run --rm --user 10001 techx-corp-ad:test
   ```
2. Kiểm tra xem ứng dụng có cố gắng ghi dữ liệu vào các đường dẫn ngoài `/tmp` hay không bằng cách chạy thử container với cờ `--read-only`.

## Rủi ro & rollback
- **Rủi ro**: Việc thay đổi UID và cấu hình read-only có thể làm hỏng cơ chế ghi cache của một số thư viện ngôn ngữ hoặc framework (ví dụ: cache bytecode của Python, cache gem của Ruby) dẫn đến suy giảm hiệu năng hoặc crash.
- **Rollback**: Sửa lại Dockerfile để loại bỏ lệnh `USER 10001`, build lại các image và triển khai phiên bản cũ để khôi phục dịch vụ.

---

## English Summary
This backlog manages the image and runtime compatibility updates within the `techx-corp-platform` repository. It covers updating the Dockerfiles of 9 custom services (`ad`, `cart`, `currency`, `email`, `llm`, `load-generator`, `product-reviews`, `recommendation`, and `flagd-ui`) to run under non-root user `10001:10001`, applying proper ownership `chown` to runtime directories, adapting configuration generation behavior at startup for `frontend-proxy` and `image-provider` to write config into `/tmp`, and ensuring compatibility with a read-only root filesystem.
