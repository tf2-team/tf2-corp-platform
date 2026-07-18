// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import * as S from './ProductReviews.styled';
import { useProductReview } from '../../providers/ProductReview.provider';
import { AiClaim, AiStructuredResponse, useAiAssistant } from '../../providers/ProductAIAssistant.provider';
import React, { useMemo, useState } from 'react';
import { CypressFields } from '../../utils/enums/CypressFields';
import { ProductReview } from '../../protos/demo';

const clamp = (n: number, min = 0, max = 5) => Math.max(min, Math.min(max, n));

const StarRating = ({ value, max = 5 }: { value: number; max?: number }) => {
  const rounded = clamp(Math.round(value), 0, max);
  const stars = Array.from({ length: max }, (_, i) => (i < rounded ? '★' : '☆')).join(' ');
  return <S.StarRating aria-label={`${value.toFixed(1)} out of ${max} stars`}>{stars}</S.StarRating>;
};

const scrollToReview = (sourceId: string) => {
  const el = document.getElementById(`review-${sourceId}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
};

/** Keep only source ids that resolve to a real review on the page. */
const resolveValidSources = (sourceIds: string[] | undefined, reviewsById: Map<string, ProductReview>) =>
  (sourceIds || []).filter((id) => reviewsById.has(id));

/**
 * Build a dense citation number map from claim order of first appearance.
 * Backend claims[].source_ids are unchanged; numbers are display-only.
 */
const buildCitationNumberMap = (claims: AiClaim[], reviewsById: Map<string, ProductReview>) => {
  const map = new Map<string, number>();
  let next = 1;
  for (const claim of claims) {
    for (const id of resolveValidSources(claim.source_ids, reviewsById)) {
      if (!map.has(id)) {
        map.set(id, next++);
      }
    }
  }
  return map;
};

const CitationMarker = ({
  sourceId,
  displayNumber,
  review,
}: {
  sourceId: string;
  displayNumber: number;
  review: ProductReview;
}) => (
  <S.InlineCitation
    type="button"
    aria-label={`Citation ${displayNumber}, review by ${review.username || 'unknown'}`}
    onClick={() => scrollToReview(sourceId)}
  >
    [{displayNumber}]
    <S.CitationTooltip role="tooltip">
      <S.CitationTooltipHeader>
        <StarRating value={Number(review.score) || 0} />
        <span>{review.username || 'Anonymous'}</span>
      </S.CitationTooltipHeader>
      <S.CitationTooltipBody>
        {review.description || 'No description provided.'}
      </S.CitationTooltipBody>
    </S.CitationTooltip>
  </S.InlineCitation>
);

/** Hướng C: one paragraph from claims + inline citations; no backend format change. */
const GroundedAnswerParagraph = ({
  claims,
  fallbackAnswer,
  reviewsById,
  citationNumbers,
}: {
  claims: AiClaim[];
  fallbackAnswer: string;
  reviewsById: Map<string, ProductReview>;
  citationNumbers: Map<string, number>;
}) => {
  if (!claims.length) {
    return <S.AiParagraph>{fallbackAnswer}</S.AiParagraph>;
  }

  return (
    <S.AiParagraph>
      {claims.map((claim, idx) => {
        const validSources = resolveValidSources(claim.source_ids, reviewsById);
        const text = (claim.text || '').trim();
        if (!text) return null;

        const needsSpace = idx > 0;
        return (
          <React.Fragment key={`claim-${idx}`}>
            {needsSpace ? ' ' : null}
            <span>{text}</span>
            {validSources.map((sourceId) => {
              const review = reviewsById.get(sourceId);
              const displayNumber = citationNumbers.get(sourceId);
              if (!review || displayNumber == null) return null;
              return (
                <CitationMarker
                  key={`${idx}-${sourceId}`}
                  sourceId={sourceId}
                  displayNumber={displayNumber}
                  review={review}
                />
              );
            })}
          </React.Fragment>
        );
      })}
    </S.AiParagraph>
  );
};

const SourcesPanel = ({
  citationNumbers,
  reviewsById,
}: {
  citationNumbers: Map<string, number>;
  reviewsById: Map<string, ProductReview>;
}) => {
  const entries = Array.from(citationNumbers.entries()).sort((a, b) => a[1] - b[1]);
  if (entries.length === 0) return null;

  return (
    <S.SourcesDropdown data-cy="AiSourcesDropdown">
      <S.SourcesSummary>
        View Sources ({entries.length} review{entries.length === 1 ? '' : 's'} cited)
      </S.SourcesSummary>
      <S.SourcesList>
        {entries.map(([sourceId, num]) => {
          const review = reviewsById.get(sourceId);
          if (!review) return null;
          return (
            <S.SourceItem
              key={sourceId}
              onClick={() => scrollToReview(sourceId)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  scrollToReview(sourceId);
                }
              }}
            >
              <S.SourceBadge>[{num}]</S.SourceBadge>
              <S.SourceContent>
                <S.SourceMeta>
                  <StarRating value={Number(review.score) || 0} />
                  <span>{review.username || 'Anonymous'}</span>
                </S.SourceMeta>
                <S.SourceSnippet>{review.description || 'No description provided.'}</S.SourceSnippet>
              </S.SourceContent>
            </S.SourceItem>
          );
        })}
      </S.SourcesList>
    </S.SourcesDropdown>
  );
};

const StructuredAiResponse = ({
  aiResponse,
  productReviews,
}: {
  aiResponse: AiStructuredResponse;
  productReviews: ProductReview[] | null;
}) => {
  const reviewsById = useMemo(() => {
    const map = new Map<string, ProductReview>();
    if (Array.isArray(productReviews)) {
      for (const review of productReviews) {
        if (review?.id) {
          map.set(String(review.id), review);
        }
      }
    }
    return map;
  }, [productReviews]);

  const claims = aiResponse.claims || [];
  const citationNumbers = useMemo(
    () => buildCitationNumberMap(claims, reviewsById),
    [claims, reviewsById]
  );

  const isGrounded = aiResponse.status === 'GROUNDED';

  // User-facing copy only — never surface internal status tags (BLOCKED, FALLBACK, …).
  const friendlyMessage =
    (aiResponse.answer || aiResponse.reason || '').trim() ||
    (aiResponse.status === 'FALLBACK'
      ? 'AI summary is temporarily unavailable.'
      : aiResponse.status === 'BLOCKED'
        ? 'Sorry, I cannot process this request.'
        : aiResponse.status === 'ABSTAINED'
          ? 'The current reviews do not provide enough information.'
          : 'Something went wrong. Please try again.');

  return (
    <S.AiResponseContainer>
      {isGrounded && claims.length > 0 ? (
        <>
          <GroundedAnswerParagraph
            claims={claims}
            fallbackAnswer={friendlyMessage}
            reviewsById={reviewsById}
            citationNumbers={citationNumbers}
          />
          <SourcesPanel citationNumbers={citationNumbers} reviewsById={reviewsById} />
        </>
      ) : (
        <S.AiReasonBlock>{friendlyMessage}</S.AiReasonBlock>
      )}
    </S.AiResponseContainer>
  );
};

const ProductReviews = () => {
  const { productReviews, loading, error, averageScore } = useProductReview();

  const average = useMemo(() => {
    if (!averageScore) return null;
    return clamp(Number(averageScore));
  }, [averageScore]);

  const distribution = useMemo(() => {
    if (!Array.isArray(productReviews)) return [0, 0, 0, 0, 0];
    const counts = [0, 0, 0, 0, 0];
    for (const r of productReviews) {
      const s = clamp(Math.round(Number(r.score)), 1, 5);
      counts[s - 1] += 1;
    }
    return counts;
  }, [productReviews]);

  const normalizedPercents = useMemo(() => {
    if (!Array.isArray(productReviews) || productReviews.length === 0) return [0, 0, 0, 0, 0];

    const raw = distribution.map((c) => (c / productReviews.length) * 100);
    const floored = raw.map((p) => Math.floor(p));
    const sumFloors = floored.reduce((a, b) => a + b, 0);
    let remainder = 100 - sumFloors;

    const order = raw
      .map((p, i) => ({ i, frac: p - Math.floor(p) }))
      .sort((a, b) => b.frac - a.frac);

    const final = floored.slice();
    for (let k = 0; k < remainder; k++) {
      final[order[k].i] += 1;
    }
    return final;
  }, [distribution, productReviews]);

  const [aiQuestion, setAiQuestion] = useState('');
  const { sendAiRequest, aiResponse, aiLoading, aiError, reset } = useAiAssistant();

  const handleAskAI = (questionOverride?: string) => {
    const q = (questionOverride ?? aiQuestion).trim();
    if (!q) return;
    reset();
    sendAiRequest({ question: q });
  };

  const handleQuickPrompt = (prompt: string) => {
    setAiQuestion(prompt);
    handleAskAI(prompt);
  };

  return (
    <S.ProductReviews aria-live="polite" data-cy={CypressFields.ProductReviews}>
      <S.AskAISection aria-label="Ask AI about this product" data-cy="AskAISection">
        <S.AskAIHeader>Ask AI About This Product</S.AskAIHeader>

        <S.AskAIInputRow>
          <S.AskAIInput
            id="ask-ai-input"
            type="text"
            placeholder="Type a question about the product…"
            value={aiQuestion}
            onChange={(e) => setAiQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !aiLoading && aiQuestion.trim()) {
                handleAskAI();
              }
            }}
            aria-label="Question to AI"
            data-cy="AskAIInput"
          />
          <S.AskAIButton
            type="button"
            onClick={() => handleAskAI()}
            disabled={aiLoading || !aiQuestion.trim()}
            aria-busy={aiLoading ? 'true' : 'false'}
            data-cy="AskAIButton"
          >
            {aiLoading ? 'Asking AI…' : 'Ask'}
          </S.AskAIButton>
        </S.AskAIInputRow>

        <S.AskAIControls>
          <S.QuickPromptButton
            type="button"
            onClick={() => handleQuickPrompt('Can you summarize the product reviews?')}
            data-cy="QuickPromptSummarize"
          >
            Can you summarize the product reviews?
          </S.QuickPromptButton>

          <S.QuickPromptButton
            type="button"
            onClick={() => handleQuickPrompt('What age(s) is this recommended for?')}
            data-cy="QuickPromptAges"
          >
            What age(s) is this recommended for?
          </S.QuickPromptButton>

          <S.QuickPromptButton
            type="button"
            onClick={() => handleQuickPrompt('Were there any negative reviews?')}
            data-cy="QuickPromptNegative"
          >
            Were there any negative reviews?
          </S.QuickPromptButton>
        </S.AskAIControls>

        {aiLoading && (
          <S.AIMessage data-cy="AILoading">Thinking… fetching product context and reviews.</S.AIMessage>
        )}

        {aiError && (
          <S.AIMessage role="alert" data-cy="AIError">
            {aiError.message ?? 'Sorry, something went wrong while asking AI.'}
          </S.AIMessage>
        )}

        {aiResponse && (
          <S.AIMessage aria-live="polite" data-cy="AIAnswer">
            <S.AskAIHeader>AI Response</S.AskAIHeader>
            {typeof aiResponse === 'string' ? (
              <S.AiReasonBlock>{aiResponse}</S.AiReasonBlock>
            ) : 'status' in aiResponse ? (
              <StructuredAiResponse aiResponse={aiResponse} productReviews={productReviews} />
            ) : (
              <S.AiReasonBlock>{(aiResponse as any).text}</S.AiReasonBlock>
            )}
          </S.AIMessage>
        )}
      </S.AskAISection>

      <S.TitleContainer>
        <S.Title>Customer Reviews</S.Title>
      </S.TitleContainer>

      {loading && <p>Loading product reviews…</p>}

      {!loading && error && <p>Could not load product reviews.</p>}

      {!loading && !error && Array.isArray(productReviews) && productReviews.length === 0 && (
        <p>No reviews yet.</p>
      )}

      {!loading && !error && (
        <>
          {average != null && (
            <S.SummaryCard>
              <S.AverageBlock>
                <S.AverageScoreBadge>{average.toFixed(1)}</S.AverageScoreBadge>
                <StarRating value={average} />
                <S.ScoreCount>
                  {Array.isArray(productReviews) ? `${productReviews.length} reviews` : ''}
                </S.ScoreCount>
              </S.AverageBlock>

              {Array.isArray(productReviews) && productReviews.length > 0 && (
                <S.ScoreDistribution>
                  {[1, 2, 3, 4, 5].map((score, idx) => {
                    const pct = normalizedPercents[idx];
                    return (
                      <S.ScoreRow key={`score-${score}`}>
                        <S.ScoreLabel>
                          {score} star{score > 1 ? 's' : ''}
                        </S.ScoreLabel>
                        <S.ScoreBar aria-label={`${score} stars: ${pct}%`}>
                          <S.ScoreBarFill style={{ width: `${pct}%` }} />
                        </S.ScoreBar>
                        <S.ScorePct>{pct}%</S.ScorePct>
                      </S.ScoreRow>
                    );
                  })}
                </S.ScoreDistribution>
              )}
            </S.SummaryCard>
          )}

          {Array.isArray(productReviews) && productReviews.length > 0 && (
            <S.ReviewsGrid as="ul">
              {productReviews.map((review, idx) => (
                <S.ReviewCard
                  as="li"
                  id={`review-${review.id || idx}`}
                  key={`${review.username}-${review.score}-${idx}`}
                >
                  <S.ReviewHeader>
                    <S.ReviewerName>{review.username}</S.ReviewerName>
                    <StarRating value={Number(review.score) || 0} />
                  </S.ReviewHeader>
                  <S.ReviewBody>{review.description || 'No description provided.'}</S.ReviewBody>
                </S.ReviewCard>
              ))}
            </S.ReviewsGrid>
          )}
        </>
      )}
    </S.ProductReviews>
  );
};

export default ProductReviews;
