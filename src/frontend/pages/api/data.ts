// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiHandler } from 'next';
import InstrumentationMiddleware from '../../utils/telemetry/InstrumentationMiddleware';
import AdGateway from '../../gateways/rpc/Ad.gateway';
import { Ad, Empty } from '../../protos/demo';
import {
  isOptionalDependencyError,
  isOptionalDependencyCircuitOpen,
  recordOptionalDependencyCircuitOpen,
  recordOptionalDependencyFallback,
  setDegradedDependencyHeader,
} from '../../utils/resilience/OptionalDependency';

type TResponse = Ad[] | Empty;

type AdDependency = Pick<typeof AdGateway, 'listAds'>;

export const createDataHandler = (
  adDependency: AdDependency = AdGateway,
  onFallback: typeof recordOptionalDependencyFallback = recordOptionalDependencyFallback
): NextApiHandler<TResponse> => async ({ method, query }, res) => {
  switch (method) {
    case 'GET': {
      const { contextKeys = [] } = query;
      if (isOptionalDependencyCircuitOpen('ad')) {
        recordOptionalDependencyCircuitOpen('ad');
        setDegradedDependencyHeader(res, 'ad');
        return res.status(200).json([]);
      }
      try {
        const { ads: adList } = await adDependency.listAds(
          Array.isArray(contextKeys) ? contextKeys : contextKeys.split(',')
        );

        return res.status(200).json(adList);
      } catch (error) {
        if (!isOptionalDependencyError(error)) throw error;

        onFallback('ad', error);
        setDegradedDependencyHeader(res, 'ad');
        return res.status(200).json([]);
      }
    }

    default: {
      return res.status(405).send('');
    }
  }
};

export default InstrumentationMiddleware(createDataHandler());
