// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React, { useState, useEffect } from 'react';
import styled from 'styled-components';
import { useShoppingCopilot } from '../../providers/ShoppingCopilot.provider';

const Container = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  margin-bottom: 24px;
`;

const Form = styled.form`
  display: flex;
  gap: 12px;
  width: 100%;

  @media (max-width: 600px) {
    flex-direction: column;
  }
`;

const InputWrapper = styled.div`
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
`;

const Input = styled.input`
  width: 100%;
  padding: 14px 40px 14px 18px;
  border-radius: 10px;
  border: 1px solid ${({ theme }) => theme.colors.lightBorderGray};
  background-color: ${({ theme }) => theme.colors.white};
  color: ${({ theme }) => theme.colors.textGray};
  font-size: 15px;
  outline: none;
  transition: all 0.2s ease;

  &:focus {
    border-color: ${({ theme }) => theme.colors.otelBlue};
    box-shadow: 0 0 0 3px rgba(82, 98, 168, 0.15);
  }
`;

const ClearButton = styled.button`
  position: absolute;
  right: 12px;
  background: none;
  border: none;
  color: #9ca3af;
  font-size: 14px;
  cursor: pointer;
  padding: 4px;

  &:hover {
    color: #4b5563;
  }
`;

const SubmitButton = styled.button`
  padding: 14px 28px;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: ${({ theme }) => theme.colors.white};
  font-weight: 600;
  font-size: 15px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;

  &:hover {
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    transform: translateY(-1px);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
`;

const SamplePromptContainer = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
`;

const SampleLabel = styled.span`
  font-size: 12px;
  color: #6b7280;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const SamplePill = styled.button`
  background-color: #f3f4f6;
  border: 1px solid #e5e7eb;
  color: #374151;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background-color: #2563eb;
    color: #ffffff;
    border-color: #2563eb;
    transform: translateY(-1px);
  }
`;

const SAMPLE_PROMPTS = [
  'Noise cancelling headphones under $100',
  'Casual comfort style t-shirt',
  'How long does the battery last on these headphones?',
  'Add the best headphones to my cart',
];

interface CopilotInputProps {
  externalQuery?: string;
}

export const CopilotInput: React.FC<CopilotInputProps> = ({ externalQuery }) => {
  const [query, setQuery] = useState('');
  const { searchCopilot, loading } = useShoppingCopilot();

  useEffect(() => {
    if (externalQuery) {
      setQuery(externalQuery);
    }
  }, [externalQuery]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      searchCopilot(query.trim());
    }
  };

  const handleSampleClick = (prompt: string) => {
    setQuery(prompt);
    searchCopilot(prompt);
  };

  return (
    <Container>
      <Form onSubmit={handleSubmit}>
        <InputWrapper>
          <Input
            type="text"
            placeholder="Ask Shopping Copilot in English (e.g., Headphones under $100)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
          />
          {query && (
            <ClearButton type="button" onClick={() => setQuery('')}>
              ✕
            </ClearButton>
          )}
        </InputWrapper>
        <SubmitButton type="submit" disabled={loading || !query.trim()}>
          {loading ? 'Searching...' : 'AI Search'}
        </SubmitButton>
      </Form>

      <SamplePromptContainer>
        <SampleLabel>Suggestions:</SampleLabel>
        {SAMPLE_PROMPTS.map((prompt, idx) => (
          <SamplePill
            key={idx}
            type="button"
            onClick={() => handleSampleClick(prompt)}
            disabled={loading}
          >
            {prompt}
          </SamplePill>
        ))}
      </SamplePromptContainer>
    </Container>
  );
};
