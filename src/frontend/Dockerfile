# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM docker.io/library/node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS builder

# Apply Debian security updates so builder OS packages (e.g. OpenSSL) match Trivy fixed versions.
RUN apk upgrade --no-cache

WORKDIR /app

COPY ./src/frontend/package.json package.json
COPY ./src/frontend/package-lock.json package-lock.json

RUN npm ci

COPY ./src/frontend/components/ components/
COPY ./src/frontend/gateways/ gateways/
COPY ./src/frontend/pages/ pages/
COPY ./src/frontend/protos/ protos/
COPY ./src/frontend/providers/ providers/
COPY ./src/frontend/services/ services/
COPY ./src/frontend/styles/ styles/
COPY ./src/frontend/types/ types/

COPY ./src/frontend/utils/enums/ utils/enums/
COPY ./src/frontend/utils/telemetry/ utils/telemetry/
COPY ./src/frontend/utils/imageLoader.js utils/imageLoader.js
COPY ./src/frontend/utils/Request.ts utils/Request.ts

COPY ./src/frontend/next.config.js next.config.js
COPY ./src/frontend/tsconfig.json tsconfig.json

RUN npm run build

# -----------------------------------------------------------------------------

FROM docker.io/library/node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS deps

RUN apk upgrade --no-cache

WORKDIR /app

COPY ./src/frontend/package.json package.json
COPY ./src/frontend/package-lock.json package-lock.json

RUN npm ci --omit=dev

# -----------------------------------------------------------------------------
# Use node:22-slim (not distroless) so runtime can apply Debian security upgrades
# required for Trivy HIGH/CRITICAL (e.g. OpenSSL CVE-2026-31789).

FROM docker.io/library/node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2

RUN apk upgrade --no-cache

# The runtime invokes node directly; remove package managers and their bundled
# dependency trees so build-only tooling is not part of the production image.
RUN rm -rf /usr/local/lib/node_modules/npm /opt/yarn-v* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg

WORKDIR /app

COPY --from=builder /app/.next/standalone/ ./
COPY --from=builder /app/.next/static/ .next/static/

COPY --from=deps /app/node_modules/ node_modules/

COPY ./src/frontend/public/ public/

COPY ./src/frontend/utils/telemetry/Instrumentation.js Instrumentation.js

RUN addgroup -g 10001 -S appgroup \
    && adduser -u 10001 -S -D -H -G appgroup appuser \
    && chown -R appuser:appgroup /app

EXPOSE ${FRONTEND_PORT}

USER 10001
CMD ["node", "--require=./Instrumentation.js", "server.js"]
# Change trail: @hungxqt - 2026-07-20 - Node slim runtime + apt upgrade and Next/protobufjs security bumps for Trivy
