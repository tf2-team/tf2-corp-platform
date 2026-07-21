// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { ListRecommendationsResponse, RecommendationServiceClient } from '../../protos/demo';
import { createOptionalDependencyDeadline } from '../../utils/resilience/OptionalDependency';

const { RECOMMENDATION_ADDR = '' } = process.env;

const client = new RecommendationServiceClient(RECOMMENDATION_ADDR, ChannelCredentials.createInsecure());

const RecommendationsGateway = () => ({
  listRecommendations(userId: string, productIds: string[]) {
    return new Promise<ListRecommendationsResponse>((resolve, reject) =>
      client.listRecommendations(
        { userId, productIds },
        new Metadata(),
        { deadline: createOptionalDependencyDeadline() },
        (error, response) => (error ? reject(error) : resolve(response))
      )
    );
  },
});

export default RecommendationsGateway();
