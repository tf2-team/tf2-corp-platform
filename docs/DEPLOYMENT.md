# Tài liệu Hướng dẫn Triển khai End-to-End (Production Runbook)

> [!NOTE]
> **Vai trò của Repository này (`techx-corp-platform`):**
> Repository này chịu trách nhiệm chính về việc đóng gói mã nguồn ứng dụng, build và push Docker images cho toàn bộ các dịch vụ microservices lên AWS ECR Registry theo quy ước **`[REGISTRY]/[PROJECT]/[SERVICE]:[VERSION]`**.

---

## 1. Mục tiêu (Objectives)

Tài liệu này cung cấp hướng dẫn từng bước để triển khai toàn bộ nền tảng TechX Corp lên AWS EKS. Quy trình bao gồm:

- Khởi tạo hạ tầng cơ sở và Remote State bằng Terraform (`techx-corp-infra`).
- Tạo **nested ECR repositories** (`techx-corp/*`, `techx-dev-corp/*`) và IAM role GitHub Actions OIDC.
- Triển khai EKS Cluster và cấu hình AWS Load Balancer Controller.
- Build và Push Docker images (CI/CD hoặc thủ công).
- Triển khai ứng dụng bằng Helm (`techx-corp-chart`) với ALB, smoke test và rollback an toàn.

## 2. Bản đồ Repository (Repository Map)

| Repository | Vai trò |
|---|---|
| **`techx-corp-platform`** | Mã nguồn microservices, Dockerfiles, Compose/Buildx, GitHub Actions build/push |
| **`techx-corp-infra`** | Terraform: VPC, EKS, nested ECR, GitHub OIDC roles, ALB Controller IAM |
| **`techx-corp-chart`** | Helm chart, public ALB values, smoke test, rollout/rollback |

## 3. Điều kiện tiên quyết (Prerequisites)

- **AWS Account**: `493499579600`, region `us-east-1`
- **AWS CLI**, **Terraform** `>= 1.10.0` (khuyến nghị `v1.15.7`), provider `~> 5.0`
- **Docker & Buildx** (multi-arch)
- **Helm** v3+, **kubectl**
- **GitHub** (repo `tmcmanhcuong/tf2-corp-platform`) đã cấu hình Environments + OIDC (xem [CICD.md](./CICD.md))

## 4. Các Hằng số & Cấu hình Hệ thống

### Production

| Hằng số | Giá trị |
|---|---|
| AWS Account / Region | `493499579600` / `us-east-1` |
| Project (infra) | `techx` |
| EKS Cluster | `techx-tf2` |
| ECR project prefix | `techx-corp` |
| Image base (`IMAGE_NAME` / Helm `repository`) | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp` |
| Git branch → CD | `main` (hoặc tag `v*`) |
| GitHub Environment | `production` |
| Namespace | `techx-corp` |
| Terraform path | `enviroments/production` (giữ chính tả thư mục) |

### Development

| Hằng số | Giá trị |
|---|---|
| ECR project prefix | `techx-dev-corp` |
| Image base | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` |
| Git branch → CD | `techx-dev-corp` |
| GitHub Environment | `development` |
| Terraform path | `enviroments/development` |

### Quy ước đặt tên image (bắt buộc)

```text
[REGISTRY]/[PROJECT]/[SERVICE]:[VERSION]
```

Ví dụ:

```text
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp/ad:sha-a1b2c3d
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp/checkout:sha-a1b2c3d
493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp/frontend:sha-a1b2c3d
```

| Thành phần | Ý nghĩa | Ví dụ |
|---|---|---|
| `REGISTRY` | ECR registry host | `493499579600.dkr.ecr.us-east-1.amazonaws.com` |
| `PROJECT` | Prefix ECR (môi trường) | `techx-corp`, `techx-dev-corp` |
| `SERVICE` | Tên microservice | `ad`, `checkout`, `frontend` |
| `VERSION` | Tag phiên bản | `sha-a1b2c3d`, `v1.2.3` |

Compose / bake:

```text
${IMAGE_NAME}/<service>:${DEMO_VERSION}
# IMAGE_NAME = REGISTRY/PROJECT (không gồm service)
```

Helm:

```text
default.image.repository = REGISTRY/PROJECT
default.image.tag        = VERSION
# Chart tự append /SERVICE → REGISTRY/PROJECT/SERVICE:VERSION
```

> **Lưu ý:** Định dạng cũ `REGISTRY/PROJECT:VERSION-SERVICE` (ví dụ `techx-corp:1.0-ad`) **không còn dùng**.

---

## Phase 1: Terraform Bootstrapping & Production Provisioning

*Thực hiện tại repository `techx-corp-infra`*

> [!CAUTION]
> **Quy tắc an toàn Terraform:**
> 1. **KHÔNG COMMIT** `*.tfstate`, `*.tfstate.backup`.
> 2. **KHÔNG COMMIT** `backend.hcl` thật.
> 3. **Luôn** `plan -out=...` → review → `apply` file plan (không `apply` trực tiếp trên production).

### Bước 1: Bootstrap Remote State (S3)

1. `terraform -chdir=bootstrap init`
2. `terraform -chdir=bootstrap plan -out=bootstrap.tfplan`
3. `terraform -chdir=bootstrap apply "bootstrap.tfplan"`
4. Tạo `bootstrap/backend.hcl` (không commit):

   ```hcl
   bucket       = "techx-tf-state-493499579600-us-east-1"
   key          = "bootstrap/terraform.tfstate"
   region       = "us-east-1"
   encrypt      = true
   use_lockfile = true
   ```

5. Bật backend S3 và migrate state:

   ```bash
   terraform -chdir=bootstrap init -migrate-state -force-copy -backend-config=backend.hcl
   terraform -chdir=bootstrap state list
   ```

### Bước 2: Provision production (VPC, EKS, nested ECR, GHA OIDC)

Terraform production tạo:

- VPC + EKS (`techx-tf2`)
- **Nested ECR**: `techx-corp/<service>` cho toàn bộ catalog platform
- **GitHub Actions OIDC provider** + role `techx-gha-platform-prod` (push ECR)
- IAM ALB Controller

```bash
# backend.hcl (không commit)
# key = "production/terraform.tfstate"

terraform -chdir=enviroments/production init -backend-config=backend.hcl
terraform -chdir=enviroments/production fmt -check
terraform -chdir=enviroments/production validate
terraform -chdir=enviroments/production plan -out=prod.tfplan
# Review plan — đặc biệt các aws_ecr_repository nested
terraform -chdir=enviroments/production apply "prod.tfplan"
```

Outputs hữu ích:

```bash
terraform -chdir=enviroments/production output ecr_image_base_url
terraform -chdir=enviroments/production output ecr_service_names
terraform -chdir=enviroments/production output github_actions_ecr_role_arn
```

### Bước 3 (tuỳ chọn): Provision development

```bash
terraform -chdir=enviroments/development init -backend-config=backend.hcl
terraform -chdir=enviroments/development plan -out=dev.tfplan
terraform -chdir=enviroments/development apply "dev.tfplan"

terraform -chdir=enviroments/development output ecr_image_base_url
# → .../techx-dev-corp
terraform -chdir=enviroments/development output github_actions_ecr_role_arn
```

Gán output `github_actions_ecr_role_arn` vào GitHub Environment variable **`AWS_ROLE_ARN`**, và `ecr_image_base_url` vào **`IMAGE_NAME`** (xem [CICD.md](./CICD.md)).

---

## Phase 2: EKS Kubeconfig & AWS Load Balancer Controller

```bash
aws eks update-kubeconfig --region us-east-1 --name techx-tf2
kubectl get nodes
```

```bash
helm repo add eks https://aws.github.io/eks-charts && helm repo update
terraform -chdir=enviroments/production output -raw aws_load_balancer_controller_helm_command
# Chạy lệnh Helm in ra, sau đó:
kubectl get deployment -n kube-system aws-load-balancer-controller
```

---

## Phase 3: Docker Image Build & Push

*Thực hiện tại repository `techx-corp-platform`*

> [!TIP]
> **Khuyến nghị — GitHub Actions** (`.github/workflows/build-and-push.yml`):
>
> | Trigger | GitHub Environment | ECR PROJECT |
> |---|---|---|
> | push `main` / tag `v*` | `production` | `techx-corp` |
> | push branch `techx-dev-corp` | `development` | `techx-dev-corp` |
> | `workflow_dispatch` | chọn thủ công | theo environment |
>
> Tag CI: `sha-<7-char>` trên branch; tên tag git (ví dụ `v1.2.3`) khi push tag.  
> Chi tiết OIDC / Environments: **[CICD.md](./CICD.md)**.

> [!IMPORTANT]
> **`.env.override`** có thể trỏ registry test (`.../test`).  
> CI **không** source `.env.override`. Khi chạy tay: ghi đè `IMAGE_NAME` / `DEMO_VERSION` qua env, hoặc sửa `.env.override` cẩn thận.

### Bước 0 (ưu tiên): CI/CD

1. Setup GitHub Environments (`AWS_ROLE_ARN`, `IMAGE_NAME`) theo [CICD.md](./CICD.md).
2. Push `main` (prod) hoặc `techx-dev-corp` (dev), hoặc Run workflow.
3. Xác minh:

   ```bash
   aws ecr describe-images --repository-name techx-corp/ad --region us-east-1 --max-items 5
   # dev: techx-dev-corp/ad
   ```

### Bước 1: Login ECR (thủ công)

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 493499579600.dkr.ecr.us-east-1.amazonaws.com
```

### Bước 2: Build & push (thủ công)

```bash
docker buildx create --name techx-corp-builder --bootstrap --use \
  --driver docker-container --config ./buildkitd.toml

IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp \
IMAGE_VERSION=sha-manual DEMO_VERSION=sha-manual \
docker buildx bake -f docker-compose.yml --push \
  --set "*.platform=linux/amd64,linux/arm64"
```

Kết quả mẫu: `.../techx-corp/ad:sha-manual`, `.../techx-corp/checkout:sha-manual`, …

Hoặc Makefile sau khi set `.env.override`:

```env
IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp
IMAGE_VERSION=sha-manual
DEMO_VERSION=sha-manual
```

```bash
make create-multiplatform-builder
make build-multiplatform-and-push
```

---

## Phase 4: Helm Deploy

*Thực hiện tại repository `techx-corp-chart`*

Chart render image:

```text
{{ default.image.repository }}/{{ service }}:{{ default.image.tag }}
→ 493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp/ad:sha-a1b2c3d
```

```bash
helm upgrade --install techx-corp techx-corp-chart \
  -n techx-corp --create-namespace \
  -f techx-corp-chart/values-public-alb.yaml \
  --set default.image.repository=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp \
  --set default.image.tag=sha-a1b2c3d \
  --wait --atomic --timeout 10m --history-max 10
```

- `repository` = **REGISTRY/PROJECT** (không có `/service`)
- `tag` = **VERSION only** (không còn suffix `-service`)
- `--wait --atomic --timeout 10m --history-max 10`: sẵn sàng cao + auto-rollback

### Toggle ALB path block only (release already installed)

If the chart is already deployed, flip storefront path blocking without changing images:

```bash
# ON  — BLOCK /grafana /jaeger /loadgen /feature /flagservice /otlp-http (HTTP 403)
helm upgrade techx-corp techx-corp-chart \
  -n techx-corp \
  --reuse-values \
  --set components.frontend-proxy.publicAlb.blockSensitivePaths=true \
  --wait --timeout 5m

# OFF — allow all paths to frontend-proxy
helm upgrade techx-corp techx-corp-chart \
  -n techx-corp \
  --reuse-values \
  --set components.frontend-proxy.publicAlb.blockSensitivePaths=false \
  --wait --timeout 5m
```

Chi tiết posture + verify: `techx-corp-chart/docs/DEPLOYMENT.md` (Phase 4 — *Storefront ALB path blocking*).

---

## Phase 5: Verification & Access

```bash
kubectl get ingress frontend-proxy-public -n techx-corp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

Smoke test:

```bash
bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp

ALB_DNS=$(kubectl get ingress frontend-proxy-public -n techx-corp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp --alb-host "$ALB_DNS"
```

Route công cộng nhạy cảm (`/grafana`, `/jaeger`, `/loadgen`) qua ALB phải trả **HTTP 403**.

---

## Phase 6: Rollback & Safety

```bash
helm history techx-corp -n techx-corp
helm rollback techx-corp 5 -n techx-corp --wait --timeout 10m

kubectl -n techx-corp rollout status deploy/frontend-proxy --timeout=300s
kubectl -n techx-corp rollout status deploy/frontend --timeout=300s
kubectl -n techx-corp rollout status deploy/checkout --timeout=300s
kubectl -n techx-corp rollout status deploy/payment --timeout=300s

bash techx-corp-chart/scripts/smoke-test.sh --namespace techx-corp
```

---

## Troubleshooting

### 1. Terraform state lock

```bash
terraform -chdir=enviroments/production force-unlock <LOCK_ID>
```

### 2. ALB không tạo

```bash
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=100
```

Kiểm tra tag subnet: `kubernetes.io/role/elb=1` (public), `kubernetes.io/role/internal-elb=1` (private).

### 3. ErrImagePull / ImagePullBackOff

- Image phải là `.../techx-corp/<service>:<version>` (không phải `.../techx-corp:<version>-<service>`).
- Repo ECR nested đã được Terraform tạo: `aws ecr describe-repositories --repository-names techx-corp/ad`.
- Node role có `AmazonEC2ContainerRegistryReadOnly`.
- Helm `default.image.tag` khớp tag đã push (ví dụ `sha-a1b2c3d`).

### 4. State S3 hỏng

```bash
aws s3api list-object-versions --bucket techx-tf-state-493499579600-us-east-1 \
  --prefix production/terraform.tfstate
# get-object + terraform state push khi cần khôi phục
```

---

## Tài liệu liên quan

- [CICD.md](./CICD.md) — GitHub Actions, OIDC, Environments  
- `techx-corp-infra` — Terraform modules `ecr`, `github-actions-ecr`  
- `techx-corp-chart` — Helm values + smoke test  
