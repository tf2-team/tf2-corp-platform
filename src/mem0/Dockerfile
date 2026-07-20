# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY src/mem0/requirements-production.txt /build/requirements-production.txt
RUN python -m pip install --prefix=/install --requirement /build/requirements-production.txt

# Install the pinned Git submodule source, never the mem0ai package from PyPI.
COPY third-party/mem0 /build/mem0
RUN python -m pip install --prefix=/install --no-deps /build/mem0


FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    MEM0_DIR=/tmp/.mem0 \
    HISTORY_DB_PATH=/app/history/history.db \
    FASTEMBED_CACHE_PATH=/models/fastembed \
    FASTEMBED_LOCAL_FILES_ONLY=true \
    MEM0_TELEMETRY=false

RUN groupadd --gid "${APP_GID}" mem0 \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home --shell /usr/sbin/nologin mem0 \
    && mkdir -p /app/server /app/history /models/fastembed \
    && chown -R "${APP_UID}:${APP_GID}" /app/history /models/fastembed

COPY --from=builder /install /usr/local
COPY --from=builder /build/mem0/server /app/server

WORKDIR /app/server
USER ${APP_UID}:${APP_GID}

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
