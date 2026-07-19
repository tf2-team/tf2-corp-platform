// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiHandler } from 'next';
import ShoppingCopilotService from '../../../services/ShoppingCopilot.service';
import InstrumentationMiddleware from '../../../utils/telemetry/InstrumentationMiddleware';

const handler: NextApiHandler = async (req, res) => {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { pending_action_token = '', user_id = 'anonymous' } = req.body || {};

  if (!pending_action_token) {
    return res.status(400).json({ success: false, reason: 'pending_action_token is required' });
  }

  try {
    const response = await ShoppingCopilotService.confirmCartAction(
      pending_action_token,
      user_id
    );
    return res.status(200).json(response);
  } catch (error: any) {
    return res.status(500).json({
      success: false,
      reason: error?.message || 'Cart confirmation failed',
    });
  }
};

export default InstrumentationMiddleware(handler);
