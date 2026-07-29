#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

from techx_ai_common.contracts import (
    GroundedClaim,
    GroundedDraft,
    GroundedResponse,
    ResponseStatus,
    SafeReview,
    SafeReviewSet,
)

import review_tool


def test_openai_review_grounding_receives_question_and_records_usage(monkeypatch):
    safe_reviews = SafeReviewSet(
        product_id="product-1",
        reviews=[
            SafeReview(
                source_id="review-1",
                text="Portable and clear enough to observe planets.",
                score="5",
            )
        ],
    )
    captured = {}

    monkeypatch.setattr(review_tool, "is_bedrock_provider", lambda: False)
    monkeypatch.setattr(review_tool, "sanitize_reviews", lambda *_: safe_reviews)

    def fake_generate(reviews, question="", usage_callback=None):
        captured["reviews"] = reviews
        captured["question"] = question
        usage_callback(11, 4)
        return GroundedDraft(
            answer="It is portable and suitable for observing planets.",
            claims=[
                GroundedClaim(
                    text="It is portable.",
                    sources=["review-1"],
                )
            ],
        )

    monkeypatch.setattr(review_tool, "generate_grounded_summary", fake_generate)
    monkeypatch.setattr(
        review_tool,
        "validate_grounded_summary",
        lambda *_: GroundedResponse(
            status=ResponseStatus.GROUNDED,
            answer="It is portable.",
            claims=[
                GroundedClaim(
                    text="It is portable.",
                    sources=["review-1"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        review_tool.copilot_metrics,
        "record_model_call",
        lambda provider, input_tokens, output_tokens: captured.update(
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )
    stub = SimpleNamespace(
        GetProductReviews=lambda *_: SimpleNamespace(
            product_reviews=[
                SimpleNamespace(
                    id="review-1",
                    username="shopper",
                    description="Portable and clear enough to observe planets.",
                    score="5",
                )
            ]
        )
    )

    grounded, returned_reviews = review_tool.answer_with_reviews(
        "product-1",
        "Can I use it to observe planets?",
        ["product-1"],
        stub,
    )

    assert grounded.status == ResponseStatus.GROUNDED
    assert returned_reviews is safe_reviews
    assert captured["question"] == "Can I use it to observe planets?"
    assert captured["provider"] == "openai"
    assert captured["input_tokens"] == 11
    assert captured["output_tokens"] == 4
