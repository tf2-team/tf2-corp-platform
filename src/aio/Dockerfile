# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

ARG PYTHON_IMAGE=docker.io/library/python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

FROM ${PYTHON_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /venv
ENV PATH="/venv/bin:${PATH}"

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --requirement /tmp/requirements.lock

WORKDIR /build
COPY pyproject.toml README.md ./
COPY aiops ./aiops
RUN pip install --no-deps .

FROM ${PYTHON_IMAGE} AS runtime

ARG AIOPS_BUILD_REVISION=unknown
ENV AIOPS_BUILD_REVISION=${AIOPS_BUILD_REVISION} \
    AIOPS_PORT=8080 \
    PATH="/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 aiops && \
    useradd --uid 10001 --gid aiops --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin aiops && \
    mkdir -p /app/state /app/evidence && \
    chown -R aiops:aiops /app

COPY --from=build /venv /venv
COPY --chown=aiops:aiops config /app/config
COPY --chown=aiops:aiops runbooks /app/runbooks

WORKDIR /app
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('AIOPS_PORT', '8080') + '/health/live', timeout=2)"]

ENTRYPOINT ["aiops-api"]
