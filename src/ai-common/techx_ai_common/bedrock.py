#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Small shared adapter for Amazon Bedrock Converse requests."""

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


def _converse(system_prompt: str, user_prompt: str) -> dict:
    import boto3

    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    ).converse(
        modelId=os.environ["BEDROCK_MODEL_ID"],
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={
            "maxTokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
            "temperature": 0.0,
        },
    )


def converse_text(system_prompt: str, user_prompt: str) -> str:
    return _response_text(_converse(system_prompt, user_prompt))


def converse_json(response_model: type[T], system_prompt: str, user_prompt: str) -> T:
    """Invoke Bedrock and validate its JSON response, retrying one malformed reply."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return response_model.model_validate_json(
                converse_text(f"{system_prompt}\nReturn valid JSON only; do not use Markdown fences.", user_prompt)
            )
        except ValidationError as exc:
            last_error = exc
    raise RuntimeError("Bedrock returned invalid structured output") from last_error
