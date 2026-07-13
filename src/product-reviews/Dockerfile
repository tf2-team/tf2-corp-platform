# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/python:3.12-alpine3.22 AS build-venv

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk update && \
    apk add gcc g++ linux-headers

COPY ./src/product-reviews/requirements.txt requirements.txt

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    python -m venv venv && \
    venv/bin/pip install -r requirements.txt

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    venv/bin/opentelemetry-bootstrap -a install

FROM docker.io/library/python:3.12-alpine3.22

COPY --from=build-venv /venv/ /venv/

WORKDIR /app

RUN addgroup -g 10001 -S appgroup && \
    adduser -u 10001 -S -G appgroup appuser

COPY --chown=appuser:appgroup ./src/product-reviews/demo_pb2_grpc.py demo_pb2_grpc.py
COPY --chown=appuser:appgroup ./src/product-reviews/demo_pb2.py demo_pb2.py
COPY --chown=appuser:appgroup ./src/product-reviews/product_reviews_server.py product_reviews_server.py
COPY --chown=appuser:appgroup ./src/product-reviews/database.py database.py
COPY --chown=appuser:appgroup ./src/product-reviews/metrics.py metrics.py

RUN chown -R appuser:appgroup /app

USER 10001

EXPOSE ${PRODUCT_REVIEWS_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "product_reviews_server.py" ]
