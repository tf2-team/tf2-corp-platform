# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS base

FROM base AS builder

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get -qq update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY ./src/load-generator/requirements.txt .
RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    pip install --prefix="/reqs" -r requirements.txt

FROM base
WORKDIR /usr/src/app/

RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser

COPY --from=builder /reqs /usr/local
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV XDG_CONFIG_HOME=/tmp/.config
RUN playwright install --with-deps chromium

COPY --chown=appuser:appgroup ./src/load-generator/locustfile.py .
COPY --chown=appuser:appgroup ./src/load-generator/people.json .

RUN chown -R appuser:appgroup /usr/src/app /opt/pw-browsers

USER 10001

ENTRYPOINT ["locust", "--skip-log-setup"]
