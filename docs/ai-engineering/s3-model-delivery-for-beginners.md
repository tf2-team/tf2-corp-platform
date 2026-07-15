# Phân phối AI model từ Amazon S3 đến Kubernetes

> Tài liệu nhập môn dành cho người mới làm quen với Amazon S3, IAM/IRSA và cách đưa model vào một workload chạy trên Amazon EKS.

## 1. Bài toán cần giải quyết

Một AI service thường cần hai nhóm thành phần:

- **Runtime code**: application, Python libraries, model loader và business logic.
- **Model artifact**: model weights, tokenizer, cấu hình và metadata của một revision cụ thể.

Có thể đóng gói cả hai vào cùng một container image, nhưng model lớn làm image nặng, build chậm và khó cập nhật độc lập. Một kiến trúc linh hoạt hơn là:

1. Container image chỉ chứa runtime code và libraries.
2. Model artifact được lưu trong private Amazon S3 bucket.
3. Kubernetes tải model trước khi application khởi động.
4. Application sử dụng model ở chế độ offline.

Trong kiến trúc này:

> **Amazon S3 lưu và phân phối model; pod trên Amazon EKS mới là nơi chạy inference.**

## 2. Những khái niệm nền tảng

### 2.1 Amazon S3

Amazon S3 là dịch vụ **object storage**. Ba khái niệm chính là:

- **Bucket**: kho chứa cấp cao nhất.
- **Key**: tên đầy đủ của một object trong bucket.
- **Object**: dữ liệu của file cùng metadata được lưu dưới một key.

Ví dụ:

```text
s3://<model-bucket>/
  protectai/deberta-v3-base-prompt-injection-v2/
    <model-revision>/
      model.tar.gz
      model.tar.gz.sha256
      manifest.json
```

S3 không có thư mục thật giống ổ đĩa. Dấu `/` trong key tạo ra **prefix**, giúp con người và IAM policy nhóm object theo đường dẫn logic.

### 2.2 Model revision

Model revision là một định danh bất biến, thường là commit hash của model repository. Pin revision giúp bảo đảm:

- Mỗi lần build lấy đúng cùng một model.
- Dev và production có thể dùng cùng artifact đã được kiểm tra.
- Rollback không phụ thuộc vào một alias có thể thay đổi như `latest` hoặc `main`.

Một revision đã phát hành nên được xem là **immutable**: không ghi đè nội dung dưới cùng một revision key. Nếu model thay đổi, hãy phát hành revision mới.

### 2.3 Checksum SHA-256

Checksum là dấu vân tay của file. Khi nội dung file thay đổi dù chỉ một byte, SHA-256 gần như chắc chắn tạo ra giá trị khác.

Quy trình kiểm tra:

```text
Lúc build                              Lúc pod khởi động
---------                              ------------------
model.tar.gz                           tải model.tar.gz
     |                                 tải file .sha256
     v                                      |
tính SHA-256                                v
     |                                 tính lại SHA-256
     v                                      |
model.tar.gz.sha256                    so sánh hai giá trị
                                            |
                                  khớp -----+----- không khớp
                                   |                  |
                              tiếp tục          dừng khởi động
```

Checksum phát hiện file hỏng hoặc bị thay đổi. Để xác minh **ai đã phát hành** artifact, hệ thống có thể bổ sung chữ ký số hoặc artifact attestation; checksum một mình không cung cấp danh tính người phát hành.

### 2.4 IAM Role và IRSA

IAM quyết định một identity được phép gọi API AWS nào trên resource nào.

IRSA (IAM Roles for Service Accounts) liên kết một Kubernetes ServiceAccount với một IAM Role thông qua OIDC. Pod nhận temporary credentials và không cần lưu static access key.

```text
Kubernetes ServiceAccount
          |
          | EKS OIDC xác nhận danh tính
          v
      IAM Role
          |
          | s3:GetObject trên đúng model prefix
          v
    Private S3 bucket
```

Role runtime chỉ nên có quyền đọc:

- `s3:GetObject` trên approved model prefix.
- `s3:ListBucket` với điều kiện giới hạn cùng prefix nếu workload cần list.

Role này không cần `PutObject` hoặc `DeleteObject`. Quyền publish model thuộc về một operator hoặc CI identity riêng.

### 2.5 S3 Gateway VPC Endpoint

EKS node thường nằm trong private subnet. S3 Gateway VPC Endpoint thêm route để traffic tới S3 đi trên mạng AWS thay vì qua NAT Gateway hoặc public Internet.

Gateway Endpoint giải quyết **đường truyền mạng**, còn IAM giải quyết **quyền truy cập**. Có endpoint không đồng nghĩa pod tự động có quyền đọc bucket.

### 2.6 Init container và `emptyDir`

Init container chạy xong trước application container. Nó phù hợp với công việc chuẩn bị bắt buộc như tải và xác minh model.

`emptyDir` là volume được tạo cùng pod:

- Init container ghi model đã giải nén vào volume.
- Application container mount cùng volume ở chế độ read-only.
- Volume bị xóa khi pod bị xóa.

Do đó, mỗi pod mới tải lại model. Đây là thiết kế đơn giản và cô lập tốt; với model rất lớn hoặc scale-out thường xuyên, có thể cân nhắc node-local cache, EBS hoặc EFS sau khi đo thời gian khởi động và chi phí thực tế.

## 3. Kiến trúc tổng thể

```text
Hugging Face model revision
          |
          v
Artifact builder trong tf2-corp-platform
          |
          +--> model.tar.gz
          +--> model.tar.gz.sha256
          +--> manifest.json
          |
          v
Publisher identity -- s3:PutObject --> Private S3 bucket
                                             |
                                             | HTTPS qua Gateway Endpoint
                                             | s3:GetObject qua IRSA
                                             v
                              EKS init container tải model
                                             |
                                      kiểm tra SHA-256
                                             |
                                    giải nén vào emptyDir
                                             |
                                 kiểm tra marker .model-ready
                                             |
                                             v
                              Application mount read-only
                                             |
                                             v
                                  Chạy inference offline
```

## 4. Trách nhiệm của từng repository

### `tf2-corp-infra`: tạo tài nguyên AWS

Terraform chịu trách nhiệm tạo và cấu hình:

- Private S3 bucket.
- Public access block.
- Object ownership.
- Versioning.
- Server-side encryption.
- Bucket policy bắt buộc TLS.
- S3 Gateway VPC Endpoint.
- Runtime IAM Role và policy đọc model.
- Trust policy liên kết role với Kubernetes ServiceAccount.

Code tham khảo: `tf2-corp-infra/modules/ai-model-storage/main.tf`.

### `tf2-corp-platform`: tạo và sử dụng model artifact

Platform chịu trách nhiệm:

- Pin model ID và revision.
- Tải model vào Hugging Face cache layout.
- Thử load model ở chế độ offline trước khi đóng gói.
- Tạo archive, checksum, manifest và marker `.model-ready`.
- Cung cấp runtime code dùng model cache đã mount.
- Fail startup khi production yêu cầu model nhưng model không load được.

Code tham khảo:

- `src/product-reviews/scripts/build_model_artifact.py`
- `src/product-reviews/guardrails.py`

### `tf2-corp-chart`: kết nối S3 với pod

Helm chart chịu trách nhiệm:

- Gắn IRSA role ARN vào ServiceAccount.
- Khai báo S3 URI của model revision.
- Tạo init container dùng AWS CLI.
- Tải archive và checksum.
- Xác minh checksum và `.model-ready`.
- Giải nén model vào `emptyDir`.
- Mount cache read-only vào application.
- Bật Hugging Face và Transformers offline mode.

Code tham khảo:

- `tf2-corp-chart/values-prod.yaml`
- `tf2-corp-chart/templates/_objects.tpl`
- `tf2-corp-chart/templates/networkpolicy.yaml`

## 5. Vòng đời của model artifact

### Bước 1: Build một revision cố định

Từ `tf2-corp-platform`:

```powershell
.\src\product-reviews\.venv\Scripts\python.exe `
  src\product-reviews\scripts\build_model_artifact.py
```

Artifact builder tạo:

```text
dist/ai-model/
├── model.tar.gz
├── model.tar.gz.sha256
└── manifest.json
```

`manifest.json` nên mô tả tối thiểu model ID, revision, cache layout và SHA-256. Metadata này giúp audit và đối chiếu giữa artifact, chart và runtime.

### Bước 2: Publish vào S3

Publisher sử dụng identity có quyền ghi vào đúng prefix:

```powershell
$bucket = "<private-model-bucket>"
$model = "protectai/deberta-v3-base-prompt-injection-v2"
$revision = "<immutable-model-revision>"
$prefix = "s3://$bucket/$model/$revision"

aws s3 cp dist/ai-model/model.tar.gz `
  "$prefix/model.tar.gz" --profile <publisher-profile>

aws s3 cp dist/ai-model/model.tar.gz.sha256 `
  "$prefix/model.tar.gz.sha256" --profile <publisher-profile>

aws s3 cp dist/ai-model/manifest.json `
  "$prefix/manifest.json" --profile <publisher-profile>
```

Publisher và runtime là hai trust boundary khác nhau:

| Identity | Quyền chính | Mục đích |
|---|---|---|
| Operator hoặc CI publisher | `s3:PutObject` vào model prefix | Phát hành artifact |
| EKS ServiceAccount qua IRSA | `s3:GetObject` từ model prefix | Tải artifact lúc pod khởi động |

### Bước 3: Trỏ chart tới revision đã publish

Ví dụ cấu hình production:

```yaml
components:
  product-reviews:
    serviceAccount:
      create: true
      name: product-reviews
      annotations:
        eks.amazonaws.com/role-arn: <runtime-model-read-role-arn>

    modelDelivery:
      enabled: true
      awsRegion: <aws-region>
      s3Uri: s3://<private-model-bucket>/<model-id>/<revision>/model.tar.gz
      mountPath: /models/huggingface
      cacheSizeLimit: 2Gi
```

Artifact phải tồn tại trước khi rollout chart sử dụng URI mới.

### Bước 4: Init container chuẩn bị model

Logic cốt lõi của init container:

```sh
aws s3 cp "$MODEL_S3_URI" /tmp/model.tar.gz
aws s3 cp "${MODEL_S3_URI}.sha256" /tmp/model.tar.gz.sha256
cd /tmp
sha256sum -c model.tar.gz.sha256
mkdir -p /models
tar -xzf model.tar.gz -C /models
test -f /models/.model-ready
```

Mọi lệnh đều phải thành công. Nếu download, checksum, extraction hoặc marker validation thất bại, init container trả exit code khác `0` và Kubernetes không khởi động application container.

### Bước 5: Application chạy offline

Application container nhận các biến môi trường:

```text
HF_HOME=/models/huggingface
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
AI_GUARDRAIL_REQUIRE_MODEL=true
```

Cache được mount read-only. Runtime không tự tải model khác và không âm thầm fallback sang một revision ngoài quy trình phát hành.

## Tóm tắt

- S3 lưu và phân phối model; pod trên EKS chạy inference.
- Model được pin theo revision, đóng gói cùng checksum và manifest.
- Publisher có quyền upload; runtime pod chỉ có quyền đọc qua IRSA.
- S3 Gateway Endpoint cung cấp đường mạng riêng từ private subnet tới S3.
- Init container tải, xác minh và giải nén model trước khi application chạy.
- Application dùng cache read-only ở chế độ offline và không khởi động nếu model không hợp lệ.
- `emptyDir` tồn tại theo vòng đời pod, vì vậy pod mới sẽ tải lại model.
