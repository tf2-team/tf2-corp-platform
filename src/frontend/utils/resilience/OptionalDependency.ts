// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { context, metrics, trace } from '@opentelemetry/api';
import { status } from '@grpc/grpc-js';
import type { NextApiResponse } from 'next';

const DEFAULT_TIMEOUT_MS = 500;
const DEFAULT_CIRCUIT_COOLDOWN_MS = 30_000;
const DEFAULT_WARNING_INTERVAL_MS = 30_000;
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

const meter = metrics.getMeter('frontend');
const fallbackCounter = meter.createCounter('app.frontend.optional_dependency_fallbacks');
const circuitOpenUntil = new Map<string, number>();
const lastWarningAt = new Map<string, number>();

export const getOptionalDependencyTimeoutMs = (rawValue = process.env.OPTIONAL_DEPENDENCY_TIMEOUT_MS): number => {
  if (!rawValue) return DEFAULT_TIMEOUT_MS;
  const parsed = Number(rawValue);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
};

export const createOptionalDependencyDeadline = (): Date =>
  new Date(Date.now() + getOptionalDependencyTimeoutMs());

export const getOptionalDependencyCircuitCooldownMs = (
  rawValue = process.env.OPTIONAL_DEPENDENCY_CIRCUIT_COOLDOWN_MS
): number => {
  if (!rawValue) return DEFAULT_CIRCUIT_COOLDOWN_MS;
  const parsed = Number(rawValue);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : DEFAULT_CIRCUIT_COOLDOWN_MS;
};

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

export const isOptionalDependencyCircuitOpen = (dependency: string, now = Date.now()): boolean =>
  (circuitOpenUntil.get(dependency) ?? 0) > now;

const annotateFallback = (dependency: string, errorCode: string, reason: 'error' | 'circuit_open'): void => {
  fallbackCounter.add(1, { dependency, error_code: errorCode, reason });
  const span = trace.getSpan(context.active());
  span?.setAttribute('app.degraded', true);
  span?.setAttribute('app.degraded_dependency', dependency);
  span?.addEvent('optional_dependency.fallback', {
    'dependency.name': dependency,
    'error.code': errorCode,
    'fallback.reason': reason,
  });
};

export const recordOptionalDependencyFallback = (dependency: string, error: unknown, now = Date.now()): void => {
  const errorLike = asErrorLike(error);
  const errorCode = String(errorLike?.code ?? 'unknown');
  circuitOpenUntil.set(dependency, now + getOptionalDependencyCircuitCooldownMs());
  annotateFallback(dependency, errorCode, 'error');

  const previousWarning = lastWarningAt.get(dependency);
  if (previousWarning === undefined || now - previousWarning >= DEFAULT_WARNING_INTERVAL_MS) {
    lastWarningAt.set(dependency, now);
    console.warn(JSON.stringify({ event: 'optional_dependency_fallback', dependency, errorCode }));
  }
};

/** A cool-down bypass is still observable, but does not extend the circuit. */
export const recordOptionalDependencyCircuitOpen = (dependency: string): void =>
  annotateFallback(dependency, 'circuit_open', 'circuit_open');

/** Test-only reset for the process-local circuit breaker. */
export const resetOptionalDependencyCircuitForTest = (): void => {
  circuitOpenUntil.clear();
  lastWarningAt.clear();
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
