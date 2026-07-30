# Product Reviews Service

This service returns product reviews for a specific product, along with an
AI-generated summary of the product reviews.

## Local Build

To build the protos, run from the root directory:

```sh
make docker-generate-protobuf
```

## Docker Build

From the root directory, run:

```sh
docker compose build product-reviews
```

## LLM Configuration

Use Amazon Bedrock Nova through `.env`:

``` yaml
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=global.amazon.nova-2-lite-v1:0
BEDROCK_MAX_TOKENS=1024
```

Supply AWS credentials locally (or an IRSA role in Kubernetes), then start the
stack:

```sh
docker compose up -d
```

The runtime uses the Bedrock Converse API. Never commit long-lived AWS
credentials; use an AWS profile locally and IRSA in Kubernetes.
