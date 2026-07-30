#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shopping-specific wrappers for the shared Bedrock Converse adapter."""

from __future__ import annotations

from techx_ai_common import bedrock as _shared_bedrock

import metrics as copilot_metrics


is_bedrock_provider = _shared_bedrock.is_bedrock_provider
BedrockUnavailableError = _shared_bedrock.BedrockUnavailableError
BedrockDeadlineExceededError = _shared_bedrock.BedrockDeadlineExceededError
CircuitBreakerOpenError = _shared_bedrock.CircuitBreakerOpenError
InvalidModelOutputError = _shared_bedrock.InvalidModelOutputError


def converse_raw(
    request,
    *,
    workflow_step: str,
    deadline: float | None = None,
):
    return _shared_bedrock.converse_raw(
        request,
        workflow_step=workflow_step,
        deadline=deadline,
        usage_callback=lambda input_tokens, output_tokens: (
            copilot_metrics.record_model_call(
                "bedrock", input_tokens, output_tokens
            )
        ),
    )


def converse_json(
    response_model,
    system_prompt: str,
    user_prompt: str,
    *,
    workflow_step: str = "structured_generation",
    deadline: float | None = None,
):
    return _shared_bedrock.converse_json(
        response_model,
        system_prompt,
        user_prompt,
        usage_callback=lambda input_tokens, output_tokens: (
            copilot_metrics.record_model_call(
                "bedrock", input_tokens, output_tokens
            )
        ),
        workflow_step=workflow_step,
        deadline=deadline,
    )


__all__ = [
    "BedrockDeadlineExceededError",
    "BedrockUnavailableError",
    "CircuitBreakerOpenError",
    "InvalidModelOutputError",
    "converse_json",
    "converse_raw",
    "is_bedrock_provider",
]
