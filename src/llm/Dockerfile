# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322 AS build-venv

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk upgrade --no-cache && apk add --no-cache gcc g++ linux-headers

COPY ./src/llm/requirements.txt requirements.txt

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    python -m venv venv && \
    venv/bin/pip install -r requirements.txt

FROM docker.io/library/python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322

RUN apk upgrade --no-cache

COPY --from=build-venv /venv/ /venv/

WORKDIR /app

RUN addgroup -g 10001 -S appgroup && \
    adduser -u 10001 -S -G appgroup appuser

COPY --chown=appuser:appgroup ./src/llm/app.py app.py
COPY --chown=appuser:appgroup ./src/llm/product-review-summaries/product-review-summaries.json product-review-summaries.json
COPY --chown=appuser:appgroup ./src/llm/product-review-summaries/inaccurate-product-review-summaries.json inaccurate-product-review-summaries.json

RUN chown -R appuser:appgroup /app

USER 10001

EXPOSE ${LLM_PORT}
ENTRYPOINT [ "/venv/bin/python", "app.py" ]
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
