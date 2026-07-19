// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';
import { CopilotClaim, CopilotSource } from '../../providers/ShoppingCopilot.provider';

const Container = styled.div`
  background: #fdfdfd;
  border: 1px solid ${({ theme }) => theme.colors.lightBorderGray};
  border-left: 4px solid ${({ theme }) => theme.colors.otelYellow};
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;
`;

const Header = styled.h4`
  font-size: 15px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.textGray};
  margin: 0 0 12px 0;
  display: flex;
  align-items: center;
  gap: 8px;
`;

const ClaimItem = styled.div`
  font-size: 14px;
  line-height: 1.5;
  color: ${({ theme }) => theme.colors.textGray};
  margin-bottom: 10px;

  &:last-child {
    margin-bottom: 0;
  }
`;

const CitationBadge = styled.span`
  display: inline-block;
  background-color: ${({ theme }) => theme.colors.backgroundGray};
  color: ${({ theme }) => theme.colors.otelBlue};
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
  vertical-align: middle;
`;

interface Props {
  claims: CopilotClaim[];
  sources: CopilotSource[];
}

export const CopilotClaims: React.FC<Props> = ({ claims }) => {
  if (!claims || claims.length === 0) return null;

  return (
    <Container>
      <Header>User Reviews (Grounded Review Q&A)</Header>
      {claims.map((claim, idx) => (
        <ClaimItem key={idx}>
          • {claim.text}
          {claim.sourceIds && claim.sourceIds.length > 0 && (
            <CitationBadge>
              [Source: {claim.sourceIds.length} review{claim.sourceIds.length > 1 ? 's' : ''}]
            </CitationBadge>
          )}
        </ClaimItem>
      ))}
    </Container>
  );
};
