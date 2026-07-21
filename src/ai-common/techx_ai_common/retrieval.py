# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import logging
from rank_bm25 import BM25Okapi
from .contracts import SafeReviewSet, SafeReview

logger = logging.getLogger("retrieval")

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def retrieve_relevant_reviews(safe_reviews: SafeReviewSet, question: str, top_k: int = 5) -> SafeReviewSet:
    """Retrieves top_k relevant reviews for a given question using a hybrid search of
    BERT (dense semantic) and BM25 (sparse lexical) combined using Reciprocal Rank Fusion (RRF).
    """
    if not safe_reviews.reviews or len(safe_reviews.reviews) <= top_k:
        logger.info(
            f"Bypassing retrieval search because review count ({len(safe_reviews.reviews)}) is <= top_k ({top_k})"
        )
        return safe_reviews

    reviews_list = safe_reviews.reviews
    texts = [r.text for r in reviews_list]

    # 1. BERT (Dense Retrieval)
    try:
        model = _get_model()
        from sentence_transformers import util
        import torch
        
        query_emb = model.encode(question, convert_to_tensor=True)
        doc_embs = model.encode(texts, convert_to_tensor=True)
        cos_scores = util.cos_sim(query_emb, doc_embs)[0]
        
        # Convert to CPU list if it is a tensor
        if hasattr(cos_scores, "tolist"):
            cos_scores = cos_scores.tolist()
        else:
            cos_scores = list(cos_scores)
            
        bert_ranked = sorted(enumerate(cos_scores), key=lambda x: x[1], reverse=True)
        bert_ranks = {idx: rank for rank, (idx, _) in enumerate(bert_ranked, 1)}
    except Exception as e:
        logger.error(f"BERT dense encoding failed: {e}. Falling back to flat ranking for BERT.")
        # Fallback to order of appearance in case of transformer failure
        bert_ranks = {idx: idx + 1 for idx in range(len(reviews_list))}

    # 2. BM25 (Sparse Retrieval)
    try:
        tokenized_corpus = [doc.lower().split() for doc in texts]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = question.lower().split()
        bm25_scores = bm25.get_scores(tokenized_query)
        
        if hasattr(bm25_scores, "tolist"):
            bm25_scores = bm25_scores.tolist()
        else:
            bm25_scores = list(bm25_scores)
            
        bm25_ranked = sorted(enumerate(bm25_scores), key=lambda x: x[1], reverse=True)
        bm25_ranks = {idx: rank for rank, (idx, _) in enumerate(bm25_ranked, 1)}
    except Exception as e:
        logger.error(f"BM25 sparse ranking failed: {e}. Falling back to flat ranking for BM25.")
        bm25_ranks = {idx: idx + 1 for idx in range(len(reviews_list))}

    # 3. Reciprocal Rank Fusion (RRF)
    # RRF Score formula: RRF(d) = sum(1 / (k + rank_i(d))) where k = 60
    rrf_scores = []
    for idx in range(len(reviews_list)):
        r_bert = bert_ranks[idx]
        r_bm25 = bm25_ranks[idx]
        rrf_score = 1.0 / (60.0 + r_bert) + 1.0 / (60.0 + r_bm25)
        rrf_scores.append((idx, rrf_score))

    # Sort by RRF score descending
    rrf_ranked = sorted(rrf_scores, key=lambda x: x[1], reverse=True)

    # Slice to top_k
    top_k_indices = [idx for idx, _ in rrf_ranked[:top_k]]
    top_k_reviews = [reviews_list[idx] for idx in top_k_indices]

    logger.info(
        f"Successfully retrieved top {len(top_k_reviews)} reviews out of {len(reviews_list)} using BERT+BM25+RRF"
    )
    return SafeReviewSet(
        product_id=safe_reviews.product_id,
        reviews=top_k_reviews,
        reason=safe_reviews.reason
    )
