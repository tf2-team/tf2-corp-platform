// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import { status } from '@grpc/grpc-js';

process.env.AD_ADDR = '127.0.0.1:1';
process.env.RECOMMENDATION_ADDR = '127.0.0.1:1';
process.env.PRODUCT_CATALOG_ADDR = '127.0.0.1:1';
process.env.CURRENCY_ADDR = '127.0.0.1:1';

const { createAdGateway } = await import('../../gateways/rpc/Ad.gateway.ts');
const { createRecommendationsGateway } = await import('../../gateways/rpc/Recommendations.gateway.ts');
const { createDataHandler } = await import('../../pages/api/data.ts');
const { createRecommendationsHandler } = await import('../../pages/api/recommendations.ts');

const createResponse = () => {
  const headers = new Map();
  return {
    statusCode: 200,
    body: undefined,
    getHeader: name => headers.get(name),
    setHeader(name, value) {
      headers.set(name, value);
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(value) {
      this.body = value;
      return this;
    },
    send(value) {
      this.body = value;
      return this;
    },
  };
};

test('ad gateway applies the optional dependency deadline', async () => {
  let capturedOptions;
  const gateway = createAdGateway({
    getAds(_request, _metadata, options, callback) {
      capturedOptions = options;
      callback(null, { ads: [] });
    },
  });

  const before = Date.now();
  await gateway.listAds(['product']);
  assert.ok(capturedOptions.deadline.getTime() - before >= 450);
  assert.ok(capturedOptions.deadline.getTime() - before <= 550);
});

test('recommendation gateway applies the optional dependency deadline', async () => {
  let capturedOptions;
  const gateway = createRecommendationsGateway({
    listRecommendations(_request, _metadata, options, callback) {
      capturedOptions = options;
      callback(null, { productIds: [] });
    },
  });

  const before = Date.now();
  await gateway.listRecommendations('session', ['product']);
  assert.ok(capturedOptions.deadline.getTime() - before >= 450);
  assert.ok(capturedOptions.deadline.getTime() - before <= 550);
});

test('ad API returns an empty degraded response for availability failures', async () => {
  const response = createResponse();
  const handler = createDataHandler(
    { listAds: async () => { throw { code: status.UNAVAILABLE }; } },
    () => {}
  );

  await handler({ method: 'GET', query: { contextKeys: 'one,two' } }, response);

  assert.equal(response.statusCode, 200);
  assert.deepEqual(response.body, []);
  assert.equal(response.getHeader('X-TechX-Degraded-Dependencies'), 'ad');
});

test('ad API propagates non-degradable errors', async () => {
  const handler = createDataHandler(
    { listAds: async () => { throw new TypeError('invalid response'); } },
    () => {}
  );

  await assert.rejects(
    () => handler({ method: 'GET', query: {} }, createResponse()),
    /invalid response/
  );
});

test('recommendation fallback does not call product catalog', async () => {
  let catalogCalls = 0;
  const response = createResponse();
  const handler = createRecommendationsHandler(
    { listRecommendations: async () => { throw { code: status.DEADLINE_EXCEEDED }; } },
    { getProduct: async () => { catalogCalls += 1; return {}; } },
    () => {}
  );

  await handler({
    method: 'GET',
    query: { productIds: ['one'], sessionId: 'session', currencyCode: 'USD' },
  }, response);

  assert.equal(response.statusCode, 200);
  assert.deepEqual(response.body, []);
  assert.equal(response.getHeader('X-TechX-Degraded-Dependencies'), 'recommendation');
  assert.equal(catalogCalls, 0);
});

test('recommendation API propagates non-degradable errors', async () => {
  const handler = createRecommendationsHandler(
    { listRecommendations: async () => { throw { code: status.INVALID_ARGUMENT }; } },
    { getProduct: async () => ({}) },
    () => {}
  );

  await assert.rejects(
    () => handler({ method: 'GET', query: {} }, createResponse()),
    error => error.code === status.INVALID_ARGUMENT
  );
});
