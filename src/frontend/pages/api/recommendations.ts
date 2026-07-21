// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next';
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

const handler = async ({ method, query }: NextApiRequest, res: NextApiResponse<TResponse>) => {
  switch (method) {
    case 'GET': {
      const { productIds = [], sessionId = '', currencyCode = '' } = query;
      let productList: string[];
      try {
        const response = await RecommendationsGateway.listRecommendations(sessionId as string, productIds as string[]);
        productList = response.productIds;
      } catch (error) {
        if (!isOptionalDependencyError(error)) throw error;

        recordOptionalDependencyFallback('recommendation', error);
        setDegradedDependencyHeader(res, 'recommendation');
        return res.status(200).json([]);
      }

      const recommendedProductList = await Promise.all(
        productList.slice(0, 4).map(id => ProductCatalogService.getProduct(id, currencyCode as string))
      );

      return res.status(200).json(recommendedProductList);
    }

    default: {
      return res.status(405).send('');
    }
  }
};

export default InstrumentationMiddleware(handler);
