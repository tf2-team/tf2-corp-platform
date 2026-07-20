# Chạy Amazon Bedrock Nova trên máy local

Tài liệu này hướng dẫn cấu hình Docker Compose trên máy local để gọi Amazon Bedrock Nova thông qua AWS CLI profile.

## 1. Cấu hình AWS CLI profile

Tạo profile tên `bedrock-dev`:

```powershell
aws configure --profile bedrock-dev
```

Mỗi người dùng AWS credential được cấp riêng. Không đính kèm hoặc sao chép file CSV access key vào ClickUp, chat hay Git.

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

Trên Windows PowerShell, tạo thư mục local `bedrocks` và file JSON bên trong thay vì truyền JSON trực tiếp trên command line:

```powershell
$messages = @'
[
  {
    "role": "user",
    "content": [
      { "text": "Reply with OK" }
    ]
  }
]
'@

[System.IO.Directory]::CreateDirectory((Join-Path $PWD 'bedrocks')) | Out-Null
[System.IO.File]::WriteAllText(
  (Join-Path $PWD 'bedrocks/bedrock-messages.json'),
  $messages,
  (New-Object System.Text.UTF8Encoding($false))
)
```

Sau đó chạy một request Converse nhỏ trước khi khởi động Docker Compose:

```powershell
aws bedrock-runtime converse `
  --region us-east-1 `
  --profile bedrock-dev `
  --model-id us.amazon.nova-2-lite-v1:0 `
  --messages file://bedrocks/bedrock-messages.json
```

Lệnh phải trả về response. Nếu nhận `AccessDeniedException`, IAM identity cần quyền `bedrock:InvokeModel` cho Nova inference profile và foundation model.

## 3. Cấu hình Docker Compose

Cập nhật file `.env` local ở thư mục gốc repository. Không commit AWS credential hoặc đường dẫn máy cá nhân:

```text
AWS_PROFILE=bedrock-dev
AWS_CONFIG_DIR=C:/Users/<WindowsUser>/.aws
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
LLM_PROVIDER=bedrock
MEM0_LLM_PROVIDER=aws_bedrock
MEM0_DEFAULT_LLM_MODEL=us.amazon.nova-2-lite-v1:0
```

Thay `<WindowsUser>` bằng tên tài khoản Windows. Ví dụ:

```text
AWS_CONFIG_DIR=C:/Users/alex/.aws
```

Compose sẽ mount thư mục credential này dưới dạng chỉ đọc vào `shopping-copilot`, `product-reviews` và `mem0`.

## 4. Khởi động local stack

```powershell
docker compose up --build --detach frontend-proxy shopping-copilot mem0
```

Kiểm tra log của ba service AI:

```powershell
docker compose logs --tail=100 shopping-copilot product-reviews mem0
```

Mở `http://localhost:8080`, rồi thử một prompt tìm sản phẩm, một câu hỏi review và một thao tác thêm giỏ hàng. Lần build đầu có thể lâu vì Compose phải dựng các service phụ thuộc.

## 5. Cấu hình runtime mong đợi

| Service | Provider | Model |
| --- | --- | --- |
| Shopping Copilot | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Product Reviews | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Mem0 | Mem0 `aws_bedrock` provider | `us.amazon.nova-2-lite-v1:0` |

`LLM_PROVIDER=bedrock` và Nova model ID là cấu hình mặc định của Compose. Có thể ghi đè chúng trong `.env.override` để dùng một Bedrock inference profile khác đã được cấp quyền.
