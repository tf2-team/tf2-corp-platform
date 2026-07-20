# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM python:3.12-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS base

RUN apt-get -qq update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

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
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
