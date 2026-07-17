// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';
import { useQueryClient } from '@tanstack/react-query';
import { useShoppingCopilot } from '../../providers/ShoppingCopilot.provider';

const Container = styled.div`
  background: #fff8e7;
  border: 1px solid ${({ theme }) => theme.colors.otelYellow};
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;

  @media (max-width: 600px) {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
`;

const Message = styled.div`
  font-size: 14px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.textGray};
`;

const ButtonGroup = styled.div`
  display: flex;
  gap: 8px;
  align-items: center;
`;

const Button = styled.button`
  padding: 10px 20px;
  background-color: ${({ theme }) => theme.colors.otelYellow};
  color: ${({ theme }) => theme.colors.textGray};
  font-weight: 700;
  font-size: 14px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: opacity 0.2s;

  &:hover {
    opacity: 0.9;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;

const CancelButton = styled.button`
  padding: 10px 16px;
  background-color: transparent;
  color: ${({ theme }) => theme.colors.textGray};
  font-weight: 600;
  font-size: 14px;
  border: 1px solid ${({ theme }) => theme.colors.lightBorderGray};
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    background-color: #e4e6eb;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
`;

const AlertMessage = styled.div<{ success?: boolean }>`
  margin-top: 10px;
  padding: 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  background-color: ${({ success }) => (success ? '#e6f4ea' : '#fce8e6')};
  color: ${({ success }) => (success ? '#137333' : '#c5221f')};
`;

interface Props {
  pendingToken: string;
}

export const CopilotCartConfirm: React.FC<Props> = ({ pendingToken }) => {
  const { confirmCartAction, cancelCartAction, confirmLoading, confirmSuccess, confirmMessage } =
    useShoppingCopilot();
  const queryClient = useQueryClient();

  if (!pendingToken) return null;

  const handleConfirm = async () => {
    await confirmCartAction(pendingToken);
    queryClient.invalidateQueries({ queryKey: ['cart'] });
  };

  return (
    <div>
      <Container>
        <Message>
          AI suggests adding this item to your cart. Please confirm:
        </Message>
        <ButtonGroup>
          <CancelButton onClick={cancelCartAction} disabled={confirmLoading}>
            Cancel
          </CancelButton>
          <Button onClick={handleConfirm} disabled={confirmLoading}>
            {confirmLoading ? 'Processing...' : 'Confirm Add to Cart'}
          </Button>
        </ButtonGroup>
      </Container>
      {confirmMessage && (
        <AlertMessage success={confirmSuccess === true}>
          {confirmMessage}
        </AlertMessage>
      )}
    </div>
  );
};
