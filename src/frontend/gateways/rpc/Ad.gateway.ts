// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { AdResponse, AdServiceClient } from '../../protos/demo';
import { createOptionalDependencyDeadline } from '../../utils/resilience/OptionalDependency';

const { AD_ADDR = '' } = process.env;

const client = new AdServiceClient(AD_ADDR, ChannelCredentials.createInsecure());

const AdGateway = () => ({
  listAds(contextKeys: string[]) {
    return new Promise<AdResponse>((resolve, reject) =>
      client.getAds(
        { contextKeys: contextKeys },
        new Metadata(),
        { deadline: createOptionalDependencyDeadline() },
        (error, response) => (error ? reject(error) : resolve(response))
      )
    );
  },
});

export default AdGateway();
