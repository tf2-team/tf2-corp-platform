#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shopping-specific wrappers for the shared Bedrock Converse adapter."""

from techx_ai_common import bedrock as _shared_bedrock

import metrics as copilot_metrics


is_bedrock_provider = _shared_bedrock.is_bedrock_provider


def converse_json(response_model, system_prompt: str, user_prompt: str):
    return _shared_bedrock.converse_json(
        response_model,
        system_prompt,
        user_prompt,
        usage_callback=lambda input_tokens, output_tokens: (
            copilot_metrics.record_model_call(
                "bedrock", input_tokens, output_tokens
            )
        ),
    )
