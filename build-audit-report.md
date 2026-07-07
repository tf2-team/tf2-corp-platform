# BÁO CÁO AUDIT: CÁC LỖI HỆ THỐNG & GIẢI PHÁP KHẮC PHỤC KHI DỰNG BASELINE

*(Tài liệu chia sẻ nội bộ cho thành viên Task Force)*

Tài liệu này tổng hợp lại toàn bộ các lỗi phát sinh do thiếu tệp tin hoặc sai sót cấu hình trong bộ mã nguồn mẫu của Ban tổ chức khi tiến hành build và push 18 Docker Images lên ECR.

---

## 1. Lỗi Đường Dẫn Build Script (`build-push-images.sh`)

* **Mô tả lỗi:**
  Đường dẫn tương đối trỏ tới thư mục mã nguồn ứng dụng bị sai sau khi cấu trúc lại thư mục dự án (tách thành các repo riêng biệt).
* **Triệu chứng:**
  Không tìm thấy tệp `.env.override` khi bắt đầu chạy build.
* **Tệp ảnh hưởng:**
  `phase3/deploy/build-push-images.sh` (Dòng số 7).
* **Giải pháp đã thực hiện:**
  Sửa đường dẫn di chuyển thư mục từ `../techx-corp-platform` thành `../../techx-corp-platform` để trỏ đúng ra thư mục cha bên ngoài:

  ```bash
  # Trước: cd "$HERE/../techx-corp-platform"
  # Sau:  cd "$HERE/../../techx-corp-platform"
  ```

---

## 2. Lỗi Thiếu Tag ECR Cho Service OpenSearch

* **Mô tả lỗi:**
  Dịch vụ OpenSearch trong file cấu hình Docker Compose được thiết lập tự động build cục bộ (`build:`), nhưng lại thiếu thuộc tính định danh ảnh (`image:`).
* **Triệu chứng:**
  Khi đẩy ảnh lên ECR bằng Buildx, hệ thống báo lỗi:

  ```text
  ERROR: tag is needed when pushing to registry
  make: *** [build-multiplatform-and-push] Error 1
  ```

* **Tệp ảnh hưởng:**
  `techx-corp-platform/docker-compose.yml` (Dòng số 922).
* **Giải pháp đã thực hiện:**
  Bổ sung thuộc tính `image` cho `opensearch` theo đúng định dạng chung:

  ```yaml
    # OpenSearch
    opensearch:
  +   image: ${IMAGE_NAME}:${DEMO_VERSION}-opensearch
      container_name: opensearch
      build: ...
  ```

---

## 3. Lỗi Thiếu Tệp gRPC Health Check Của Service Currency

* **Mô tả lỗi:**
  Thư mục `/src/currency/proto` bị đưa vào danh mục bỏ qua của `.gitignore` (`/src/currency/proto` tại dòng 49). Điều này khiến tệp định nghĩa gRPC Health check của dịch vụ C++ không được tải lên GitHub.
* **Triệu chứng:**
  Khi chạy build, Docker báo lỗi không tìm thấy thư mục để copy:

  ```text
  ERROR: target currency: failed to solve: failed to compute cache key: failed to calculate checksum... "/src/currency/proto": not found
  ```

* **Tệp ảnh hưởng:**
  `techx-corp-platform/src/currency/Dockerfile` (Dòng số 40).
* **Giải pháp đã thực hiện:**
  Tạo lại thư mục và tệp tin định nghĩa gRPC Healthcheck chuẩn tại đường dẫn:
  `techx-corp-platform/src/currency/proto/grpc/health/v1/health.proto`.

---

## 4. Lỗi Thiếu Thư Mục `rel` Của Service Flagd-UI (Elixir Release)

* **Mô tả lỗi:**
  Tương tự lỗi của `currency`, thư mục `/src/flagd-ui/rel` (chứa các script khởi chạy Phoenix release trong môi trường Production) bị thiếu trong mã nguồn Git nhưng Dockerfile lại cố sao chép chúng.
* **Triệu chứng:**

  ```text
  ERROR: target flagd-ui: failed to solve: ... "/src/flagd-ui/rel": not found
  ```

* **Tệp ảnh hưởng:**
  `techx-corp-platform/src/flagd-ui/Dockerfile` (Dòng số 66).
* **Giải pháp đã thực hiện:**
  Tạo lại cấu trúc thư mục và sinh các tệp script khởi chạy chuẩn cho Phoenix release tại:
  * `techx-corp-platform/src/flagd-ui/rel/overlays/bin/server`
  * `techx-corp-platform/src/flagd-ui/rel/overlays/bin/server.bat`
  * Cấp quyền thực thi (`chmod +x`) cho script.

---

## 5. Lỗi Nghẽn Mạng Tải Thư Viện (TLS Handshake Timeout)

* **Mô tả lỗi:**
  Trong quá trình tải thư viện bên thứ ba của ngôn ngữ Go (ví dụ: `open-feature/flagd`), mạng kết nối từ container ra máy chủ thư viện quốc tế bị nghẽn làm quá trình tải qua Docker bị quá hạn (timeout).
* **Triệu chứng:**

  ```text
  Get "https://proxy.golang.org/...": net/http: TLS handshake timeout
  ERROR: target product-catalog: failed to solve: process "/bin/sh -c go mod download" did not complete successfully
  ```

* **Giải pháp:**
  * **Giải pháp ngắn hạn:** Chạy lại script build để thử lại kết nối mạng.
  * **Giải pháp dài hạn (Nếu bị lỗi liên tục):** Cấu hình thêm Proxy ở khu vực Châu Á bằng cách thêm dòng `ENV GOPROXY=https://goproxy.io,direct` vào Dockerfile của các service chạy Go để tăng tốc độ tải.

---

## 6. Lỗi Không Tương Thích Giữa Erlang/OTP 28.0 (UndefinedFunctionError) và Lỗi SSL/TLS (key_usage_mismatch) Trên Erlang 27+

* **Mô tả lỗi:**
  * **Lỗi 1 (OTP 28.0):** Erlang 28.0 lược bỏ hàm `:re.import/1` làm crash trình quản lý gói Hex của Elixir khi chạy lệnh cài đặt thư viện (`mix deps.get`).
  * **Lỗi 2 (OTP 27.2):** Khi hạ xuống Erlang 27+, bộ máy SSL/TLS của Erlang áp dụng tiêu chuẩn RFC 5280 quá nghiêm ngặt để xác thực chứng chỉ HTTPS. Khi kết nối tới `builds.hex.pm` qua một số mạng/CDN hoặc proxy, Erlang 27+ lập tức từ chối và báo lỗi khớp khóa chứng chỉ (`key_usage_mismatch`).
* **Triệu chứng:**
  * Với OTP 28: `** (UndefinedFunctionError) function :re.import/1 is undefined`
  * Với OTP 27: `{:tls_alert, {:unsupported_certificate, ... key_usage_mismatch}}`
* **Tệp ảnh hưởng:**
  `techx-corp-platform/src/flagd-ui/Dockerfile` (Dòng số 18).
* **Giải pháp đã thực hiện:**
  Hạ phiên bản Erlang/OTP hẳn xuống phiên bản **`26.2.5`** cực kỳ ổn định. Đây là phiên bản Erlang 26 cuối cùng, vẫn tương thích tốt với Elixir 1.19.3 nhưng không bị lỗi `:re.import/1` và không áp đặt bộ lọc TLS nghiêm ngặt gây lỗi `key_usage_mismatch`:

  ```dockerfile
  # Trước: ARG OTP_VERSION=28.0.2 (hoặc 27.2)
  # Sau:  ARG OTP_VERSION=26.2.5
  ```

---

## 7. Lỗi Thiếu `assets/vendor` Của Service Flagd-UI Khi Compile Phoenix Assets

* **Mô tả lỗi:**
  Dự án Flagd-UI sử dụng Phoenix 1.8 với Tailwind CSS 4. File `assets/css/app.css` tham chiếu các plugin trong `assets/vendor`, và `assets/js/app.js` import `../vendor/topbar`, nhưng thư mục vendor bị thiếu khỏi mã nguồn mẫu.
* **Triệu chứng:**

  ```text
  Error: Can't resolve '../vendor/heroicons' in '/app/assets/css'
  ** (Mix) `mix tailwind flagd_ui --minify` exited with 1
  ```

  Sau khi thêm riêng `heroicons`, Tailwind tiếp tục báo:

  ```text
  Error: The plugin "../vendor/daisyui" does not accept options
  ** (Mix) `mix tailwind flagd_ui --minify` exited with 1
  ```

  Nguyên nhân phụ là `app.css` gọi plugin theo cú pháp có block options:

  ```css
  @plugin "../vendor/daisyui" {
    themes: false;
  }
  ```

  Vì vậy plugin local phải dùng API `plugin.withOptions(...)` của Tailwind. Nếu chỉ export function thường thì Tailwind không chấp nhận block options.
* **Tệp ảnh hưởng:**
  * `techx-corp-platform/src/flagd-ui/assets/css/app.css`
  * `techx-corp-platform/src/flagd-ui/assets/js/app.js`
  * `techx-corp-platform/src/flagd-ui/assets/vendor/*`
  * `techx-corp-platform/.gitignore`
  * `phase3/deploy/build-push-images.sh`
* **Giải pháp đã thực hiện:**
  Khôi phục các vendor module cần thiết:
  * `assets/vendor/heroicons.js`: tạo class `hero-*` bằng cách đọc SVG từ `deps/heroicons/optimized` trong lúc build.
  * `assets/vendor/daisyui.js`: cung cấp các component class cơ bản mà UI đang dùng, bọc bằng `plugin.withOptions(...)` để nhận được block options trong `@plugin`.
  * `assets/vendor/daisyui-theme.js`: khai báo CSS variables theme tối thiểu, cũng bọc bằng `plugin.withOptions(...)`.
  * `assets/vendor/topbar.js`: cung cấp progress bar cho Phoenix LiveView navigation.
  * Thêm exception trong `.gitignore`:

    ```gitignore
    !src/flagd-ui/assets/vendor/
    !src/flagd-ui/assets/vendor/*.js
    ```

    Nếu không có exception này thì các file sửa lỗi nằm trong thư mục `vendor/` sẽ bị Git ignore và lỗi sẽ tái diễn khi clone/build ở máy khác.
  * Cập nhật `phase3/deploy/build-push-images.sh` để source `.env.override` trước smoke build, đảm bảo `docker compose build checkout` cũng dùng registry ECR giống bước push chính:

    ```bash
    set -a
    . ./.env.override
    set +a
    ```

* **Xác minh:**
  Build riêng target `flagd-ui` đã chạy thành công qua `mix assets.deploy`, `mix compile`, `mix release` và export image local:

  ```bash
  cd techx-corp-platform
  set -a; . ./.env.override; set +a
  docker buildx bake -f docker-compose.yml flagd-ui --load --set flagd-ui.platform=linux/amd64
  ```

  Sau đó chạy full script thành công:

  ```bash
  ./phase3/deploy/build-push-images.sh
  ```

  Kết quả: script exit code `0`, image `1.0-flagd-ui` và các image `1.0-*` khác đã được push lên ECR `techx-corp` tại region `ap-southeast-1`.

---

## 8. Mẹo Tối Ưu Tốc Độ Build (Giảm 50% Thời Gian)

Mặc định script của Ban tổ chức build dạng **Multi-architecture (AMD64 + ARM64)**. Việc này rất tốn thời gian do Docker phải chạy giả lập QEMU cho kiến trúc không trùng với máy Mac của bạn.

* **Khuyến nghị:**
  Nếu cụm EKS của bạn chỉ sử dụng các node EC2 thông thường (kiến trúc AMD64), hãy chỉnh sửa script để **chỉ build bản `linux/amd64`**, thời gian build sẽ giảm một nửa và giảm đáng kể tải CPU/RAM cho máy.
* **Cách thực hiện:**
  Sửa các target `build-multiplatform` và `build-multiplatform-and-push` trong tệp **[techx-corp-platform/Makefile](file:///Users/enma/Downloads/Coding/Cloud_Engineer/Unitled/capstone-p/cap-phase3/techx-corp-platform/Makefile)**:

  ```makefile
  # Trước:
  set -a; . ./.env.override; set +a && docker buildx bake -f docker-compose.yml --push --set "*.platform=linux/amd64,linux/arm64"

  # Sau (Chỉ build AMD64 - Đã được cấu hình áp dụng):
  set -a; . ./.env.override; set +a && docker buildx bake -f docker-compose.yml --push --set "*.platform=linux/amd64"
  ```
