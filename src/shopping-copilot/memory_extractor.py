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


_PROMPT = """\
Extract only durable shopping facts explicitly stated by the user.
Allowed memory_kind values: preference, constraint, shopping_goal.
For constraints, constraint_type is one of budget, brand, feature,
compatibility, exclusion. Otherwise constraint_type is null.
Do not store greetings, product-list positions, product IDs, instructions,
personal data, or facts inferred only from the assistant response.
Return JSON exactly as {"memories":[...]} with at most 5 memories.
"""


from techx_ai_common.observability import instructor_create, trace_subspan


def extract_memories(user_message: str) -> MemoryExtraction:
    with trace_subspan("memory.extraction"):
        if is_bedrock_provider():
            return converse_json(MemoryExtraction, _PROMPT, user_message)
        client = instructor.from_openai(
            OpenAI(
                base_url=os.environ["LLM_BASE_URL"],
                api_key=os.environ["OPENAI_API_KEY"],
            ),
            mode=instructor.Mode.JSON,
        )
        return instructor_create(
            instructor_client=client,
            model=os.environ["LLM_MODEL"],
            response_model=MemoryExtraction,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": user_message},
            ],
            surface="copilot",
            max_retries=2,
        )

# Change trail: @hungxqt - 2026-07-29 - Route memory extraction through instructor_create adapter with telemetry subspan.

