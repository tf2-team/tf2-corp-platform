// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelCredentials } from '@grpc/grpc-js';
import {
  CopilotSearchResponse,
  ConfirmCartActionResponse,
  ShoppingCopilotServiceClient,
} from '../../protos/demo';

const { SHOPPING_COPILOT_ADDR = 'shopping-copilot:3552' } = process.env;

const client = new ShoppingCopilotServiceClient(
  SHOPPING_COPILOT_ADDR,
  ChannelCredentials.createInsecure()
);

const ShoppingCopilotGateway = () => ({
  search(userMessage: string) {
    return new Promise<CopilotSearchResponse>((resolve, reject) =>
      client.search({ userMessage }, (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
  confirmCartAction(pendingActionToken: string, userId: string) {
    return new Promise<ConfirmCartActionResponse>((resolve, reject) =>
      client.confirmCartAction({ pendingActionToken, userId }, (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
});

export default ShoppingCopilotGateway();
