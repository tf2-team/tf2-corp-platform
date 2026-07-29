// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import {isValidTraceId} from './[traceId].ts';

test('accepts only a 32-character hexadecimal trace ID', () => {
  assert.equal(isValidTraceId('0123456789abcdef0123456789abcdef'), true);
  assert.equal(isValidTraceId('PII-TOKEN-XYZ'), false);
  assert.equal(isValidTraceId('../api/traces'), false);
});
