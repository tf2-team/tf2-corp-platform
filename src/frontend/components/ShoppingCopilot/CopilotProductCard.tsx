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
  margin-bottom: 20px;
`;

const Card = styled.div`
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);

  &:hover {
    transform: translateY(-2px);
    border-color: #93c5fd;
    box-shadow: 0 8px 20px rgba(37, 99, 235, 0.1);
  }
`;

const ProductHeader = styled.div`
  margin-bottom: 12px;
`;

const Title = styled.h3`
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 8px 0;
  line-height: 1.4;
`;

const Price = styled.div`
  font-size: 18px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: -0.3px;
`;

const DescriptionText = styled.p`
  font-size: 13px;
  color: #475569;
  margin: 8px 0 0 0;
  line-height: 1.5;
`;

const ViewButton = styled.a`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 9px 16px;
  background-color: #f1f5f9;
  color: #334155;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.15s ease;

  &:hover {
    background-color: #2563eb;
    color: #ffffff;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
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
          <ProductHeader>
            <Title>{product.name}</Title>
            <Price>
              {formatPrice(
                product.priceUnits,
                product.priceNanos,
                product.currencyCode || 'USD'
              )}
            </Price>
            {product.description && <DescriptionText>{product.description}</DescriptionText>}
          </ProductHeader >
          <Link href={`/product/${product.productId}`} passHref legacyBehavior>
            <ViewButton>View Details</ViewButton>
          </Link>
        </Card >
      ))}
    </Grid >
  );
};
