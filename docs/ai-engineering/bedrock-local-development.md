# Chạy Amazon Bedrock Nova trên máy local

Tài liệu này hướng dẫn cấu hình Docker Compose trên máy local để gọi Amazon Bedrock Nova thông qua AWS CLI profile.

## 1. Cấu hình AWS CLI profile

Tạo profile tên `bedrock-dev`:

```powershell
aws configure --profile bedrock-dev
```

Khi được hỏi, nhập access key ID và secret access key, sau đó đặt:

```text
Tên region mặc định: us-east-1
Định dạng output mặc định: json
```

Kiểm tra AWS CLI có thể dùng profile này:

```powershell
aws sts get-caller-identity --profile bedrock-dev
```

## 2. Kiểm tra quyền gọi Bedrock Nova

Chạy một request Converse nhỏ trước khi khởi động Docker Compose:

```powershell
aws bedrock-runtime converse `
  --region us-east-1 `
  --profile bedrock-dev `
  --model-id us.amazon.nova-2-lite-v1:0 `
  --messages '[{"role":"user","content":[{"text":"Reply with OK"}]}]'
```

Lệnh phải trả về response. Nếu nhận `AccessDeniedException`, IAM identity cần quyền `bedrock:InvokeModel` cho Nova inference profile và foundation model.

## 3. Cấu hình Docker Compose

Tạo hoặc cập nhật file không được Git theo dõi `.env.override` ở thư mục gốc repository:

```text
AWS_PROFILE=bedrock-dev
AWS_CONFIG_DIR=C:/Users/<WindowsUser>/.aws
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
```

Thay `<WindowsUser>` bằng tên tài khoản Windows. Ví dụ:

```text
AWS_CONFIG_DIR=C:/Users/alex/.aws
```

Compose sẽ mount thư mục credential này dưới dạng chỉ đọc vào `shopping-copilot`, `product-reviews` và `mem0`.

## 4. Khởi động local stack

```powershell
docker compose --env-file .env --env-file .env.override up --build --detach
```

Kiểm tra log của ba service AI:

```powershell
docker compose --env-file .env --env-file .env.override logs --tail=100 shopping-copilot product-reviews mem0
```

## 5. Cấu hình runtime mong đợi

| Service | Provider | Model |
| --- | --- | --- |
| Shopping Copilot | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Product Reviews | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Mem0 | Mem0 `aws_bedrock` provider | `us.amazon.nova-2-lite-v1:0` |

`LLM_PROVIDER=bedrock` và Nova model ID là cấu hình mặc định của Compose. Có thể ghi đè chúng trong `.env.override` để dùng một Bedrock inference profile khác đã được cấp quyền.
