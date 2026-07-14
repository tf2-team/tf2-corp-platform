"""Tests for grounding.py (A1.1).

These tests never call a real LLM. call_model_for_draft is patched in every
test that needs a model response, so the whole suite runs offline and fast.
"""

from unittest.mock import patch

import pytest

from ai_contracts import ResponseStatus, SafeReview, SafeReviewSet
from grounding import summarize_with_grounding

FAKE_CLIENT = object()  # never actually called; call_model_for_draft is patched
FAKE_MODEL = "fake-model"


def _reviews(*pairs):
    """Shorthand: _reviews(("r1", "Pin dung tot"), ("r2", "May hoi nang"))"""
    return [SafeReview(source_id=sid, text=text) for sid, text in pairs]


# --- Grounding: claim with a valid, content-matching source is kept -----

def test_claim_with_valid_source_is_kept():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    mock_draft = (
        '{"answer": "Pin dung tot",'
        ' "claims": [{"text": "Pin dung tot", "sources": ["r1"]}]}'
    )

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.GROUNDED
    assert len(result.claims) == 1
    assert result.claims[0].sources == ["r1"]


# --- Citation: claim citing a source_id that doesn't exist gets dropped -

def test_claim_with_unknown_source_id_is_dropped():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    mock_draft = (
        '{"answer": "San pham co sac nhanh",'
        ' "claims": [{"text": "San pham co sac nhanh", "sources": ["r99"]}]}'
    )

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.claims == []
    assert result.reason


# --- Citation: claim cites a real source_id but content doesn't match --

def test_claim_with_unsupported_content_is_dropped():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot, dung ca ngay khong het")),
    )
    # r1 exists, but nothing in its text supports a specific "20 gio" claim
    mock_draft = (
        '{"answer": "Pin dung duoc 20 gio",'
        ' "claims": [{"text": "Pin dung duoc hai muoi gio lien tuc", "sources": ["r1"]}]}'
    )

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.ABSTAINED


# --- Abstention: empty SafeReviewSet short-circuits, no model call -----

def test_empty_review_set_abstains_without_calling_model():
    safe_reviews = SafeReviewSet(product_id="P001", reviews=[], reason="No reviews found")

    with patch("grounding.call_model_for_draft") as mock_call:
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)
        mock_call.assert_not_called()

    assert result.status == ResponseStatus.ABSTAINED
    assert result.reason == "No reviews found"


# --- Abstention: model returns a schema that doesn't match GroundedDraft

def test_malformed_model_output_abstains():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot")),
    )
    mock_draft = "this is not valid json at all"

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.ABSTAINED


# --- Abstention: every claim gets dropped -> whole response abstains ---

def test_all_claims_dropped_results_in_abstention():
    safe_reviews = SafeReviewSet(
        product_id="P001",
        reviews=_reviews(("r1", "Pin dung tot")),
    )
    mock_draft = (
        '{"answer": "khong lien quan",'
        ' "claims": [{"text": "khong lien quan gi ca", "sources": ["r99"]}]}'
    )

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.claims == []


# --- flagd: even when llmInaccurateResponse is simulated (model forced -
# --- to fabricate an answer), grounding still filters the bad claim ----

def test_grounding_filters_fabricated_claim_from_inaccurate_flag():
    """Simulates product_reviews_server.py's llmInaccurateResponse flag
    path: the model is instructed to make the answer inaccurate, so it
    fabricates a claim not supported by any real review. grounding.py
    must not know or care that the flag was on — it should filter this
    exactly like any other unsupported claim.
    """
    safe_reviews = SafeReviewSet(
        product_id="L9ECAV7KIM",
        reviews=_reviews(("r1", "May hoi nang nhung cam chac tay")),
    )
    # Model was told to "make the answer inaccurate" and invents a claim
    # with no basis in the actual review text.
    mock_draft = (
        '{"answer": "San pham nay bi loi man hinh thuong xuyen",'
        ' "claims": [{"text": "San pham bi loi man hinh thuong xuyen", "sources": ["r1"]}]}'
    )

    with patch("grounding.call_model_for_draft", return_value=mock_draft):
        result = summarize_with_grounding(safe_reviews, FAKE_CLIENT, FAKE_MODEL)

    assert result.status == ResponseStatus.ABSTAINED
    assert result.claims == []


# --- Contract sanity: SafeReviewSet with duplicate source_id is invalid
# (schema-level check already enforced by ai_contract.py; verifying here
# so a future contract change that weakens this doesn't go unnoticed)

def test_safe_review_set_rejects_duplicate_source_ids():
    with pytest.raises(Exception):
        SafeReviewSet(
            product_id="P001",
            reviews=_reviews(("r1", "text a"), ("r1", "text b")),
        )
