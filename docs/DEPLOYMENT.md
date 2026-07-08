# Tài liệu Hướng dẫn Triển khai End-to-End (Production Runbook)

> [!NOTE]
> **Vai trò của Repository này (`techx-corp-platform`):**
> Repository này chịu trách nhiệm chính về việc đóng gói mã nguồn ứng dụng, build và push Docker images cho toàn bộ các dịch vụ microservices lên AWS ECR Registry.

---

## 1. Mục tiêu (Objectives)
Tài liệu này cung cấp hướng dẫn từng bước để triển khai toàn bộ nền tảng TechX Corp lên môi trường Production trên AWS EKS. Quy trình bao gồm:
- Khởi tạo hạ tầng cơ sở và Remote State bằng Terraform.
- Triển khai EKS Cluster và cấu hình AWS Load Balancer Controller.
- Build và Push Docker images của các microservices lên AWS ECR.
- Triển khai ứng dụng bằng Helm với chế độ High Availability, Ingress ALB, kiểm tra bảo mật route và cơ chế rollback tự động/thủ công.

## 2. Bản đồ Repository (Repository Map)
Hệ thống TechX Corp được chia thành 3 repository chuyên biệt:
- **`techx-corp-platform`**: Chứa mã nguồn ứng dụng microservices, Dockerfiles, cấu hình Docker Compose / Buildx để đóng gói hình ảnh ứng dụng.
- **`techx-corp-infra`**: Quản lý cơ sở hạ tầng dưới dạng mã (IaC) sử dụng Terraform để thiết lập VPC, EKS cluster, ECR registries, IAM roles và chính sách bảo mật.
- **`techx-corp-chart`**: Chứa Helm chart của ứng dụng để triển khai lên Kubernetes, định nghĩa các Ingress public ALB, chạy script kiểm tra khói (Smoke Test) và cấu hình các chính sách nâng cấp an toàn.

## 3. Điều kiện tiên quyết (Prerequisites)
Trước khi bắt đầu, hãy đảm bảo toán tử (operator) đã đáp ứng các điều kiện sau:
- **Tài khoản AWS**: Quyền truy cập quản trị vào tài khoản AWS ID `493499579600` tại vùng `us-east-1`.
- **AWS CLI**: Đã cài đặt và cấu hình credentials hợp lệ với profile AWS phù hợp.
- **Terraform**: Phiên bản `>= 1.10.0` (Khuyến nghị sử dụng v1.15.7), AWS provider `~> 5.0`.
- **Docker & Buildx**: Docker Engine đang hoạt động và hỗ trợ Buildx (để build/push multi-architecture images).
- **Helm**: Phiên bản `v3` trở lên.
- **kubectl**: Đã cài đặt để quản trị cluster Kubernetes.

## 4. Các Hằng số & Cấu hình Hệ thống (Constants & Configurations)
Quy trình triển khai sử dụng các hằng số cố định sau. Toán tử KHÔNG ĐƯỢC THAY ĐỔI các giá trị này để đảm bảo tính nhất quán trên môi trường production:
- **AWS Account ID**: `493499579600`
- **AWS Region**: `us-east-1`
- **Project Name**: `techx`
- **EKS Cluster Name**: `techx-tf2`
- **ECR Repository**: `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp`
- **Kubernetes Namespace mặc định**: `techx-corp` (Lưu ý: Mặc định triển khai ứng dụng vào namespace này. Nếu đã deploy tài nguyên demo vào một namespace khác từ trước, toán tử có thể ghi đè namespace tương ứng trong các câu lệnh).
- **Đường dẫn môi trường Live (Bảo toàn lỗi chính tả)**: `enviroments/production`

---

## Phase 1: Terraform Bootstrapping & Production Provisioning
*Thực hiện tại repository `techx-corp-infra`*

> [!CAUTION]
> **Quy tắc an toàn Terraform:**
> 1. **KHÔNG COMMIT file state cục bộ (`*.tfstate`, `*.tfstate.backup`)** lên Git vì chúng chứa thông tin nhạy cảm ở dạng văn bản rõ. Đảm bảo `.gitignore` đã chặn các file này.
> 2. **KHÔNG COMMIT file cấu hình backend thực tế (`backend.hcl`)** chứa thông tin cụ thể về bucket và state key.
> 3. **KHÔNG CHẠY apply trực tiếp không có plan review (`terraform apply`)**. Mọi thay đổi trên production bắt buộc phải chạy thông qua việc tạo plan trước (`terraform plan -out=prod.tfplan`), review cẩn thận, sau đó apply chính xác file plan đó (`terraform apply "prod.tfplan"`).

### Bước 1: Khởi tạo S3 Remote State Bucket (Bootstrap)
Bước này tạo hạ tầng lưu trữ S3 Bucket và KMS Key phục vụ cho việc quản lý Remote State tập trung.

1. Comment hoặc để trống block backend trong `bootstrap/provider.tf` (đã thực hiện mặc định).
2. Khởi tạo thư mục bootstrap:
   ```bash
   terraform -chdir=bootstrap init
   ```
3. Tạo plan lưu trữ:
   * PowerShell:
     ```powershell
     terraform -chdir=bootstrap plan "-out=bootstrap.tfplan"
     ```
   * CMD / Bash:
     ```bash
     terraform -chdir=bootstrap plan -out=bootstrap.tfplan
     ```
4. Áp dụng plan để tạo tài nguyên trên AWS:
   ```bash
   terraform -chdir=bootstrap apply "bootstrap.tfplan"
   ```
5. Tạo file cấu hình `bootstrap/backend.hcl` (KHÔNG commit file này):
   ```hcl
   bucket       = "techx-tf-state-493499579600-us-east-1"
   key          = "bootstrap/terraform.tfstate"
   region       = "us-east-1"
   encrypt      = true
   use_lockfile = true
   ```
6. Bỏ comment block `backend "s3" {}` trong `bootstrap/provider.tf` và di chuyển state file lên S3:
   * PowerShell:
     ```powershell
     terraform -chdir=bootstrap init "-migrate-state" "-force-copy" "-backend-config=backend.hcl"
     ```
   * CMD / Bash:
     ```bash
     terraform -chdir=bootstrap init -migrate-state -force-copy -backend-config=backend.hcl
     ```
7. Xác minh di chuyển thành công bằng cách liệt kê tài nguyên:
   ```bash
   terraform -chdir=bootstrap state list
   ```
   Sau khi xác nhận thành công, hãy xóa file `bootstrap/terraform.tfstate` cục bộ.

### Bước 2: Triển khai Hạ tầng Production
Chúng ta tiến hành tạo VPC, EKS Cluster (`techx-tf2`), ECR Registry, và các IAM roles cho môi trường Production.

1. Tạo file cấu hình `enviroments/production/backend.hcl` (KHÔNG commit file này):
   ```hcl
   bucket       = "techx-tf-state-493499579600-us-east-1"
   key          = "production/terraform.tfstate"
   region       = "us-east-1"
   encrypt      = true
   use_lockfile = true
   ```
2. Đảm bảo cấu hình backend trong `enviroments/production/provider.tf` đã được bật:
   ```hcl
   backend "s3" {
     key          = "production/terraform.tfstate"
     encrypt      = true
     use_lockfile = true
   }
   ```
3. Khởi tạo backend cho môi trường Production:
   * PowerShell:
     ```powershell
     terraform -chdir=enviroments/production init "-backend-config=backend.hcl"
     ```
   * CMD / Bash:
     ```bash
     terraform -chdir=enviroments/production init -backend-config=backend.hcl
     ```
4. Kiểm tra lỗi cú pháp và format:
   ```bash
   terraform -chdir=enviroments/production fmt -check
   terraform -chdir=enviroments/production validate
   ```
5. Thực hiện tạo plan triển khai:
   * PowerShell:
     ```powershell
     terraform -chdir=enviroments/production plan "-out=prod.tfplan"
     ```
   * CMD / Bash:
     ```bash
     terraform -chdir=enviroments/production plan -out=prod.tfplan
     ```
6. Review kỹ lưỡng nội dung plan, sau đó apply plan lên AWS:
   ```bash
   terraform -chdir=enviroments/production apply "prod.tfplan"
   ```

---

## Phase 2: EKS Kubeconfig & AWS Load Balancer Controller Installation
*Thực hiện tại môi trường shell quản trị*

Sau khi hạ tầng EKS đã được tạo thành công, ta cần kết nối và cài đặt AWS Load Balancer Controller để quản lý Ingress ALB.

### Bước 1: Cấu hình Kubeconfig
Chạy lệnh sau để tạo/cập nhật file cấu hình kết nối kubectl tới EKS Cluster `techx-tf2`:
```bash
aws eks update-kubeconfig --region us-east-1 --name techx-tf2
```
Kiểm tra kết nối tới cluster:
```bash
kubectl get nodes
```

### Bước 2: Cài đặt AWS Load Balancer Controller
1. Thêm EKS Helm repository:
   ```bash
   helm repo add eks https://aws.github.io/eks-charts
   helm repo update
   ```
2. Lấy giá trị IAM Role ARN từ output của Terraform ở Phase 1:
   ```bash
   terraform -chdir=enviroments/production output aws_load_balancer_controller_role_arn
   ```
   Hoặc chạy trực tiếp lệnh Helm được sinh ra tự động từ output của Terraform:
   ```bash
   terraform -chdir=enviroments/production output -raw aws_load_balancer_controller_helm_command
   ```
   *Lệnh Helm mẫu sinh ra bởi Terraform:*
   ```bash
   helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
     -n kube-system \
     --set clusterName=techx-tf2 \
     --set serviceAccount.create=true \
     --set serviceAccount.name=aws-load-balancer-controller \
     --set serviceAccount.annotations.eks\.amazonaws\.com/role-arn=arn:aws:iam::493499579600:role/techx-tf2-alb-controller
   ```
3. Kiểm tra trạng thái hoạt động của controller:
   ```bash
   kubectl get deployment -n kube-system aws-load-balancer-controller
   ```

---

## Phase 3: Docker Image Build & Push
*Thực hiện tại repository `techx-corp-platform`*

> [!IMPORTANT]
> **Lưu ý về file `.env.override`:**
> File cấu hình cục bộ `techx-corp-platform/.env.override` hiện tại đang được theo dõi trên Git trỏ tới repo test (`493499579600.dkr.ecr.us-east-1.amazonaws.com/test`). Do đó, nếu chạy trực tiếp các lệnh `make` thô, hình ảnh sẽ bị đẩy nhầm vào registry `/test`.
> Để triển khai môi trường Production, toán tử bắt buộc phải thực hiện một trong hai cách dưới đây:
> - **Cách 1 (Khuyến nghị trong CI/CD)**: Sử dụng các biến môi trường trực tiếp từ shell hoặc chạy trực tiếp lệnh `docker buildx bake` với các tham số ghi đè.
> - **Cách 2**: Kiểm tra và chỉnh sửa file `.env.override` cục bộ trỏ tới registry production trước khi chạy lệnh `make`.

### Bước 1: Đăng nhập vào AWS ECR Production
Chạy lệnh xác thực Docker với ECR trong region `us-east-1`:
```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 493499579600.dkr.ecr.us-east-1.amazonaws.com
```

### Bước 2: Thực hiện Build & Push hình ảnh dịch vụ
Sử dụng các hằng số quy định: `IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp`, `IMAGE_VERSION=1.0`, và `DEMO_VERSION=1.0`.

#### Cách 1: Sử dụng Docker CLI & Buildx Bake trực tiếp (Không dùng Makefile)
1. Tạo một multiplatform builder nếu chưa có:
   ```bash
   docker buildx create --name techx-corp-builder --bootstrap --use --driver docker-container --config ./buildkitd.toml
   ```
2. Build và Push trực tiếp bằng Docker Buildx Bake để tối ưu hóa caching và song song hóa:
   ```bash
   IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp IMAGE_VERSION=1.0 DEMO_VERSION=1.0 docker buildx bake -f docker-compose.yml --push --set "*.platform=linux/amd64,linux/arm64"
   ```

#### Cách 2: Sử dụng Makefile (Sau khi cập nhật cấu hình)
1. Cập nhật nội dung file `.env.override` cục bộ thành:
   ```env
   IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp
   IMAGE_VERSION=1.0
   DEMO_VERSION=1.0
   ```
2. Khởi tạo builder:
   ```bash
   make create-multiplatform-builder
   ```
3. Thực hiện build và push multiplatform:
   ```bash
   make build-multiplatform-and-push
   ```

---

## Phase 4: Helm Deploy
*Thực hiện tại repository `techx-corp-chart`*

Quy trình nâng cấp/triển khai ứng dụng an toàn sử dụng các tham số bắt buộc để đảm bảo tính sẵn sàng cao, kiểm tra trạng thái và tự động rollback khi gặp lỗi.

### Bước 1: Nâng cấp / Cài đặt Helm Release
Để triển khai ứng dụng, toán tử chạy lệnh nâng cấp tích hợp file cấu hình Ingress ALB công cộng (`values-public-alb.yaml`) và chỉ định ECR repo production:

```bash
helm upgrade --install techx-corp techx-corp-chart \
  -n techx-corp --create-namespace \
  -f techx-corp-chart/values-public-alb.yaml \
  --set default.image.repository=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp \
  --wait --atomic --timeout 10m --history-max 10
```

*Ý nghĩa của các tham số an toàn:*
- `-f techx-corp-chart/values-public-alb.yaml`: Kích hoạt public ALB Ingress cho component `frontend-proxy`.
- `--set default.image.repository=...`: Ghi đè địa chỉ ECR registry sang địa chỉ production cụ thể vùng `us-east-1`.
- `--wait`: Bắt buộc Helm chờ tất cả Pods chuyển sang trạng thái `Ready`, các PVCs được gán và các Ingress/Services hoạt động trước khi báo thành công.
- `--atomic`: Nếu có bất kỳ lỗi nào xảy ra trong quá trình triển khai hoặc hết thời gian timeout, Helm sẽ tự động rollback release về phiên bản chạy ổn định gần nhất trước đó.
- `--timeout 10m`: Cung cấp thời gian tối đa 10 phút để tải ảnh từ ECR và khởi động các database/broker (như PostgreSQL, Kafka, Valkey).
- `--history-max 10`: Giới hạn lưu trữ tối đa 10 revision để tránh ConfigMap bloating trong Kubernetes.

---

## Phase 5: Verification & Access
*Thực hiện tại repository `techx-corp-chart`*

Sau khi Helm báo trạng thái triển khai thành công, toán tử cần xác minh hệ thống hoạt động bình thường.

### Bước 1: Lấy địa chỉ Application Load Balancer (ALB)
AWS Load Balancer Controller sẽ phân bổ một ALB công cộng. Lấy hostname của ALB:
```bash
kubectl get ingress frontend-proxy-public -n techx-corp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```
*Lưu ý: Có thể mất từ 2-5 phút để AWS hoàn tất việc tạo ALB và phân giải DNS.*

### Bước 2: Chạy Smoke Test xác thực ứng dụng & Tính năng Chặn Route
Chạy script kiểm thử khói để tự động hóa các bước kiểm tra (truy cập homepage, lấy danh sách sản phẩm, thêm vào giỏ hàng, checkout và xác thực route-blocking):

1. **Kiểm tra thông qua Port-Forward cục bộ** (Tiện lợi để kiểm tra API nội bộ):
   ```bash
   bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp
   ```
2. **Kiểm tra trực tiếp qua Public ALB** (Bao gồm cả xác minh ALB Ingress route-blocking các đường dẫn nhạy cảm như `/grafana`, `/jaeger`, `/loadgen`):
   ```bash
   # Lấy địa chỉ ALB DNS
   ALB_DNS=$(kubectl get ingress frontend-proxy-public -n techx-corp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
   
   # Chạy smoke test hướng vào ALB
   bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp --alb-host "$ALB_DNS"
   ```
   Nếu tính năng chặn route (ALB route-blocking) cấu hình đúng, các request truy cập vào `/grafana` hay `/jaeger` qua ALB công cộng sẽ nhận mã lỗi `HTTP 403 Forbidden` và script smoke-test sẽ hiển thị trạng thái `✔ Route /grafana is blocked (HTTP 403)`.

---

## Phase 6: Rollback & Safety
Trường hợp xảy ra lỗi ứng dụng ở bước Smoke Test hoặc hệ thống bị giảm hiệu năng đột ngột sau nâng cấp, toán tử cần nhanh chóng đưa hệ thống về trạng thái ổn định.

### Cơ chế Rollback Helm
1. **Kiểm tra lịch sử các phiên bản** để tìm revision chạy tốt trước đó:
   ```bash
   helm history techx-corp -n techx-corp
   ```
2. **Thực hiện lệnh rollback** về revision mong muốn (ví dụ revision `5`):
   ```bash
   helm rollback techx-corp 5 -n techx-corp --wait --timeout 10m
   ```
3. **Xác minh trạng thái rollout** của các thành phần critical:
   ```bash
   kubectl -n techx-corp rollout status deploy/frontend-proxy --timeout=300s
   ```
   ```bash
   kubectl -n techx-corp rollout status deploy/frontend --timeout=300s
   ```
   ```bash
   kubectl -n techx-corp rollout status deploy/checkout --timeout=300s
   ```
   ```bash
   kubectl -n techx-corp rollout status deploy/payment --timeout=300s
   ```
4. **Chạy lại Smoke Test** để chắc chắn dịch vụ storefront đã hoạt động bình thường:
   ```bash
   bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp
   ```

---

## Troubleshooting Notes (Lưu ý xử lý sự cố)

### 1. Lỗi kẹt State Lock trong Terraform
Nếu tiến trình bị ngắt đột ngột và nhận thông báo lỗi lock state S3:
- Xác định `ID Lock` từ thông báo lỗi.
- Chạy lệnh giải phóng lock thủ công sau khi chắc chắn không có tiến trình nào khác đang chạy:
  ```bash
  terraform -chdir=enviroments/production force-unlock <LOCK_ID>
  ```

### 2. Lỗi AWS Load Balancer Controller không tạo ALB
- Kiểm tra log của controller trong namespace `kube-system`:
  ```bash
  kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=100
  ```
- Lỗi phổ biến thường do thiếu tag trên các Subnet của VPC để ALB tự động nhận diện (auto-discovery). Đảm bảo public subnet có tag `kubernetes.io/role/elb = 1` và private subnet có tag `kubernetes.io/role/internal-elb = 1`. Các tag này đã được module VPC của Terraform tự động cấu hình mặc định.

### 3. Lỗi ErrImagePull hoặc ImagePullBackOff
- Xác nhận toán tử đã push đúng Docker image với tag định dạng: `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp:1.0-<service-name>`.
- Kiểm tra EKS node có quyền pull image từ ECR không (quyền `AmazonEC2ContainerRegistryReadOnly` trên IAM Role của EKS Worker Nodes).

### 4. Lỗi S3 Backend Versioning & State Corruption
Nếu file remote state bị lỗi hoặc hỏng:
1. Xem lịch sử các version của `production/terraform.tfstate`:
   ```bash
   aws s3api list-object-versions --bucket techx-tf-state-493499579600-us-east-1 --prefix production/terraform.tfstate
   ```
2. Tải về phiên bản ổn định trước đó:
   ```bash
   aws s3api get-object --bucket techx-tf-state-493499579600-us-east-1 --key production/terraform.tfstate --version-id <version-id> restored_state.tfstate
   ```
3. Đẩy đè version tốt lên S3:
   ```bash
   terraform -chdir=enviroments/production state push restored_state.tfstate
   ```
