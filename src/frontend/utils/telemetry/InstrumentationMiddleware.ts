// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { NextApiHandler } from 'next';
import {context, Exception, Span, SpanStatusCode, trace} from '@opentelemetry/api';
import { SemanticAttributes } from '@opentelemetry/semantic-conventions';
import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('frontend');
const requestCounter = meter.createCounter('app.frontend.requests');

/** Keep Prometheus labels bounded while preserving the endpoint's operation. */
export const normalizeMetricTarget = (target: string): string => {
  if (/^\/api\/products\/[^/]+\/index$/.test(target)) return '/api/products/{productId}/index';
  if (/^\/api\/product-reviews\/[^/]+\/index$/.test(target)) return '/api/product-reviews/{productId}/index';
  if (/^\/api\/product-reviews-avg-score\/[^/]+\/index$/.test(target)) return '/api/product-reviews-avg-score/{productId}/index';
  if (/^\/api\/product-ask-ai-assistant\/[^/]+\/index$/.test(target)) return '/api/product-ask-ai-assistant/{productId}/index';
  return target;
};

const InstrumentationMiddleware = (handler: NextApiHandler): NextApiHandler => {
  return async (request, response) => {
    const {method, url = ''} = request;
    const [rawTarget] = url.split('?');
    const target = normalizeMetricTarget(rawTarget);

    const span = trace.getSpan(context.active()) as Span;

    let httpStatus = 200;
    try {
      await runWithSpan(span, async () => handler(request, response));
      httpStatus = response.statusCode;
    } catch (error) {
      span.recordException(error as Exception);
      span.setStatus({ code: SpanStatusCode.ERROR });
      httpStatus = 500;
      throw error;
    } finally {
      requestCounter.add(1, { method, target, status: httpStatus });
      span.setAttribute(SemanticAttributes.HTTP_STATUS_CODE, httpStatus);
    }
  };
};

async function runWithSpan(parentSpan: Span, fn: () => Promise<unknown>) {
  const ctx = trace.setSpan(context.active(), parentSpan);
  return await context.with(ctx, fn);
}

export default InstrumentationMiddleware;
