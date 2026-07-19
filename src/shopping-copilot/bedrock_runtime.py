#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Small Bedrock Converse adapter for Shopping Copilot structured output."""

import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def is_bedrock_provider() -> bool:
    return os.environ.get("LLM_PROVIDER", "groq").lower() == "bedrock"


def _response_text(response: dict) -> str:
    for content in response["output"]["message"]["content"]:
        if "text" in content:
            return content["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    raise RuntimeError("Bedrock Converse response did not include text content")


def converse_json(response_model: type[T], system_prompt: str, user_prompt: str) -> T:
    """Invoke the configured Bedrock inference profile and validate JSON output."""
    import boto3

    model_id = os.environ["BEDROCK_MODEL_ID"]
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    last_error: Exception | None = None

    for _ in range(2):
        response = client.converse(
            modelId=model_id,
            system=[{"text": f"{system_prompt}\nReturn valid JSON only; do not use Markdown fences."}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={
                "maxTokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
                "temperature": 0.0,
            },
        )
        try:
            return response_model.model_validate_json(_response_text(response))
        except ValidationError as exc:
            last_error = exc

    raise RuntimeError("Bedrock returned invalid structured output") from last_error
