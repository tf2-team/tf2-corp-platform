#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import pytest
from unittest.mock import patch, MagicMock
from techx_ai_common.contracts import SafeReviewSet, SafeReview
from techx_ai_common.retrieval import _estimate_adaptive_k, retrieve_relevant_reviews, tokenize


@patch("techx_ai_common.retrieval._get_model")
def test_retrieve_ranks_even_when_reviews_do_not_exceed_top_k(mock_get_model):
    reviews = [
        SafeReview(source_id="1", text="The screen is crisp and bright", score=5.0),
        SafeReview(source_id="2", text="Battery lasts all day", score=5.0),
        SafeReview(source_id="3", text="Battery drains quickly", score=2.0),
    ]
    safe_set = SafeReviewSet(product_id="P001", reviews=reviews)

    mock_model = MagicMock()
    mock_model.encode.side_effect = lambda text, **kwargs: text
    mock_get_model.return_value = mock_model

    import torch
    with patch("sentence_transformers.util.cos_sim", return_value=torch.tensor([[0.1, 0.9, 0.4]])):
        result = retrieve_relevant_reviews(safe_set, "How long does the battery last?", top_k=5)

    assert mock_get_model.called
    assert len(result.reviews) == 3
    assert [r.source_id for r in result.reviews] == ["2", "3", "1"]


def test_tokenize_handles_punctuation_stemming_and_negation():
    assert tokenize("This camera isn't easy-to-use, but connected quickly!") == [
        "camera", "isn't", "easy-to-us", "but", "connect", "quick",
    ]


@patch("techx_ai_common.retrieval._get_model", side_effect=RuntimeError("model unavailable"))
def test_retrieve_uses_bm25_when_dense_retrieval_fails(mock_get_model, caplog):
    reviews = [
        SafeReview(source_id="1", text="The screen is crisp", score=5.0),
        SafeReview(source_id="2", text="Battery lasts all day", score=5.0),
    ]

    result = retrieve_relevant_reviews(
        SafeReviewSet(product_id="P001", reviews=reviews),
        "How is the battery?",
        top_k=1,
    )

    assert mock_get_model.called
    assert [review.source_id for review in result.reviews] == ["2"]
    assert "retrieval_mode=bm25_only" in caplog.text


def test_adaptive_k_uses_largest_similarity_gap_but_keeps_minimum_evidence():
    assert _estimate_adaptive_k([0.91, 0.77, 0.24, 0.18, 0.15], max_k=5) == 3


def test_adaptive_k_keeps_max_evidence_when_similarity_is_flat():
    assert _estimate_adaptive_k([0.34, 0.34, 0.34, 0.34, 0.34], max_k=5) == 5


@patch("techx_ai_common.retrieval._get_model")
def test_retrieve_with_rrf_ranking(mock_get_model):
    # Mock SentenceTransformer encoding
    mock_model = MagicMock()
    mock_get_model.return_value = mock_model
    
    # We have 4 reviews
    reviews = [
        SafeReview(source_id="101", text="Long battery life and cheap", score=5.0),
        SafeReview(source_id="102", text="Beautiful design but very expensive", score=4.0),
        SafeReview(source_id="103", text="Terrible sound, would not recommend", score=1.0),
        SafeReview(source_id="104", text="Fast shipping but product has bad quality", score=2.0),
    ]
    safe_set = SafeReviewSet(product_id="P001", reviews=reviews)
    
    import torch
    
    # Mocking SentenceTransformer model encoding output
    mock_model.encode.side_effect = lambda text, **kwargs: text
    
    # Mocking util.cos_sim to return a tensor of scores
    mock_cos_sim = MagicMock()
    mock_cos_sim.return_value = torch.tensor([[0.85, 0.40, 0.10, 0.20]])
    
    with patch("sentence_transformers.util.cos_sim", mock_cos_sim):
        # Query does not contain the word "review"
        result = retrieve_relevant_reviews(safe_set, "How long does the battery last on this product?", top_k=2)
        
        # Result should have top 2 reviews
        assert len(result.reviews) == 2
        # Review 101 must be first (rank 1 in both BERT and BM25)
        assert result.reviews[0].source_id == "101"
        assert result.reviews[1].source_id == "102"
