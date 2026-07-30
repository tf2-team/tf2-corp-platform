#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Small shared adapter for Amazon Bedrock Converse requests."""

import os
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from .observability import call_model


T = TypeVar("T", bound=BaseModel)


def is_bedrock_provider() -> bool:
    return os.environ.get("LLM_PROVIDER", "groq").lower() == "bedrock"


def _response_text(response: dict) -> str:
    for content in response["output"]["message"]["content"]:
        if "text" in content:
            return content["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    raise RuntimeError("Bedrock Converse response did not include text content")


def _converse(system_prompt: str, user_prompt: str, workflow_step: str) -> dict:
    import boto3

    model = os.environ["BEDROCK_MODEL_ID"]
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    return call_model(
        lambda: client.converse(
            modelId=model,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={
                "maxTokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
                "temperature": 0.0,
            },
        ),
        model=model,
        provider="aws.bedrock",
        workflow_step=workflow_step,
    )


def converse_with_usage(
    system_prompt: str,
    user_prompt: str,
    *,
    workflow_step: str = "generation",
) -> tuple[str, int, int]:
    """Return (text, input_tokens, output_tokens) from a real Bedrock response.

    Token counts come from the provider usage block; they are not estimated
    from string length.
    """
    response = _converse(system_prompt, user_prompt, workflow_step)
    text = _response_text(response)
    usage = response.get("usage") or {}
    input_tokens = int(usage.get("inputTokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
    return text, input_tokens, output_tokens


def converse_text(
    system_prompt: str,
    user_prompt: str,
    *,
    workflow_step: str = "generation",
) -> str:
    text, _, _ = converse_with_usage(
        system_prompt, user_prompt, workflow_step=workflow_step
    )
    return text


def converse_json(
    response_model: type[T],
    system_prompt: str,
    user_prompt: str,
    usage_callback: Callable[[int, int], None] | None = None,
    *,
    workflow_step: str = "structured_generation",
) -> T:
    """Invoke Bedrock and validate its JSON response, retrying one malformed reply."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            text, input_tokens, output_tokens = converse_with_usage(
                f"{system_prompt}\nReturn valid JSON only; do not use Markdown fences.",
                user_prompt,
                workflow_step=workflow_step,
            )
            if usage_callback is not None:
                usage_callback(input_tokens, output_tokens)
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
            return response_model.model_validate_json(
                text
            )
        except ValidationError as exc:
            last_error = exc
    raise RuntimeError("Bedrock returned invalid structured output") from last_error

# Change trail: @hungxqt - 2026-07-29 - Merge Bedrock calls onto the content-free telemetry wrapper.
