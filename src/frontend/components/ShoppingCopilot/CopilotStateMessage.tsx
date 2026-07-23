// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';
import { CopilotResponse } from '../../providers/ShoppingCopilot.provider';

const Banner = styled.div<{ status: string }>`
  padding: 16px 20px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  background-color: ${({ status }) => {
    switch (status) {
      case 'GROUNDED':
        return '#eff6ff';
      case 'NO_RESULTS':
        return '#fefce8';
      case 'ABSTAINED':
        return '#f0f9ff';
      case 'BLOCKED':
        return '#fef2f2';
      case 'FALLBACK':
        return '#f8fafc';
      default:
        return '#ffffff';
    }
  }};
  border: 1px solid
    ${({ status }) => {
    switch (status) {
      case 'GROUNDED':
        return '#bfdbfe';
      case 'NO_RESULTS':
        return '#fef08a';
      case 'ABSTAINED':
        return '#bae6fd';
      case 'BLOCKED':
        return '#fecaca';
      case 'FALLBACK':
        return '#e2e8f0';
      default:
        return '#e2e8f0';
    }
  }};
  color: #1e293b;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
`;

const TitleRow = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
`;

const Title = styled.div`
  font-weight: 700;
  font-size: 15px;
  color: #0f172a;
`;

const Content = styled.div`
  font-size: 14px;
  color: #475569;
  margin-bottom: 8px;
`;

const SuggestionsBox = styled.div`
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(0, 0, 0, 0.1);
  font-size: 13px;
  color: #64748b;
`;

const SuggestionTitle = styled.div`
  font-weight: 600;
  margin-bottom: 8px;
`;

const SuggestionList = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
`;

const SuggestionItem = styled.button`
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;

  &:hover {
    background: #eff6ff;
    color: #1d4ed8;
    border-color: #93c5fd;
  }
`;

interface Props {
  response: CopilotResponse;
  onSuggestionClick?: (text: string) => void;
}

export const CopilotStateMessage: React.FC<Props> = ({ response, onSuggestionClick }) => {
  const { status, reason } = response;

  if (status === 'GROUNDED') {
    if (!reason || !reason.trim()) return null;
    return (
      <Banner status="GROUNDED">
        <TitleRow>
          <Title>Shopping Assistant</Title>
        </TitleRow>
        <Content>{reason}</Content>
      </Banner>
    );
  }

  const getTitle = () => {
    switch (status) {
      case 'NO_RESULTS':
        return 'No Products Found';
      case 'ABSTAINED':
        return 'Additional Review Evidence Needed';
      case 'BLOCKED':
        return 'Request Out of Shopping Scope';
      case 'FALLBACK':
        return 'Assistant Temporarily Unavailable';
      default:
        return 'Assistant Notification';
    }
  };

  const getSuggestions = () => {
    switch (status) {
      case 'BLOCKED':
        return [
          'Show me products under $30',
          'Find accessories under $100',
          'Add the Lens Cleaning Kit to my cart',
        ];
      case 'NO_RESULTS':
        return [
          'Show me products under $30',
          'Find accessories under $100',
          'Add the Lens Cleaning Kit to my cart',
        ];
      default:
        return [];
    }
  };

  const suggestions = getSuggestions();

  return (
    <Banner status={status}>
      <TitleRow>
        <Title>{getTitle()}</Title>
      </TitleRow>
      <Content>{reason || 'Sorry, we could not complete your request. Please try a different query.'}</Content>

      {suggestions.length > 0 && (
        <SuggestionsBox>
          <SuggestionTitle>Suggested queries:</SuggestionTitle>
          <SuggestionList>
            {suggestions.map((s, idx) => (
              <SuggestionItem
                key={idx}
                type="button"
                onClick={() => onSuggestionClick && onSuggestionClick(s)}
              >
                {s}
              </SuggestionItem>
            ))}
          </SuggestionList>
        </SuggestionsBox>
      )}
    </Banner>
  );
};
