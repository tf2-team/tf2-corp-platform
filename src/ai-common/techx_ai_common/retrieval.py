#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import logging
import re
from statistics import fmean, pstdev

from nltk.stem import SnowballStemmer
from rank_bm25 import BM25Okapi
from .contracts import SafeReviewSet

logger = logging.getLogger("retrieval")

_model = None
_STEMMER = SnowballStemmer("english")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
# Keep negation and shopping qualifiers such as "under" and "too": they can
# reverse or materially change review meaning.
_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
    "for", "from", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "with",
})
_MIN_DYNAMIC_K = 3

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


def tokenize(text: str) -> list[str]:
    """Normalize English review text for the BM25 branch without external corpora."""
    return [
        _STEMMER.stem(token)
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOP_WORDS
    ]


def _rank(scores: list[float], reviews) -> dict[int, int]:
    ranked = sorted(
        enumerate(scores),
        key=lambda item: (-item[1], reviews[item[0]].source_id),
    )
    return {idx: rank for rank, (idx, _) in enumerate(ranked, 1)}


def _estimate_adaptive_k(scores: list[float], max_k: int) -> int:
    """Keep more evidence unless score gaps show a focused question."""
    upper_bound = min(max_k, len(scores))
    if upper_bound <= _MIN_DYNAMIC_K:
        return upper_bound

    sorted_scores = sorted(scores, reverse=True)[:upper_bound]
    gaps = [
        sorted_scores[index] - sorted_scores[index + 1]
        for index in range(len(sorted_scores) - 1)
    ]
    largest_gap = max(gaps)
    dynamic_cutoff = fmean(gaps) + pstdev(gaps)
    if largest_gap <= dynamic_cutoff + 1e-6:
        return upper_bound

    return min(upper_bound, max(_MIN_DYNAMIC_K, gaps.index(largest_gap) + 1))


def retrieve_relevant_reviews(safe_reviews: SafeReviewSet, question: str, top_k: int = 5) -> SafeReviewSet:
    """Retrieves top_k relevant reviews for a given question using a hybrid search of
    BERT (dense semantic) and BM25 (sparse lexical) combined using Reciprocal Rank Fusion (RRF).
    """
    if not safe_reviews.reviews or top_k <= 0:
        return safe_reviews

    reviews_list = safe_reviews.reviews
    texts = [r.text for r in reviews_list]
    dense_scores = None
    bm25_scores = None

    # 1. BERT (Dense Retrieval)
    try:
        model = _get_model()
        from sentence_transformers import util

        query_emb = model.encode(question, convert_to_tensor=True)
        doc_embs = model.encode(texts, convert_to_tensor=True)
        cos_scores = util.cos_sim(query_emb, doc_embs)[0]
        dense_scores = cos_scores.tolist() if hasattr(cos_scores, "tolist") else list(cos_scores)
    except Exception as e:
        logger.warning("retrieval_mode=bm25_only dense_error=%s", type(e).__name__)

    # 2. BM25 (Sparse Retrieval)
    try:
        tokenized_corpus = [tokenize(doc) for doc in texts]
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(tokenize(question))
        bm25_scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)
        if not any(bm25_scores):
            query_tokens = set(tokenize(question))
            bm25_scores = [
                len(query_tokens.intersection(tokenize(review.text)))
                for review in reviews_list
            ]
    except Exception as e:
        logger.warning("retrieval_mode=dense_only bm25_error=%s", type(e).__name__)

    if dense_scores is None and bm25_scores is None:
        logger.error("retrieval_mode=unranked both_rankers_failed=true")
        return SafeReviewSet(
            product_id=safe_reviews.product_id,
            reviews=reviews_list[:top_k],
            reason=safe_reviews.reason,
        )

    modes = []
    if dense_scores is not None:
        modes.append("dense")
    if bm25_scores is not None:
        modes.append("bm25")
    adaptive_k = _estimate_adaptive_k(dense_scores or bm25_scores, top_k)
    logger.info("retrieval_mode=%s adaptive_k=%s", "+".join(modes), adaptive_k)

    # 3. Reciprocal Rank Fusion (RRF)
    # RRF Score formula: RRF(d) = sum(1 / (k + rank_i(d))) where k = 60
    dense_ranks = _rank(dense_scores, reviews_list) if dense_scores is not None else {}
    bm25_ranks = _rank(bm25_scores, reviews_list) if bm25_scores is not None else {}
    rrf_scores = []
    for idx in range(len(reviews_list)):
        rrf_score = sum(
            1.0 / (60.0 + ranks[idx])
            for ranks in (dense_ranks, bm25_ranks)
            if ranks
        )
        rrf_scores.append((idx, rrf_score))

    rrf_ranked = sorted(
        rrf_scores,
        key=lambda item: (-item[1], reviews_list[item[0]].source_id),
    )

    top_k_indices = [idx for idx, _ in rrf_ranked[:adaptive_k]]
    top_k_reviews = [reviews_list[idx] for idx in top_k_indices]

    logger.info(
        "Retrieved top %s reviews out of %s using RRF",
        len(top_k_reviews),
        len(reviews_list),
    )
    return SafeReviewSet(
        product_id=safe_reviews.product_id,
        reviews=top_k_reviews,
        reason=safe_reviews.reason
    )
