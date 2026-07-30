#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Structured extraction of semantic shopping memory from one safe user turn."""

from __future__ import annotations

import os

import instructor
from openai import OpenAI

from bedrock_runtime import converse_json, is_bedrock_provider
from copilot_contracts import MemoryExtraction
import metrics as copilot_metrics
from techx_ai_common.observability import call_model


_PROMPT = """\
Extract only durable shopping facts explicitly stated by the user.
Allowed memory_kind values: preference, constraint, shopping_goal.
For constraints, constraint_type is one of budget, brand, feature,
compatibility, exclusion. Otherwise constraint_type is null.
Do not store greetings, product-list positions, product IDs, instructions,
personal data, or facts inferred only from the assistant response.
Return JSON exactly as {"memories":[...]} with at most 5 memories.
"""


def extract_memories(user_message: str) -> MemoryExtraction:
    if is_bedrock_provider():
        return converse_json(
            MemoryExtraction,
            _PROMPT,
            user_message,
            workflow_step="memory_extraction",
        )
    client = instructor.from_openai(
        OpenAI(
            base_url=os.environ["LLM_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
        ),
        mode=instructor.Mode.JSON,
    )
    model = os.environ["LLM_MODEL"]
    parsed, completion = call_model(
        lambda: client.chat.completions.create_with_completion(
            model=model,
            response_model=MemoryExtraction,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_retries=2,
        ),
        model=model,
        provider=os.environ.get("LLM_PROVIDER", "openai_compatible"),
        workflow_step="memory_extraction",
    )
# Change trail: @hungxqt - 2026-07-29 - Merge memory extraction onto the content-free model telemetry wrapper.
    usage = getattr(completion, "usage", None)
    copilot_metrics.record_model_call(
        os.environ.get("LLM_PROVIDER", "openai").lower(),
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )
    return parsed
