#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Tests for grounding.py (A1.1), per the Day 2/3 implementation brief.

validate_grounded_summary is pure logic — it takes a GroundedDraft you
build by hand and a SafeReviewSet, no model or network involved at all.
generate_grounded_summary is the only function that touches the LLM, and
it's patched in the one test that exercises it, so the whole suite still
runs offline.
"""

from unittest.mock import patch

import pytest

from ai_contracts import (
    GroundedClaim,
    GroundedDraft,
    ResponseStatus,
    SafeReview,
    SafeReviewSet,
)
from grounding import (
    ABSTAIN_MESSAGE,
    GroundingMode,
    generate_grounded_summary,
    validate_grounded_summary,
)


def _reviews(*pairs):
    return [SafeReview(source_id=sid, text=text) for sid, text in pairs]


# --- Grounding: claim with a valid, content-matching source is kept -----

def test_claim_with_valid_source_is_kept():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    draft = GroundedDraft(
        answer="Pin dung tot",
        claims=[GroundedClaim(text="Pin dung tot", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.GROUNDED
    assert len(result.claims) == 1
    assert result.claims[0].sources == ["r1"]


# --- Citation: claim citing a source_id that doesn't exist gets dropped -

def test_claim_with_unknown_source_id_is_dropped():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    draft = GroundedDraft(
        answer="San pham co sac nhanh",
        claims=[GroundedClaim(text="San pham co sac nhanh", sources=["r99"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.claims == []
    assert result.reason == ABSTAIN_MESSAGE


# --- Citation: claim cites a real source but invents a number/duration -

def test_claim_with_fabricated_number_is_dropped():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    draft = GroundedDraft(
        answer="Pin dung duoc 20 gio",
        claims=[GroundedClaim(text="Pin dung duoc 20 gio lien tuc", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.ABSTAINED


# --- Citation: claim cites a real source but content isn't related ----

def test_claim_with_unrelated_content_is_dropped():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot")),
    )
    draft = GroundedDraft(
        answer="San pham bi loi man hinh thuong xuyen",
        claims=[GroundedClaim(text="San pham bi loi man hinh thuong xuyen", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.ABSTAINED


def test_bm25_keeps_claim_matching_a_single_cited_review():
    """A cited review must be scored within the full retrieved corpus."""
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(
            ("r1", "Manual controls are tricky at first but rewarding."),
            ("r2", "Lightweight telescope for camping trips."),
            ("r3", "Clear views of the moon and brighter planets."),
            ("r4", "Good value for beginner astronomers."),
        ),
    )
    draft = GroundedDraft(
        answer="Manual controls are tricky at first.",
        claims=[GroundedClaim(text="Manual controls are tricky at first.", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews, mode=GroundingMode.BM25)

    assert result.status == ResponseStatus.GROUNDED
    assert result.claims[0].sources == ["r1"]


def test_bm25_drops_claim_not_supported_by_its_cited_review():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(
            ("r1", "Manual controls are tricky at first but rewarding."),
            ("r2", "Lightweight telescope for camping trips."),
            ("r3", "Clear views of the moon and brighter planets."),
        ),
    )
    draft = GroundedDraft(
        answer="Battery life lasts all day.",
        claims=[GroundedClaim(text="Battery life lasts all day.", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews, mode=GroundingMode.BM25)

    assert result.status == ResponseStatus.ABSTAINED


# --- Abstention: model draft has no claim that survives validation ----

def test_all_claims_dropped_results_in_fixed_abstain_message():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot")),
    )
    draft = GroundedDraft(
        answer="khong lien quan",
        claims=[GroundedClaim(text="khong lien quan gi ca", sources=["r99"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.reason == ABSTAIN_MESSAGE
    assert result.claims == []


# --- flagd: even when llmInaccurateResponse forces a fabricated draft, -
# --- validate_grounded_summary still filters it out ---------------------

def test_validate_filters_fabricated_claim_from_inaccurate_flag():
    """Simulates product_reviews_server.py's llmInaccurateResponse flag
    path: the model is instructed to make the answer inaccurate, so
    generate_grounded_summary would return a claim with no basis in the
    real review text. validate_grounded_summary must not know or care
    that the flag was on — it filters this exactly like any other
    unsupported claim.
    """
    safe_reviews = SafeReviewSet(
        product_id="L9ECAV7KIM",
        reviews=_reviews(("r1", "May hoi nang nhung cam chac tay")),
    )
    draft = GroundedDraft(
        answer="San pham nay bi loi man hinh thuong xuyen",
        claims=[GroundedClaim(text="San pham bi loi man hinh thuong xuyen", sources=["r1"])],
    )

    result = validate_grounded_summary(draft, safe_reviews)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.claims == []


# --- generate_grounded_summary: patched, no real model/network needed -

def test_generate_grounded_summary_calls_instructor_client():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot")),
    )
    expected_draft = GroundedDraft(
        answer="Pin dung tot",
        claims=[GroundedClaim(text="Pin dung tot", sources=["r1"])],
    )

    with patch("grounding._get_client_and_model", return_value=(object(), "fake-model")), \
         patch("grounding.instructor.from_openai") as mock_from_openai:
        mock_from_openai.return_value.chat.completions.create.return_value = expected_draft
        result = generate_grounded_summary(safe_reviews, question="What do reviews say?")

    assert result == expected_draft
    # question is prompt input only; output contract remains GroundedDraft
    kwargs = mock_from_openai.return_value.chat.completions.create.call_args.kwargs
    user_content = kwargs["messages"][1]["content"]
    assert "What do reviews say?" in user_content


# --- Contract sanity: SafeReviewSet with duplicate source_id is invalid

def test_safe_review_set_rejects_duplicate_source_ids():
    with pytest.raises(Exception):
        SafeReviewSet(
            product_id="P001",
            reviews=_reviews(("r1", "text a"), ("r1", "text b")),
        )
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
