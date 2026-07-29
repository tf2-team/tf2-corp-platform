// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type {NextApiRequest, NextApiResponse} from 'next';
import InstrumentationMiddleware from '../../../utils/telemetry/InstrumentationMiddleware';

const TRACE_ID = /^[0-9a-f]{32}$/i;
export const isValidTraceId = (value: string): boolean => TRACE_ID.test(value);

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  if (req.method !== 'GET') {
    return res.status(405).json({error: 'Method not allowed'});
  }

  const traceId = String(req.query.traceId || '');
  if (!isValidTraceId(traceId)) {
    return res.status(400).json({error: 'Invalid trace ID'});
  }

  const baseUrl = process.env.JAEGER_QUERY_URL;
  if (!baseUrl) {
    return res.status(503).json({error: 'Trace backend is not configured'});
  }

  try {
    const response = await fetch(
      `${baseUrl.replace(/\/$/, '')}/api/traces/${traceId}`,
      {headers: {accept: 'application/json'}},
    );
    const body = await response.json();
    return res.status(response.status).json(body);
  } catch {
    return res.status(502).json({error: 'Trace backend is unavailable'});
  }
};

export default InstrumentationMiddleware(handler);
