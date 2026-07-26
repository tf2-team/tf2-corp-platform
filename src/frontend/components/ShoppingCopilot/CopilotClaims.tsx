// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React, { useMemo } from 'react';
import styled from 'styled-components';
import { CopilotClaim, CopilotSource } from '../../providers/ShoppingCopilot.provider';

const Container = styled.div`
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 4px solid #2563eb;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
`;

const Header = styled.h4`
  font-size: 14.5px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px 0;
  display: flex;
  align-items: center;
  gap: 8px;
`;

const Paragraph = styled.p`
  margin: 0 0 12px 0;
  line-height: 1.7;
  color: #334155;
  font-size: 14px;
`;

const InlineCitation = styled.span`
  position: relative;
  display: inline;
  margin: 0 2px;
  padding: 0 4px;
  border-radius: 3px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  vertical-align: super;
  cursor: default;
`;

const SourcesDropdown = styled.details`
  margin-top: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;

  &[open] summary {
    border-bottom: 1px solid #e2e8f0;
  }
`;

const SourcesSummary = styled.summary`
  list-style: none;
  cursor: pointer;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #2563eb;
  user-select: none;

  &::-webkit-details-marker {
    display: none;
  }

  &::before {
    content: '▶';
    display: inline-block;
    margin-right: 8px;
    font-size: 10px;
    transition: transform 0.12s ease;
  }

  details[open] > &::before {
    transform: rotate(90deg);
  }
`;

const SourcesList = styled.ul`
  list-style: none;
  margin: 0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const SourceItem = styled.li`
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;

  &:hover {
    background: #f8fafc;
  }
`;

const SourceBadge = styled.span`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 999px;
  background: #2563eb;
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
`;

const SourceContent = styled.div`
  min-width: 0;
`;

const SourceMeta = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
`;

const StarRatingSpan = styled.span`
  color: #f59e0b;
`;

const SourceSnippet = styled.div`
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.4;
`;

interface Props {
  claims: CopilotClaim[];
  sources: CopilotSource[];
}

const renderStars = (score: number = 5) => {
  const rounded = Math.max(0, Math.min(5, Math.round(score)));
  return Array.from({ length: 5 }, (_, i) => (i < rounded ? '★' : '☆')).join('');
};

export const CopilotClaims: React.FC<Props> = ({ claims, sources }) => {
  if (!claims || claims.length === 0) return null;

  const sourcesById = useMemo(() => {
    const map = new Map<string, CopilotSource>();
    if (Array.isArray(sources)) {
      for (const s of sources) {
        map.set(s.sourceId, s);
      }
    }
    return map;
  }, [sources]);

  const { citationMap, citedSourceIds } = useMemo(() => {
    const map = new Map<string, number>();
    const order: string[] = [];
    let counter = 1;

    for (const claim of claims) {
      if (claim.sourceIds) {
        for (const sid of claim.sourceIds) {
          if (!map.has(sid)) {
            map.set(sid, counter++);
            order.push(sid);
          }
        }
      }
    }
    return { citationMap: map, citedSourceIds: order };
  }, [claims]);

  return (
    <Container>
      <Header>Grounded Customer Review Insights</Header>
      <Paragraph>
        {claims.map((claim, idx) => {
          const text = (claim.text || '').trim();
          if (!text) return null;

          return (
            <React.Fragment key={idx}>
              {idx > 0 ? ' ' : ''}
              <span>{text}</span>
              {claim.sourceIds &&
                claim.sourceIds.map((sid) => {
                  const num = citationMap.get(sid);
                  if (num == null) return null;
                  return <InlineCitation key={sid}>[{num}]</InlineCitation>;
                })}
            </React.Fragment>
          );
        })}
      </Paragraph>

      {citedSourceIds.length > 0 && (
        <SourcesDropdown data-cy="CopilotSourcesDropdown">
          <SourcesSummary>
            View Sources ({citedSourceIds.length} review
            {citedSourceIds.length === 1 ? '' : 's'} cited)
          </SourcesSummary>
          <SourcesList>
            {citedSourceIds.map((sid) => {
              const num = citationMap.get(sid);
              const src = sourcesById.get(sid);
              return (
                <SourceItem key={sid}>
                  <SourceBadge>[{num}]</SourceBadge>
                  <SourceContent>
                    <SourceMeta>
                      <StarRatingSpan>{renderStars(src?.score ?? 5)}</StarRatingSpan>
                      <span>{src?.username || 'Anonymous'}</span>
                    </SourceMeta>
                    <SourceSnippet>
                      {src?.description || 'No detailed review snippet available.'}
                    </SourceSnippet>
                  </SourceContent>
                </SourceItem>
              );
            })}
          </SourcesList>
        </SourcesDropdown>
      )}
    </Container>
  );
};
