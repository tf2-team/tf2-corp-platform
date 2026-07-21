# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import pytest
from unittest.mock import patch, MagicMock
from techx_ai_common.contracts import SafeReviewSet, SafeReview
from techx_ai_common.retrieval import retrieve_relevant_reviews

def test_retrieve_bypass_if_few_reviews():
    # Create a SafeReviewSet with 3 reviews
    reviews = [
        SafeReview(source_id="1", text="Excellent product", score=5.0),
        SafeReview(source_id="2", text="Okay product", score=3.0),
        SafeReview(source_id="3", text="Terrible product", score=1.0),
    ]
    safe_set = SafeReviewSet(product_id="P001", reviews=reviews)
    
    # top_k = 5, which is > len(reviews)
    result = retrieve_relevant_reviews(safe_set, "good battery", top_k=5)
    
    # Should bypass and return all 3 reviews in original order
    assert len(result.reviews) == 3
    assert [r.source_id for r in result.reviews] == ["1", "2", "3"]

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
        # We query with "cheap battery"
        result = retrieve_relevant_reviews(safe_set, "cheap battery", top_k=2)
        
        # Result should have top 2 reviews
        assert len(result.reviews) == 2
        # Review 101 must be first (rank 1 in both BERT and BM25)
        assert result.reviews[0].source_id == "101"
        # Review 102 must be second (rank 2 in BERT, even though 0 in BM25, its RRF is higher than 104 and 103)
        # RRF calculations:
        # 101: BERT rank 1, BM25 rank 1 -> RRF = 1/61 + 1/61 = 0.0327
        # 102: BERT rank 2, BM25 rank 2 -> RRF = 1/62 + 1/62 = 0.0322
        # 104: BERT rank 3, BM25 rank 2 -> RRF = 1/63 + 1/62 = 0.0320
        # 103: BERT rank 4, BM25 rank 2 -> RRF = 1/64 + 1/62 = 0.0317
        assert result.reviews[1].source_id == "102"
