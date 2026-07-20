# Run Amazon Bedrock Nova Locally

This guide configures local Docker Compose to call Amazon Bedrock Nova through an AWS CLI profile.

## 1. Configure an AWS CLI profile

Create a profile named `bedrock-dev`:

```powershell
aws configure --profile bedrock-dev
```

Enter the access key ID and secret access key when prompted, then use:

```text
Default region name: us-east-1
Default output format: json
```

Verify that AWS CLI can use the profile:

```powershell
aws sts get-caller-identity --profile bedrock-dev
```

## 2. Verify Bedrock Nova access

Run a small Converse request before starting Docker Compose:

```powershell
aws bedrock-runtime converse `
  --region us-east-1 `
  --profile bedrock-dev `
  --model-id us.amazon.nova-2-lite-v1:0 `
  --messages '[{"role":"user","content":[{"text":"Reply with OK"}]}]'
```

The command must return a response. If it returns `AccessDeniedException`, the IAM identity needs `bedrock:InvokeModel` for the Nova inference profile and foundation model.

## 3. Configure Docker Compose

Create or update the untracked file `.env.override` in the repository root:

```text
AWS_PROFILE=bedrock-dev
AWS_CONFIG_DIR=C:/Users/<WindowsUser>/.aws
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
```

Replace `<WindowsUser>` with the Windows account name. For example:

```text
AWS_CONFIG_DIR=C:/Users/alex/.aws
```

Compose mounts this directory read-only into `shopping-copilot`, `product-reviews`, and `mem0`.

## 4. Start the local stack

```powershell
docker compose --env-file .env --env-file .env.override up --build --detach
```

Check the three AI services:

```powershell
docker compose --env-file .env --env-file .env.override logs --tail=100 shopping-copilot product-reviews mem0
```

## 5. Expected runtime configuration

| Service | Provider | Model |
| --- | --- | --- |
| Shopping Copilot | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Product Reviews | Bedrock Converse | `us.amazon.nova-2-lite-v1:0` |
| Mem0 | Mem0 `aws_bedrock` provider | `us.amazon.nova-2-lite-v1:0` |

`LLM_PROVIDER=bedrock` and the Nova model ID are Compose defaults. They can be overridden in `.env.override` for a different permitted Bedrock inference profile.
