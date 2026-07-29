import assert from 'node:assert/strict';
import test from 'node:test';
import handlerModule, { getJaegerBaseUrl } from './[traceId]/index.ts';

const handler = handlerModule.default || handlerModule;

function createMockReqRes({ method = 'GET', traceId = '24fc9daea47c1733fc92d6265da50c96' } = {}) {
  const req = {
    method,
    query: { traceId },
  };

  const headers = {};
  let statusCode = 200;
  let jsonBody = null;

  const res = {
    setHeader: (key, val) => {
      headers[key] = val;
    },
    status: (code) => {
      statusCode = code;
      return res;
    },
    json: (data) => {
      jsonBody = data;
      return res;
    },
    getHeader: (key) => headers[key],
    getStatusCode: () => statusCode,
    getJsonBody: () => jsonBody,
  };

  return { req, res, headers };
}

test('Trace API rejects non-GET methods with 405', async () => {
  const { req, res } = createMockReqRes({ method: 'POST' });
  await handler(req, res);
  assert.equal(res.getStatusCode(), 405);
  assert.equal(res.getHeader('Cache-Control'), 'private, no-store');
});

test('Trace API rejects invalid trace IDs with 400', async () => {
  const { req, res } = createMockReqRes({ traceId: 'invalid-short-id' });
  await handler(req, res);
  assert.equal(res.getStatusCode(), 400);

  const { req: req2, res: res2 } = createMockReqRes({ traceId: '24fc9daea47c1733fc92d6265da50c96xyz' });
  await handler(req2, res2);
  assert.equal(res2.getStatusCode(), 400);
});

test('Trace API resolves Jaeger URL from environment without exposing it', () => {
  const originalEnv = process.env.JAEGER_QUERY_URL;
  try {
    process.env.JAEGER_QUERY_URL = 'http://jaeger:16686/api/traces';
    assert.equal(getJaegerBaseUrl(), 'http://jaeger:16686');

    process.env.JAEGER_QUERY_URL = 'http://custom-jaeger:16686/';
    assert.equal(getJaegerBaseUrl(), 'http://custom-jaeger:16686');
  } finally {
    process.env.JAEGER_QUERY_URL = originalEnv;
  }
});

// Change trail: @hungxqt - 2026-07-29 - Add unit tests for private trace API validation, methods, and URL parsing.
