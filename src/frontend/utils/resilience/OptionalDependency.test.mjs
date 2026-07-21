// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import { status } from '@grpc/grpc-js';
import {
  createOptionalDependencyDeadline,
  getOptionalDependencyTimeoutMs,
  isOptionalDependencyError,
  setDegradedDependencyHeader,
} from './OptionalDependency.ts';

test('uses a bounded default for missing or invalid timeout values', () => {
  assert.equal(getOptionalDependencyTimeoutMs(undefined), 500);
  assert.equal(getOptionalDependencyTimeoutMs('invalid'), 500);
  assert.equal(getOptionalDependencyTimeoutMs('0'), 500);
  assert.equal(getOptionalDependencyTimeoutMs('750'), 750);
});

test('creates the default deadline approximately 500 ms in the future', () => {
  const before = Date.now();
  const deadline = createOptionalDependencyDeadline().getTime();
  assert.ok(deadline - before >= 450);
  assert.ok(deadline - before <= 550);
});

test('only classifies dependency availability and connection errors as degradable', () => {
  assert.equal(isOptionalDependencyError({ code: status.DEADLINE_EXCEEDED }), true);
  assert.equal(isOptionalDependencyError({ code: status.UNAVAILABLE }), true);
  assert.equal(isOptionalDependencyError({ cause: { code: 'ECONNREFUSED' } }), true);
  assert.equal(isOptionalDependencyError({ code: status.INVALID_ARGUMENT }), false);
  assert.equal(isOptionalDependencyError(new TypeError('programming error')), false);
});

test('adds dependencies to the degraded response header without duplicates', () => {
  const headers = new Map();
  const response = {
    getHeader: name => headers.get(name),
    setHeader: (name, value) => headers.set(name, value),
  };

  setDegradedDependencyHeader(response, 'ad');
  setDegradedDependencyHeader(response, 'recommendation');
  setDegradedDependencyHeader(response, 'ad');
  assert.equal(headers.get('X-TechX-Degraded-Dependencies'), 'ad,recommendation');
});
