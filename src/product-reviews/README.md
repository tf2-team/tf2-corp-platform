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

Local Docker Compose runs use GroqCloud through `.env`:

``` yaml
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-20b
OPENAI_API_KEY=replace-with-groq-api-key
```

Replace the API key placeholder locally, then start the stack:

```sh
docker compose up -d
```

Never commit a real API key. The `OPENAI_API_KEY` variable name remains
unchanged because the service uses the OpenAI-compatible interface for every
provider.

The selected model must support local tool calling because the service reads
`message.tool_calls` and uses `tool_choice="auto"`.

For a future Amazon Bedrock migration, `.env` includes a commented
configuration using the OpenAI-compatible `bedrock-mantle` endpoint. Confirm
that the chosen Bedrock model supports Chat Completions and client-side tool
use before enabling it.
