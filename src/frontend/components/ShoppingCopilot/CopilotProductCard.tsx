// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import Link from 'next/link';
import styled from 'styled-components';
import { CopilotProduct } from '../../providers/ShoppingCopilot.provider';

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
`;

const Card = styled.div`
  background: ${({ theme }) => theme.colors.white};
  border: 1px solid ${({ theme }) => theme.colors.lightBorderGray};
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: transform 0.2s, box-shadow 0.2s;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08);
  }
`;

const Title = styled.h3`
  font-size: 16px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.textGray};
  margin: 0 0 8px 0;
`;

const Price = styled.div`
  font-size: 18px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.otelBlue};
  margin-bottom: 12px;
`;

const ViewButton = styled.a`
  display: inline-block;
  text-align: center;
  padding: 8px 14px;
  background-color: ${({ theme }) => theme.colors.backgroundGray};
  color: ${({ theme }) => theme.colors.textGray};
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: background-color 0.2s;

  &:hover {
    background-color: ${({ theme }) => theme.colors.otelBlue};
    color: ${({ theme }) => theme.colors.white};
  }
`;

interface Props {
  products: CopilotProduct[];
}

export const CopilotProductCard: React.FC<Props> = ({ products }) => {
  if (!products || products.length === 0) return null;

  const formatPrice = (units: number, nanos: number, currency: string) => {
    const total = units + nanos / 1000000000;
    return `$${total.toFixed(2)} ${currency}`;
  };

  return (
    <Grid>
      {products.map((product) => (
        <Card key={product.productId}>
          <div>
            <Title>{product.name}</Title>
            <Price>
              {formatPrice(
                product.priceUnits,
                product.priceNanos,
                product.currencyCode || 'USD'
              )}
            </Price>
          </div>
          <Link href={`/product/${product.productId}`} passHref legacyBehavior>
            <ViewButton>Xem chi tiết</ViewButton>
          </Link>
        </Card>
      ))}
    </Grid>
  );
};
