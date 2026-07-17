// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';
import { CopilotResponse } from '../../providers/ShoppingCopilot.provider';

const Banner = styled.div<{ status: string }>`
  padding: 18px 20px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 20px;
  background-color: ${({ status }) => {
    switch (status) {
      case 'NO_RESULTS':
        return '#fffbe6';
      case 'ABSTAINED':
        return '#f0f7ff';
      case 'BLOCKED':
        return '#fff1f0';
      case 'FALLBACK':
        return '#f5f5f5';
      default:
        return '#ffffff';
    }
  }};
  border: 1px solid
    ${({ status }) => {
      switch (status) {
        case 'NO_RESULTS':
          return '#ffe58f';
        case 'ABSTAINED':
          return '#91caff';
        case 'BLOCKED':
          return '#ffa39e';
        case 'FALLBACK':
          return '#d9d9d9';
        default:
          return '#e8e8e8';
      }
    }};
  color: #1f2937;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
`;

const TitleRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
`;

const Badge = styled.span<{ status: string }>`
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  background-color: ${({ status }) => {
    switch (status) {
      case 'NO_RESULTS':
        return '#faad14';
      case 'ABSTAINED':
        return '#1677ff';
      case 'BLOCKED':
        return '#ff4d4f';
      case 'FALLBACK':
        return '#8c8c8c';
      default:
        return '#595959';
    }
  }};
  color: #ffffff;
`;

const Title = styled.div`
  font-weight: 700;
  font-size: 15px;
  color: #111827;
`;

const Content = styled.div`
  font-size: 14px;
  color: #4b5563;
  margin-bottom: 10px;
`;

const SuggestionsBox = styled.div`
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(0, 0, 0, 0.1);
  font-size: 12px;
  color: #6b7280;
`;

const SuggestionTitle = styled.div`
  font-weight: 600;
  margin-bottom: 6px;
`;

const SuggestionList = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
`;

const SuggestionItem = styled.span`
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(0, 0, 0, 0.08);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: #374151;
`;

interface Props {
  response: CopilotResponse;
  onSuggestionClick?: (text: string) => void;
}

export const CopilotStateMessage: React.FC<Props> = ({ response, onSuggestionClick }) => {
  const { status, reason } = response;

  if (status === 'GROUNDED') return null;

  const getTitle = () => {
    switch (status) {
      case 'NO_RESULTS':
        return 'Product Not Found in Catalog';
      case 'ABSTAINED':
        return 'Insufficient Review Evidence';
      case 'BLOCKED':
        return 'Out of Scope Request';
      case 'FALLBACK':
        return 'Assistant Temporarily Unavailable';
      default:
        return 'Notification';
    }
  };

  const getSuggestions = () => {
    switch (status) {
      case 'BLOCKED':
        return [
          'Noise cancelling headphones under $100',
          'Add the best headphones to my cart',
          'How long does the battery last on these headphones?',
        ];
      case 'NO_RESULTS':
        return [
          'Headphones',
          'Solar System Color Imager',
          'Casual comfort style t-shirt',
        ];
      default:
        return [];
    }
  };

  const suggestions = getSuggestions();

  return (
    <Banner status={status}>
      <TitleRow>
        <Badge status={status}>{status}</Badge>
        <Title>{getTitle()}</Title>
      </TitleRow>
      <Content>{reason || 'Please try again with a different query.'}</Content>

      {suggestions.length > 0 && (
        <SuggestionsBox>
          <SuggestionTitle>Try asking about available products:</SuggestionTitle>
          <SuggestionList>
            {suggestions.map((s, idx) => (
              <SuggestionItem
                key={idx}
                style={{ cursor: onSuggestionClick ? 'pointer' : 'default' }}
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
