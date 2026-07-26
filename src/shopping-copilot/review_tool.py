#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Review-grounded Q&A tool for Shopping Copilot (A2.2).

Reuses the shared grounding pipeline (generate_grounded_summary +
validate_grounded_summary) and guardrails (sanitize_reviews). Product ID is validated against the
allowed_product_ids set from the catalog search result before any
review fetch, preventing cross-product contamination.

Public API:
    answer_with_reviews(product_id, question, allowed_product_ids, product_reviews_stub)
        -> GroundedResponse
"""

import logging

from bedrock_grounding import generate_grounded_summary as generate_bedrock_grounded_summary
from bedrock_runtime import is_bedrock_provider
from techx_ai_common.contracts import GroundedResponse, ResponseStatus
from techx_ai_common.grounding import generate_grounded_summary, validate_grounded_summary
from techx_ai_common.guardrails import sanitize_reviews
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc

logger = logging.getLogger("review_tool")


def answer_with_reviews(
    product_id: str,
    question: str,
    allowed_product_ids: list[str],
    product_reviews_stub: demo_pb2_grpc.ProductReviewServiceStub,
) -> GroundedResponse:
    """Return a grounded answer about a product based on its reviews.

    Enforces that product_id is in allowed_product_ids (products returned
    by catalog search in this same request) to prevent cross-product answers.

    Returns:
        GroundedResponse with status GROUNDED, ABSTAINED.
        Never returns BLOCKED — that decision belongs to guardrails.py.

    Raises:
        ValueError: if product_id is not in allowed_product_ids.
        Exception: gRPC or grounding errors are propagated to the caller
                   (LangGraph node) to route to fallback.
    """
    if product_id not in allowed_product_ids:
        raise ValueError(
            f"Product ID '{product_id}' is not in allowed_product_ids for this request. "
            "Refusing to fetch reviews for an out-of-scope product."
        )

    # Fetch reviews via gRPC.
    response = product_reviews_stub.GetProductReviews(
        demo_pb2.GetProductReviewsRequest(product_id=product_id)
    )

    # Convert proto reviews to the raw format sanitize_reviews expects.
    raw_reviews = [
        {
            "id": r.id,
            "username": r.username,
            "description": r.description,
            "score": r.score,
        }
        for r in response.product_reviews
    ]

    safe_reviews = sanitize_reviews(product_id, raw_reviews)

    if not safe_reviews.reviews:
        logger.info(
            "No safe reviews for product_id=%r (blocked or empty). Abstaining.",
            product_id,
        )
        return GroundedResponse(
            status=ResponseStatus.ABSTAINED,
            reason="The current reviews do not provide enough information.",
        ), safe_reviews

    draft = (
        generate_bedrock_grounded_summary(safe_reviews, question)
        if is_bedrock_provider()
        else generate_grounded_summary(safe_reviews)
    )
    grounded = validate_grounded_summary(draft, safe_reviews)

    logger.info(
        "Review Q&A for product_id=%r: status=%s claims=%d",
        product_id, grounded.status.value, len(grounded.claims),
    )
    return grounded, safe_reviews
