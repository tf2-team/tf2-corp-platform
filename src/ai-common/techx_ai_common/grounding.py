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
from enum import Enum

class GroundingMode(str, Enum):
    SEMANTICS = "semantics"
    BM25 = "bm25"
    HYBRID = "hybrid"

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
from .bedrock import converse_json, is_bedrock_provider

logger = logging.getLogger("grounding")

# Fixed abstention message, per the Day 2/3 brief. Do not vary this string.
ABSTAIN_MESSAGE = "The current reviews do not provide enough information."

_SYSTEM_PROMPT = """\
You answer product-review questions using only the supplied reviews.

The supplied reviews may be a selected subset, not the complete set of product reviews.
Do not make absolute claims about all reviews or the product as a whole from this subset.
For absence or aggregate questions, use scoped wording such as "The supplied reviews do not mention X"; never say "There are no X reviews" unless the prompt explicitly states that the complete review set was provided.

Return exactly one JSON object. Do not use Markdown or add commentary:

{
  "answer": "short English answer",
  "claims": [
    {"text": "one factual claim in English", "sources": ["source_id"]}
  ]
}

Rules:
- Every factual statement in answer must also appear as one item in claims.
- Every claim must cite one or more source IDs from the supplied reviews.
- Use source IDs exactly as provided. Never invent a source ID.
- Do not put citations such as "[r1]" inside answer or claim text. Put source IDs only in sources.
- Do not add facts, numbers, comparisons, or opinions not stated in a review.
- If the supplied reviews do not support a scoped answer, return {"answer":"","claims":[]}.
- Write all text in English.

Example:

User question: Is this useful for cleaning lenses?

Reviews:
[r1] The lens kit cleans glasses well and includes a microfiber cloth.

JSON: {"answer":"The kit cleans glasses well and includes a microfiber cloth.","claims":[{"text":"The kit cleans glasses well and includes a microfiber cloth.","sources":["r1"]}]}
"""

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
    if is_bedrock_provider():
        return converse_json(GroundedDraft, _SYSTEM_PROMPT, _build_review_prompt(safe_reviews, question))

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


class GroundingChecker:
    _model = None

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            # Lazy load to prevent slow startup
            from sentence_transformers import SentenceTransformer
            # Using a fast, lightweight sentence transformer model
            cls._model = SentenceTransformer('all-MiniLM-L6-v2')
        return cls._model

    @classmethod
    def check_semantics(cls, claim_text: str, source_texts: list[str], threshold: float) -> bool:
        if not source_texts:
            return False
        model = cls._get_model()
        from sentence_transformers import util
        claim_emb = model.encode(claim_text, convert_to_tensor=True)
        source_embs = model.encode(source_texts, convert_to_tensor=True)
        cos_scores = util.cos_sim(claim_emb, source_embs)[0]
        return float(cos_scores.max()) >= threshold

    @classmethod
    def check_bm25(cls, claim_text: str, source_texts: list[str], threshold: float) -> bool:
        if not source_texts:
            return False
        from rank_bm25 import BM25Okapi
        tokenized_corpus = [doc.lower().split() for doc in source_texts]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = claim_text.lower().split()
        scores = bm25.get_scores(tokenized_query)
        return float(max(scores)) >= threshold


def _validate_claim(
    claim: GroundedClaim, 
    reviews_by_id: dict[str, SafeReview],
    mode: GroundingMode = GroundingMode.HYBRID,
    semantic_threshold: float = 0.65,
    bm25_threshold: float = 1.0,
) -> bool:
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

    # Layer 3 - Mode-specific content support check.
        
    sem_ok = False
    bm25_ok = False
    
    if mode in (GroundingMode.SEMANTICS, GroundingMode.HYBRID):
        sem_ok = GroundingChecker.check_semantics(claim.text, source_texts, semantic_threshold)
        if mode == GroundingMode.SEMANTICS and not sem_ok:
            logger.info(f"Dropping claim failing semantic check: '{claim.text}'")
            return False
            
    if mode in (GroundingMode.BM25, GroundingMode.HYBRID):
        bm25_ok = GroundingChecker.check_bm25(claim.text, source_texts, bm25_threshold)
        if mode == GroundingMode.BM25 and not bm25_ok:
            logger.info(f"Dropping claim failing BM25 check: '{claim.text}'")
            return False
            
    if mode == GroundingMode.HYBRID:
        if not (sem_ok or bm25_ok):
            logger.info(f"Dropping claim failing hybrid check (both semantic and BM25 failed): '{claim.text}'")
            return False

    return True


def validate_grounded_summary(
    draft: GroundedDraft,
    safe_reviews: SafeReviewSet,
    mode: GroundingMode = GroundingMode.HYBRID,
    semantic_threshold: float = 0.65,
    bm25_threshold: float = 1.0,
) -> GroundedResponse:
    """Never returns model output directly. Filters draft.claims against
    safe_reviews and re-derives the answer from surviving claims only.
    """
    reviews_by_id = {review.source_id: review for review in safe_reviews.reviews}
    surviving_claims = [
        claim for claim in draft.claims 
        if _validate_claim(claim, reviews_by_id, mode, semantic_threshold, bm25_threshold)
    ]

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
