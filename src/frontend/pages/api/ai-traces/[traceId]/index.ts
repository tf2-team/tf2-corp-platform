// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next';

const MAX_BODY_BYTES = 5 * 1024 * 1024; // 5 MiB cap

export const getJaegerBaseUrl = (): string => {
  const envUrl = process.env.JAEGER_QUERY_URL || 'http://jaeger:16686';
  // Strip trailing slashes and trailing /api/traces
  let url = envUrl.replace(/\/+$/, '');
  if (url.endsWith('/api/traces')) {
    url = url.substring(0, url.length - '/api/traces'.length);
  }
  return url;
};

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  res.setHeader('Cache-Control', 'private, no-store');

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { traceId } = req.query;
  const rawId = Array.isArray(traceId) ? traceId[0] : traceId || '';

  if (!rawId || !/^[0-9a-fA-F]{32}$/.test(rawId)) {
    return res.status(400).json({ error: 'Invalid trace ID' });
  }

  const normalizedId = rawId.toLowerCase();
  const jaegerUrl = `${getJaegerBaseUrl()}/api/traces/${normalizedId}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const upstreamRes = await fetch(jaegerUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (upstreamRes.status === 404) {
      return res.status(404).json({ error: 'Trace not found' });
    }

    if (!upstreamRes.ok) {
      return res.status(502).json({ error: 'Upstream Jaeger service error' });
    }

    const contentLength = upstreamRes.headers.get('content-length');
    if (contentLength && parseInt(contentLength, 10) > MAX_BODY_BYTES) {
      return res.status(502).json({ error: 'Upstream response size exceeded 5 MiB' });
    }

    const arrayBuffer = await upstreamRes.arrayBuffer();
    if (arrayBuffer.byteLength > MAX_BODY_BYTES) {
      return res.status(502).json({ error: 'Upstream response size exceeded 5 MiB' });
    }

    const text = new TextDecoder('utf-8').decode(arrayBuffer);
    let jsonData: any;
    try {
      jsonData = JSON.parse(text);
    } catch {
      return res.status(502).json({ error: 'Invalid JSON response from upstream Jaeger' });
    }

    // Check if Jaeger returned an empty data array or null
    if (!jsonData || (Array.isArray(jsonData.data) && jsonData.data.length === 0)) {
      return res.status(404).json({ error: 'Trace not found' });
    }

    return res.status(200).json(jsonData);
  } catch (err: any) {
    if (err?.name === 'AbortError' || err?.code === 'ABORT_ERR') {
      return res.status(504).json({ error: 'Upstream Jaeger query timed out' });
    }
    return res.status(502).json({ error: 'Failed to query upstream Jaeger' });
  }
};

export default handler;

// Change trail: @hungxqt - 2026-07-29 - Implement private Jaeger trace proxy endpoint with validation and size bounds.
