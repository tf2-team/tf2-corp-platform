# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/python:3.12-alpine3.22 AS build-venv

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk update && \
    apk add gcc g++ linux-headers

COPY ./src/recommendation/requirements.txt requirements.txt

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

COPY --chown=appuser:appgroup ./src/recommendation/demo_pb2_grpc.py demo_pb2_grpc.py
COPY --chown=appuser:appgroup ./src/recommendation/demo_pb2.py demo_pb2.py
COPY --chown=appuser:appgroup ./src/recommendation/logger.py logger.py
COPY --chown=appuser:appgroup ./src/recommendation/metrics.py metrics.py
COPY --chown=appuser:appgroup ./src/recommendation/recommendation_server.py recommendation_server.py

RUN chown -R appuser:appgroup /app

USER 10001

EXPOSE ${RECOMMENDATION_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "recommendation_server.py" ]
