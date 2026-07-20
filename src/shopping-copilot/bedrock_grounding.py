#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Bedrock generation path that reuses the existing grounding contract."""

from bedrock_runtime import converse_json
from techx_ai_common.contracts import GroundedDraft, SafeReviewSet
from techx_ai_common.grounding import _SYSTEM_PROMPT, _build_review_prompt


def generate_grounded_summary(safe_reviews: SafeReviewSet, question: str = "") -> GroundedDraft:
    return converse_json(
        GroundedDraft,
        _SYSTEM_PROMPT,
        _build_review_prompt(safe_reviews, question),
    )
