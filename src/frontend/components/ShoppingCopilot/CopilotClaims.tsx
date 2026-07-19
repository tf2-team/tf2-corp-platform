// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
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

const ClaimItem = styled.div`
  font-size: 14px;
  line-height: 1.6;
  color: #334155;
  margin-bottom: 10px;

  &:last-child {
    margin-bottom: 0;
  }
`;

const CitationBadge = styled.span`
  display: inline-block;
  background-color: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  margin-left: 8px;
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
      <Header>Grounded Customer Review Insights</Header>
      {claims.map((claim, idx) => (
        <ClaimItem key={idx}>
          • {claim.text}
          {claim.sourceIds && claim.sourceIds.length > 0 && (
            <CitationBadge>
              Source: {claim.sourceIds.length} review{claim.sourceIds.length > 1 ? 's' : ''}
            </CitationBadge>
          )}
        </ClaimItem>
      ))}
    </Container>
  );
};
