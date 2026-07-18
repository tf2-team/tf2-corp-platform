// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import ShoppingCopilotGateway from '../gateways/rpc/ShoppingCopilot.gateway';

const ShoppingCopilotService = () => ({
  async search(userMessage: string) {
    const response = await ShoppingCopilotGateway.search(userMessage);
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
