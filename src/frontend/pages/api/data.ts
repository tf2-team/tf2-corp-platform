// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next';
import InstrumentationMiddleware from '../../utils/telemetry/InstrumentationMiddleware';
import AdGateway from '../../gateways/rpc/Ad.gateway';
import { Ad, Empty } from '../../protos/demo';
import {
  isOptionalDependencyError,
  recordOptionalDependencyFallback,
  setDegradedDependencyHeader,
} from '../../utils/resilience/OptionalDependency';

type TResponse = Ad[] | Empty;

const handler = async ({ method, query }: NextApiRequest, res: NextApiResponse<TResponse>) => {
  switch (method) {
    case 'GET': {
      const { contextKeys = [] } = query;
      try {
        const { ads: adList } = await AdGateway.listAds(
          Array.isArray(contextKeys) ? contextKeys : contextKeys.split(',')
        );

        return res.status(200).json(adList);
      } catch (error) {
        if (!isOptionalDependencyError(error)) throw error;

        recordOptionalDependencyFallback('ad', error);
        setDegradedDependencyHeader(res, 'ad');
        return res.status(200).json([]);
      }
    }

    default: {
      return res.status(405).send('');
    }
  }
};

export default InstrumentationMiddleware(handler);
