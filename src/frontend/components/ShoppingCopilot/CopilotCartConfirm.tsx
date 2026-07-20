// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import styled from 'styled-components';
import { useQueryClient } from '@tanstack/react-query';
import { useShoppingCopilot } from '../../providers/ShoppingCopilot.provider';

const Container = styled.div`
  background: #fefce8;
  border: 1px solid #fef08a;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 2px 8px rgba(234, 179, 8, 0.08);

  @media (max-width: 600px) {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
`;

const Message = styled.div`
  font-size: 14.5px;
  font-weight: 600;
  color: #854d0e;
`;

const ButtonGroup = styled.div`
  display: flex;
  gap: 10px;
  align-items: center;
`;

const Button = styled.button`
  padding: 10px 20px;
  background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%);
  color: #ffffff;
  font-weight: 700;
  font-size: 14px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(202, 138, 4, 0.25);
  transition: all 0.15s ease;

  &:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(202, 138, 4, 0.35);
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
`;

const CancelButton = styled.button`
  padding: 10px 16px;
  background-color: #ffffff;
  color: #475569;
  font-weight: 600;
  font-size: 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;

  &:hover:not(:disabled) {
    background-color: #f8fafc;
    color: #0f172a;
    border-color: #94a3b8;
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
`;

const AlertMessage = styled.div<{ success?: boolean }>`
  margin-top: 10px;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 600;
  background-color: ${({ success }) => (success ? '#f0fdf4' : '#fef2f2')};
  color: ${({ success }) => (success ? '#166534' : '#991b1b')};
  border: 1px solid ${({ success }) => (success ? '#bbf7d0' : '#fecaca')};
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
          AI Assistant recommends adding this item to your cart. Please confirm:
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
