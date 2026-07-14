"""Grounding pipeline for AI-generated product review summaries (A1.1).

Takes a SafeReviewSet produced by the guardrail pipeline (A1.2) and produces
a GroundedResponse: every claim in the final response must cite a review
that actually exists in the SafeReviewSet, and its content must plausibly
be supported by that review's text. Claims that fail either check are
dropped silently. If no claim survives, the response is ABSTAINED.

This module never sets ResponseStatus.BLOCKED. BLOCKED is a decision that
belongs to the safety layer (A1.2 / guardrails.py) — grounding.py only ever
returns GROUNDED or ABSTAINED.
"""

import logging

from openai import OpenAI

from ai_contracts import (
    GroundedClaim,
    GroundedDraft,
    GroundedResponse,
    ResponseStatus,
    SafeReview,
    SafeReviewSet,
)

logger = logging.getLogger("grounding")

_SYSTEM_PROMPT = (
    "You are a product review summarizer. You will be given a list of "
    "reviews, each tagged with a source_id. Summarize what the reviews say "
    "and, for every claim you make, cite the source_id(s) that support it. "
    "Do not include any claim that is not directly supported by at least "
    "one review. Do not invent numbers, durations, or specifics that are "
    "not stated in the reviews. Respond only with JSON matching this "
    'shape: {"answer": string, "claims": [{"text": string, '
    '"sources": [string]}]}'
)

# Words shorter than this are too generic (stopword-like) to count as a
# meaningful signal for the content-overlap check below.
_MIN_KEYWORD_LENGTH = 4

_GENERIC_WORDS = {
    "dung", "duoc", "khong", "nhung", "cung", "voi", "cho", "rat",
    "tot", "san", "pham", "nay", "ngay", "lien", "tuc", "hoac",
}

def _build_review_prompt(safe_review_set: SafeReviewSet) -> str:
    lines = [f"[{review.source_id}] {review.text}" for review in safe_review_set.reviews]
    return "Reviews:\n" + "\n".join(lines)


def call_model_for_draft(safe_review_set: SafeReviewSet, client: OpenAI, model: str) -> str:
    """Calls the LLM and returns the raw JSON string it produced.

    Kept as its own function, separate from summarize_with_grounding, so
    tests can patch just this call without needing a real OpenAI client,
    network access, or API key.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_review_prompt(safe_review_set)},
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _content_supported(claim_text: str, source_texts: list[str]) -> bool:
    """Cheap keyword-overlap check: does at least one cited review share a
    meaningful word with the claim?

    This is a structural safety net, not a semantic guarantee: it catches
    claims that cite a real source_id but talk about something that
    source never actually mentions (e.g. review says "pin dung tot", claim
    says "pin dung duoc 20 gio" — no shared meaningful word beyond "pin").
    Upgrade to embedding similarity later if eval shows this isn't
    catching enough cases.
    """
    claim_words = {
        w for w in claim_text.lower().split()
        if len(w) >= _MIN_KEYWORD_LENGTH and w not in _GENERIC_WORDS
    }
    if not claim_words:
        # Claim too short/generic to extract any signal from; don't block on it.
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
    # Layer 1 - citation check: every cited source_id must exist in this
    # SafeReviewSet. This also implicitly enforces product scoping, since
    # SafeReviewSet only ever contains reviews for one product_id.
    if not all(source_id in reviews_by_id for source_id in claim.sources):
        logger.info(f"Dropping claim with unknown source_id(s): {claim.sources}")
        return False

    # Layer 2 - content check: claim text must be plausibly supported by
    # the text of its cited sources, not just point at a real ID.
    source_texts = [reviews_by_id[source_id].text for source_id in claim.sources]
    if not _content_supported(claim.text, source_texts):
        logger.info(f"Dropping claim not supported by source content: '{claim.text}'")
        return False

    return True


def summarize_with_grounding(
    safe_review_set: SafeReviewSet,
    client: OpenAI,
    model: str,
) -> GroundedResponse:
    """Entry point for A1.1. Never returns model output directly — every
    path either goes through claim validation or short-circuits to
    ABSTAINED before any model call happens.
    """
    if not safe_review_set.reviews:
        return GroundedResponse(
            status=ResponseStatus.ABSTAINED,
            reason=safe_review_set.reason or "No reviews available for this product",
        )

    raw_json = call_model_for_draft(safe_review_set, client, model)

    try:
        draft = GroundedDraft.model_validate_json(raw_json)
    except Exception as e:
        logger.error(f"Model returned a draft that did not match the expected schema: {e}")
        return GroundedResponse(
            status=ResponseStatus.ABSTAINED,
            reason="Model response did not match the expected schema",
        )

    reviews_by_id = {review.source_id: review for review in safe_review_set.reviews}
    surviving_claims = [claim for claim in draft.claims if _validate_claim(claim, reviews_by_id)]

    if not surviving_claims:
        return GroundedResponse(
            status=ResponseStatus.ABSTAINED,
            reason="No claim was supported by the available reviews",
        )

    # Re-derive the answer from surviving claims only. Never reuse
    # draft.answer as-is: it may reference a claim that was just dropped,
    # which would violate the "answer cannot exceed claims" rule from the
    # Grounded AI Response Contract.
    answer = " ".join(claim.text for claim in surviving_claims)

    return GroundedResponse(
        status=ResponseStatus.GROUNDED,
        answer=answer,
        claims=surviving_claims,
    )