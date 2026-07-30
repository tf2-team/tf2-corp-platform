import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeMetricTarget, isAiApi } from './InstrumentationMiddleware.ts';

test('normalizes product identifiers before they become metric labels', () => {
  assert.equal(normalizeMetricTarget('/api/products/OLJCESPC7Z/index'), '/api/products/{productId}/index');
  assert.equal(normalizeMetricTarget('/api/product-reviews/OLJCESPC7Z/index'), '/api/product-reviews/{productId}/index');
  assert.equal(normalizeMetricTarget('/api/cart'), '/api/cart');
});

test('identifies AI API targets for trace header emission', () => {
  assert.equal(isAiApi('/api/copilot'), true);
  assert.equal(isAiApi('/api/copilot/index'), true);
  assert.equal(isAiApi('/api/product-ask-ai-assistant/OLJCESPC7Z/index'), true);
  assert.equal(isAiApi('/api/cart'), false);
  assert.equal(isAiApi('/api/products'), false);
});

// Change trail: @hungxqt - 2026-07-29 - Add test coverage for isAiApi and trace ID header behavior.
