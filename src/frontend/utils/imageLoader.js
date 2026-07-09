// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
/*
 * Always emit same-origin relative URLs so SSR HTML and client hydration match.
 * Baking host:port at module load (e.g. localhost:8080) breaks the public ALB
 * and triggers React hydration error #418 / net::ERR_CONNECTION_REFUSED.
 *
 * Envoy routes:
 *   /images/*  → image-provider
 *   /icons/*   → frontend (Next.js public/)
 * image-provider serves files as-is; ?w=&q= are kept for Next Image API compat.
 */
export default function imageLoader({ src, width, quality }) {
  const path = src.startsWith('/') ? src : `/${src}`;
  return `${path}?w=${width}&q=${quality || 75}`;
}
