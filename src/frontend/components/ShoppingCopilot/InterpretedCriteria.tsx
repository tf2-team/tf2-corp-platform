// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';

const Container = styled.div`
  background-color: #f0f4ff;
  border: 1px solid ${({ theme }) => theme.colors.lightBorderGray};
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
`;

const Badge = styled.span`
  background-color: ${({ theme }) => theme.colors.otelBlue};
  color: ${({ theme }) => theme.colors.white};
  font-size: 12px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 4px;
  text-transform: uppercase;
`;

const CriteriaText = styled.span`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.textGray};
  font-weight: 500;
`;

interface Props {
  criteria: string;
}

export const InterpretedCriteria: React.FC<Props> = ({ criteria }) => {
  if (!criteria) return null;

  return (
    <Container>
      <Badge>AI Intent</Badge>
      <CriteriaText>{criteria}</CriteriaText>
    </Container>
  );
};
