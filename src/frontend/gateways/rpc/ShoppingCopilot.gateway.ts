// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import {
  CallOptions,
  ChannelCredentials,
  ClientUnaryCall,
  Metadata,
  ServiceError,
} from '@grpc/grpc-js';
import {
  CopilotSearchRequest,
  CopilotSearchResponse,
  ConfirmCartActionResponse,
  ShoppingCopilotServiceClient,
} from '../../protos/demo';

const { SHOPPING_COPILOT_ADDR = 'shopping-copilot:3552' } = process.env;

type ShoppingCopilotClientWithOptions = Omit<ShoppingCopilotServiceClient, 'search'> & {
  search(
    request: CopilotSearchRequest,
    metadata: Metadata,
    options: CallOptions,
    callback: (error: ServiceError | null, response: CopilotSearchResponse) => void
  ): ClientUnaryCall;
};

const client = new ShoppingCopilotServiceClient(
  SHOPPING_COPILOT_ADDR,
  ChannelCredentials.createInsecure()
) as unknown as ShoppingCopilotClientWithOptions;

const ShoppingCopilotGateway = () => ({
  search(userMessage: string, userId: string, conversationId: string, turnId: string) {
    return new Promise<CopilotSearchResponse>((resolve, reject) =>
      client.search(
        { userMessage, userId, conversationId, turnId },
        new Metadata(),
        { deadline: Date.now() + 18_000 },
        (error, response) => error ? reject(error) : resolve(response)
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
