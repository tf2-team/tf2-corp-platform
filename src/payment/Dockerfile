# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS builder

RUN apk upgrade --no-cache

WORKDIR /usr/src/app/

COPY ./src/payment/package.json package.json
COPY ./src/payment/package-lock.json package-lock.json

RUN npm ci --omit=dev

# -----------------------------------------------------------------------------
# node:22-slim runtime (not distroless) so apt security upgrades apply for Trivy.

FROM docker.io/library/node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2

RUN apk upgrade --no-cache

# The runtime invokes node directly; remove package managers and their bundled
# dependency trees so build-only tooling is not part of the production image.
RUN rm -rf /usr/local/lib/node_modules/npm /opt/yarn-v* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg

WORKDIR /usr/src/app/

COPY --from=builder /usr/src/app/node_modules/ node_modules/

COPY ./pb/demo.proto demo.proto

COPY ./src/payment/charge.js charge.js
COPY ./src/payment/index.js index.js
COPY ./src/payment/logger.js logger.js
COPY ./src/payment/opentelemetry.js opentelemetry.js

RUN addgroup -g 10001 -S appgroup \
    && adduser -u 10001 -S -D -H -G appgroup appuser \
    && chown -R appuser:appgroup /usr/src/app

EXPOSE ${PAYMENT_PORT}

USER 10001
CMD ["node", "--require=./opentelemetry.js", "index.js"]
# Change trail: @hungxqt - 2026-07-20 - Node slim runtime + apt upgrade and protobufjs override for Trivy
