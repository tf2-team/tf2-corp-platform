#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Grounding pipeline for AI-generated product review summaries (A1.1).

Public API (per Day 2/3 implementation brief):
    generate_grounded_summary(safe_reviews, question="") -> GroundedDraft
    validate_grounded_summary(draft, safe_reviews) -> GroundedResponse

This module assumes safe_reviews.reviews is non-empty. The caller
(product_reviews_server.py) is responsible for short-circuiting to an
abstained response before calling generate_grounded_summary when
SafeReviewSet has no reviews — that check belongs to the orchestration
layer, not here.

grounding.py never sets ResponseStatus.BLOCKED. BLOCKED is a decision
that belongs to the safety layer (A1.2 / guardrails.py).
"""

import logging
import os
import re

import instructor
from openai import OpenAI

from .contracts import (
    GroundedClaim,
    GroundedDraft,
    GroundedResponse,
    ResponseStatus,
    SafeReview,
    SafeReviewSet,
)

logger = logging.getLogger("grounding")

# Fixed abstention message, per the Day 2/3 brief. Do not vary this string.
ABSTAIN_MESSAGE = "The current reviews do not provide enough information."

_SYSTEM_PROMPT = (
    "You are a product review assistant. You will be given a user question "
    "and a list of reviews, each tagged with a source_id. Answer the user's "
    "question in English using only those reviews. Focus on what the question "
    "asks (for example, negative feedback when asked about negative reviews). "
    "For every claim you make, cite the source_id(s) that support it. "
    "Do not include any claim that is not directly supported by at least one "
    "review. Do not invent numbers, durations, proper names, or comparisons "
    "that are not stated in the reviews. Prefer short claim sentences that "
    "read naturally when joined into one paragraph. "
    "Return the response in JSON format."
)

_MIN_KEYWORD_LENGTH = 4
_GENERIC_WORDS = {
    "dung", "duoc", "khong", "nhung", "cung", "voi", "cho", "rat",
    "tot", "san", "pham", "nay", "ngay", "lien", "tuc", "hoac",
}
_NUMBER_PATTERN = re.compile(r"\d+")


def _build_review_prompt(safe_review_set: SafeReviewSet, question: str = "") -> str:
    lines = [f"[{review.source_id}] {review.text}" for review in safe_review_set.reviews]
    reviews_block = "Reviews:\n" + "\n".join(lines)
    q = (question or "").strip()
    if q:
        return f"User question: {q}\n\n{reviews_block}\n\nAnswer the user question using only the reviews above."
    return reviews_block


def _get_client_and_model() -> tuple[OpenAI, str]:
    """Reads LLM connection settings from the environment, same variable
    names product_reviews_server.py already uses (LLM_BASE_URL, LLM_MODEL,
    OPENAI_API_KEY). Kept as its own function so tests can patch it
    without touching real env vars or making a network call.
    """
    client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=15.0,
    )
    model = os.environ["LLM_MODEL"]
    return client, model


def generate_grounded_summary(safe_reviews: SafeReviewSet, question: str = "") -> GroundedDraft:
    """Calls the LLM through Instructor, which enforces the GroundedDraft
    schema on the model's response and retries automatically on a schema
    mismatch. Client/model come from _get_client_and_model, not from
    parameters, to match the public signature in the Day 2/3 brief.

    question is optional input context only — the GroundedDraft / claims
    output contract is unchanged.
    """
    client, model = _get_client_and_model()
    instructor_client = instructor.from_openai(client, mode=instructor.Mode.JSON)
    return instructor_client.chat.completions.create(
        model=model,
        response_model=GroundedDraft,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_review_prompt(safe_reviews, question)},
        ],
    )


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_PATTERN.findall(text))


def _claim_has_fabricated_number(claim_text: str, source_texts: list[str]) -> bool:
    """Catches the "pin tot" -> "pin dung 20 gio" case: a claim that states
    a specific number (duration, quantity, etc.) not present in any of its
    cited sources. This is a more targeted check than keyword overlap,
    since a fabricated number can otherwise share enough generic words
    with the source to pass a plain overlap check.
    """
    claim_numbers = _extract_numbers(claim_text)
    if not claim_numbers:
        return False
    source_numbers: set[str] = set()
    for text in source_texts:
        source_numbers |= _extract_numbers(text)
    return not claim_numbers.issubset(source_numbers)


def _content_supported(claim_text: str, source_texts: list[str]) -> bool:
    """Cheap keyword-overlap check: does at least one cited review share a
    meaningful, non-generic word with the claim? Structural safety net,
    not a semantic guarantee — catches claims that cite a real source_id
    but talk about something that source never mentions at all. Number
    fabrication is handled separately by _claim_has_fabricated_number,
    since a shared generic word can otherwise mask a fabricated number.
    """
    claim_words = {
        w for w in claim_text.lower().split()
        if len(w) >= _MIN_KEYWORD_LENGTH and w not in _GENERIC_WORDS
    }
    if not claim_words:
        return True
    for text in source_texts:
        source_words = {
            w for w in text.lower().split()
            if len(w) >= _MIN_KEYWORD_LENGTH and w not in _GENERIC_WORDS
        }
        if claim_words & source_words:
            return True
    return False


def _validate_claim(claim: GroundedClaim, reviews_by_id: dict[str, SafeReview]) -> bool:
    # Layer 1 - citation: every cited source_id must exist in this
    # SafeReviewSet. Also implicitly enforces product scoping, since
    # SafeReviewSet only ever contains reviews for one product_id.
    if not all(source_id in reviews_by_id for source_id in claim.sources):
        logger.info(f"Dropping claim with unknown source_id(s): {claim.sources}")
        return False

    source_texts = [reviews_by_id[source_id].text for source_id in claim.sources]

    # Layer 2 - fabricated number/duration check.
    if _claim_has_fabricated_number(claim.text, source_texts):
        logger.info(f"Dropping claim with a number not present in its sources: '{claim.text}'")
        return False

    # Layer 3 - general content-overlap check.
    if not _content_supported(claim.text, source_texts):
        logger.info(f"Dropping claim not supported by source content: '{claim.text}'")
        return False

    return True


def validate_grounded_summary(
    draft: GroundedDraft,
    safe_reviews: SafeReviewSet,
) -> GroundedResponse:
    """Never returns model output directly. Filters draft.claims against
    safe_reviews and re-derives the answer from surviving claims only.
    """
    reviews_by_id = {review.source_id: review for review in safe_reviews.reviews}
    surviving_claims = [claim for claim in draft.claims if _validate_claim(claim, reviews_by_id)]

    if not surviving_claims:
        return GroundedResponse(status=ResponseStatus.ABSTAINED, reason=ABSTAIN_MESSAGE)

    # Re-derive the answer from surviving claims only. Never reuse
    # draft.answer as-is: it may reference a claim that was just dropped.
    answer = " ".join(claim.text for claim in surviving_claims)

    return GroundedResponse(
        status=ResponseStatus.GROUNDED,
        answer=answer,
        claims=surviving_claims,
    )
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
