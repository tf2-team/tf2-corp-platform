// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiHandler } from 'next';
import ShoppingCopilotService from '../../../services/ShoppingCopilot.service';
import InstrumentationMiddleware from '../../../utils/telemetry/InstrumentationMiddleware';

const handler: NextApiHandler = async (req, res) => {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { user_message = '', user_id = 'anonymous' } = req.body || {};

  if (!user_message.trim()) {
    return res.status(400).json({ error: 'user_message is required' });
  }

  try {
    const response = await ShoppingCopilotService.search(user_message, user_id);
    return res.status(200).json(response);
  } catch (error: any) {
    return res.status(200).json({
      status: 'FALLBACK',
      interpretedCriteria: '',
      products: [],
      claims: [],
      sources: [],
      reason: 'Shopping Copilot service is temporarily unavailable. Please try again.',
      pendingActionToken: '',
      error: error?.message || String(error),
    });
  }
};

export default InstrumentationMiddleware(handler);
