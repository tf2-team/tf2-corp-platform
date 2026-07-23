// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { ListRecommendationsResponse, RecommendationServiceClient } from '../../protos/demo';
import { createOptionalDependencyDeadline } from '../../utils/resilience/OptionalDependency';

const { RECOMMENDATION_ADDR = '' } = process.env;

const client = new RecommendationServiceClient(RECOMMENDATION_ADDR, ChannelCredentials.createInsecure());

type RecommendationsClient = Pick<RecommendationServiceClient, 'listRecommendations'>;

export const createRecommendationsGateway = (recommendationsClient: RecommendationsClient = client) => ({
  listRecommendations(userId: string, productIds: string[]) {
    return new Promise<ListRecommendationsResponse>((resolve, reject) =>
      recommendationsClient.listRecommendations(
        { userId, productIds },
        new Metadata(),
        { deadline: createOptionalDependencyDeadline() },
        (error, response) => (error ? reject(error) : resolve(response))
      )
    );
  },
});

export default createRecommendationsGateway();
