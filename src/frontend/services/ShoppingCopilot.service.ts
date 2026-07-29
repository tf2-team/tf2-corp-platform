// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import ShoppingCopilotGateway from '../gateways/rpc/ShoppingCopilot.gateway';

const ShoppingCopilotService = () => ({
  async search(userMessage: string, userId: string, conversationId: string, turnId: string) {
    const response = await ShoppingCopilotGateway.search(
      userMessage,
      userId,
      conversationId,
      turnId
    );
    return response;
  },
  async confirmCartAction(pendingActionToken: string, userId: string) {
    const response = await ShoppingCopilotGateway.confirmCartAction(
      pendingActionToken,
      userId
    );
    return response;
  },
});

export default ShoppingCopilotService();
