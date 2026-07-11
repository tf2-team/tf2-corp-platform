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
| Terraform path | `environments/production` (giữ chính tả thư mục) |

### Development

| Hằng số | Giá trị |
|---|---|
| ECR project prefix | `techx-dev-corp` |
| Image base | `493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-dev-corp` |
| Git branch → CD | `techx-dev-corp` |
| GitHub Environment | `development` |
| Terraform path | `environments/development` |

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

terraform -chdir=environments/production init -backend-config=backend.hcl
terraform -chdir=environments/production fmt -check
terraform -chdir=environments/production validate
terraform -chdir=environments/production plan -out=prod.tfplan
# Review plan — đặc biệt các aws_ecr_repository nested
terraform -chdir=environments/production apply "prod.tfplan"
```

Outputs hữu ích:

```bash
terraform -chdir=environments/production output ecr_image_base_url
terraform -chdir=environments/production output ecr_service_names
terraform -chdir=environments/production output github_actions_ecr_role_arn
```

### Bước 3 (tuỳ chọn): Provision development

```bash
terraform -chdir=environments/development init -backend-config=backend.hcl
terraform -chdir=environments/development plan -out=dev.tfplan
terraform -chdir=environments/development apply "dev.tfplan"

terraform -chdir=environments/development output ecr_image_base_url
# → .../techx-dev-corp
terraform -chdir=environments/development output github_actions_ecr_role_arn
```

Gán output `github_actions_ecr_role_arn` vào GitHub Environment variable **`AWS_ROLE_ARN`**, và `ecr_image_base_url` vào **`IMAGE_NAME`** (xem [CICD.md](./CICD.md)).

---

## Phase 2: EKS Kubeconfig & AWS Load Balancer Controller

Terraform output `aws_load_balancer_controller_helm_command` installs the controller with **IRSA**, **`region`**, and **`vpcId`**.  
Do not omit `region`/`vpcId`: without them the controller falls back to EC2 IMDS and often fails on EKS with `ec2imds GetMetadata context deadline exceeded` (IMDSv2 hop limit).

```bash
aws eks update-kubeconfig --region us-east-1 --name techx-tf2
kubectl get nodes
```

```bash
helm repo add eks https://aws.github.io/eks-charts && helm repo update

# Production or development — use matching environment
terraform -chdir=environments/production output -raw aws_load_balancer_controller_helm_command
# Run the printed helm upgrade --install (includes region + vpcId + role-arn)

kubectl get deployment -n kube-system aws-load-balancer-controller
kubectl -n kube-system rollout status deployment/aws-load-balancer-controller --timeout=120s
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=50
# Healthy: version log line. Unhealthy: failed to get VPC ID / ec2imds deadline exceeded
```

---

## Phase 2a: Secrets Manager + ESO (SEC-05)

App chart defaults use `secretKeyRef` (no production passwords in Git). Infra owns ASM shells + ESO IRSA.

```bash
# From techx-corp-infra
terraform -chdir=environments/production apply

# Bootstrap ASM (current live creds only — not new random DB passwords)
# Always use full extension (.ps1 / .cmd / .sh)
./scripts/bootstrap-asm-secrets.sh techx-corp/production us-east-1          # bash / Git Bash / WSL
# Windows PowerShell:  .\scripts\bootstrap-asm-secrets.ps1 techx-corp/production us-east-1
# Windows CMD:         scripts\bootstrap-asm-secrets.cmd techx-corp/production us-east-1

# Install ESO (do not interrupt --wait; leave shell open until STATUS=deployed)
helm repo add external-secrets https://charts.external-secrets.io && helm repo update
terraform -chdir=environments/production output -raw external_secrets_helm_command
# run printed command, then:
helm status external-secrets -n external-secrets   # expect STATUS: deployed

# ClusterSecretStore
terraform -chdir=environments/production output -raw external_secrets_cluster_secret_store_manifest | kubectl apply -f -
kubectl get clustersecretstore aws-secretsmanager

# secrets-chart → wait Ready → app chart
```

If Helm reports `another operation (install/upgrade/rollback) is in progress`:

```bash
helm status external-secrets -n external-secrets   # often pending-install
helm uninstall external-secrets -n external-secrets --wait
# re-run external_secrets_helm_command
```

Runbook: `techx-corp-chart/docs/operations/external-secrets.md` · infra: `techx-corp-infra/docs/DEPLOYMENT.md` Phase 2a + troubleshooting §5.

---

## Phase 3: Docker Image Build & Push

*Thực hiện tại repository `techx-corp-platform`*

> [!TIP]
> **Khuyến nghị — GitHub Actions** (`.github/workflows/build-and-push.yml`):
>
> **Job graph:** `CI → prepare → AWS/ECR preflight → build matrix (21) → verify ECR → release-ready → update-chart-dev (dev only)`
>
> | Trigger | GitHub Environment | ECR PROJECT |
> |---|---|---|
> | push `main` with `src/**` / tag `v*` | `production` | `techx-corp` |
> | push `techx-dev-corp` with `src/**` | `development` | `techx-dev-corp` |
> | branch push without `src/**` | — | **skipped** |
> | `workflow_dispatch` | chọn thủ công | theo environment (republish khi chỉ sửa bake/compose/CI) |
>
> Tag CI: `sha-<7-char>` trên branch; tên tag git (ví dụ `v1.2.3`) khi push tag.  
> Catalog: 21 release images trong `docker-bake.hcl` (gồm customized `opensearch`); cache tag `${IMAGE_NAME}/<service>:buildcache`.  
> Sau **release-ready** xanh: **dev** auto direct-push `values-dev.yaml` tag (secret `CHART_REPO_TOKEN`); **prod** vẫn mở PR values chart thủ công.  
> Chi tiết OIDC / Environments / chart token: **[CICD.md](./CICD.md)**.

> [!IMPORTANT]
> **`.env.override`** có thể trỏ registry test (`.../test`).  
> CI **không** source `.env.override`. Khi chạy tay: ghi đè `IMAGE_NAME` / `DEMO_VERSION` qua env, hoặc sửa `.env.override` cẩn thận.

### Bước 0 (ưu tiên): CI/CD

1. Setup GitHub Environments (`AWS_ROLE_ARN`, `IMAGE_NAME`) theo [CICD.md](./CICD.md).
2. **Dev chart auto-promote (one-time operator setup)** — chi tiết đầy đủ: [CICD.md §4 Operator setup](./CICD.md#4-operator-setup--chart-promote-token-dev-automation):

   | Step | Action |
   |---|---|
   | A | Create fine-grained PAT (chart repo only, **Contents: Read and write**) |
   | B | Platform repo secret **`CHART_REPO_TOKEN`** = PAT |
   | C | Optional vars `CHART_REPO` / `CHART_BRANCH` (defaults usually OK) |
   | D | Chart branch `techx-dev-corp` allows that PAT identity to **direct push** |
   | E | Dry-run publish `development` → job **Update chart values-dev tag** green |

   Auth: push uses the **PAT** (not platform `GITHUB_TOKEN`); commit author may show as `github-actions[bot]`.  
   Prod chart tag still requires a **manual** values PR.

3. Push `techx-dev-corp` (dev) trước; promote production chỉ sau khi development pass.
4. Xác minh workflow: 21 job build riêng; job **Verify ECR** + **Release ready** xanh; dev có thêm **Update chart values-dev tag**.
5. Xác minh tag runtime (và tùy chọn `buildcache`):

   ```bash
   aws ecr describe-images --repository-name techx-corp/ad \
     --image-ids imageTag=sha-<7char> --region us-east-1
   # dev: techx-dev-corp/ad
   # lặp cho đủ 21 service trong catalog release (gồm opensearch)
   # dev: chart values-dev.yaml default.image.tag được bot push sau release-ready
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
docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push
```

Kết quả mẫu: `.../techx-corp/ad:sha-manual` + cache `.../techx-corp/ad:buildcache`, …

Hoặc Makefile sau khi set `.env.override`:

```env
IMAGE_NAME=493499579600.dkr.ecr.us-east-1.amazonaws.com/techx-corp
IMAGE_VERSION=sha-manual
DEMO_VERSION=sha-manual
```

```bash
make create-multiplatform-builder
make build-multiplatform-and-push   # bake group "release" (21 services)
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
terraform -chdir=environments/production force-unlock <LOCK_ID>
```

### 2. ALB không tạo / controller CrashLoop

```bash
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=100
kubectl get sa aws-load-balancer-controller -n kube-system -o yaml
```

| Symptom | Fix |
|---|---|
| `failed to get VPC ID` / `ec2imds GetMetadata` / `context deadline exceeded` | Reinstall from Terraform output (must set `--set region=…` and `--set vpcId=…`). See Phase 2. |
| Missing `eks.amazonaws.com/role-arn` on SA | Re-run helm command from `aws_load_balancer_controller_helm_command` |
| Controller Ready but no ALB | Subnet tags: `kubernetes.io/role/elb=1` (public), `kubernetes.io/role/internal-elb=1` (private) |

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
