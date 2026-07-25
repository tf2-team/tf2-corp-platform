// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeMetricTarget } from './InstrumentationMiddleware.ts';

test('normalizes product identifiers before they become metric labels', () => {
  assert.equal(normalizeMetricTarget('/api/products/OLJCESPC7Z/index'), '/api/products/{productId}/index');
  assert.equal(normalizeMetricTarget('/api/product-reviews/OLJCESPC7Z/index'), '/api/product-reviews/{productId}/index');
  assert.equal(normalizeMetricTarget('/api/cart'), '/api/cart');
});
