// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiHandler } from 'next';
import InstrumentationMiddleware from '../../utils/telemetry/InstrumentationMiddleware';
import RecommendationsGateway from '../../gateways/rpc/Recommendations.gateway';
import { Empty, Product } from '../../protos/demo';
import ProductCatalogService from '../../services/ProductCatalog.service';
import {
  isOptionalDependencyError,
  recordOptionalDependencyFallback,
  setDegradedDependencyHeader,
} from '../../utils/resilience/OptionalDependency';

type TResponse = Product[] | Empty;

type RecommendationDependency = Pick<typeof RecommendationsGateway, 'listRecommendations'>;
type CatalogDependency = Pick<typeof ProductCatalogService, 'getProduct'>;

export const createRecommendationsHandler = (
  recommendationDependency: RecommendationDependency = RecommendationsGateway,
  catalogDependency: CatalogDependency = ProductCatalogService,
  onFallback: typeof recordOptionalDependencyFallback = recordOptionalDependencyFallback
): NextApiHandler<TResponse> => async ({ method, query }, res) => {
  switch (method) {
    case 'GET': {
      const { productIds = [], sessionId = '', currencyCode = '' } = query;
      let productList: string[];
      try {
        const response = await recommendationDependency.listRecommendations(
          sessionId as string,
          productIds as string[]
        );
        productList = response.productIds;
      } catch (error) {
        if (!isOptionalDependencyError(error)) throw error;

        onFallback('recommendation', error);
        setDegradedDependencyHeader(res, 'recommendation');
        return res.status(200).json([]);
      }

      const recommendedProductList = await Promise.all(
        productList.slice(0, 4).map(id => catalogDependency.getProduct(id, currencyCode as string))
      );

      return res.status(200).json(recommendedProductList);
    }

    default: {
      return res.status(405).send('');
    }
  }
};

export default InstrumentationMiddleware(createRecommendationsHandler());
