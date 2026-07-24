// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { context, trace } from '@opentelemetry/api';
import { status } from '@grpc/grpc-js';
import type { NextApiResponse } from 'next';

const DEFAULT_TIMEOUT_MS = 500;
const DEGRADED_HEADER = 'X-TechX-Degraded-Dependencies';
const CONNECTION_ERROR_CODES = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ENOTFOUND',
  'ETIMEDOUT',
]);

type ErrorLike = {
  code?: number | string;
  cause?: unknown;
};

export const getOptionalDependencyTimeoutMs = (rawValue = process.env.OPTIONAL_DEPENDENCY_TIMEOUT_MS): number => {
  if (!rawValue) return DEFAULT_TIMEOUT_MS;
  const parsed = Number(rawValue);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
};

export const createOptionalDependencyDeadline = (): Date =>
  new Date(Date.now() + getOptionalDependencyTimeoutMs());

const asErrorLike = (error: unknown): ErrorLike | undefined =>
  typeof error === 'object' && error !== null ? (error as ErrorLike) : undefined;

export const isOptionalDependencyError = (error: unknown): boolean => {
  let current = asErrorLike(error);
  const visited = new Set<ErrorLike>();
  while (current && !visited.has(current)) {
    visited.add(current);
    if (current.code === status.DEADLINE_EXCEEDED || current.code === status.UNAVAILABLE) return true;
    if (typeof current.code === 'string' && CONNECTION_ERROR_CODES.has(current.code.toUpperCase())) return true;
    current = asErrorLike(current.cause);
  }
  return false;
};

export const recordOptionalDependencyFallback = (dependency: string, error: unknown): void => {
  const errorLike = asErrorLike(error);
  const span = trace.getSpan(context.active());
  span?.setAttribute('app.degraded', true);
  span?.setAttribute('app.degraded_dependency', dependency);
  span?.addEvent('optional_dependency.fallback', {
    'dependency.name': dependency,
    'error.code': String(errorLike?.code ?? 'unknown'),
  });
  console.warn(JSON.stringify({
    event: 'optional_dependency_fallback',
    dependency,
    errorCode: errorLike?.code ?? 'unknown',
  }));
};

export const setDegradedDependencyHeader = (response: NextApiResponse, dependency: string): void => {
  const existing = response.getHeader(DEGRADED_HEADER);
  const dependencies = new Set(
    (Array.isArray(existing) ? existing : String(existing ?? '').split(','))
      .map(value => value.trim())
      .filter(Boolean)
  );
  dependencies.add(dependency);
  response.setHeader(DEGRADED_HEADER, [...dependencies].join(','));
};
