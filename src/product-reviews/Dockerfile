# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS build-venv

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install --no-install-recommends -y gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY ./src/ai-common /build/ai-common
COPY ./src/product-reviews/requirements.txt requirements.txt

RUN python -m venv venv && \
    venv/bin/pip install --no-cache-dir /build/ai-common && \
    venv/bin/pip install --no-cache-dir -r requirements.txt

RUN venv/bin/python -c "import spacy; spacy.load('en_core_web_lg')"

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    venv/bin/opentelemetry-bootstrap -a install
FROM docker.io/library/python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install --no-install-recommends -y libgomp1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build-venv /venv/ /venv/

WORKDIR /app

RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --no-create-home appuser && \
    mkdir -p /home/appuser/.cache/huggingface && \
    chown -R appuser:appgroup /home/appuser

ENV HF_HOME=/home/appuser/.cache/huggingface

COPY --chown=appuser:appgroup ./src/product-reviews/product_reviews_server.py product_reviews_server.py
COPY --chown=appuser:appgroup ./src/product-reviews/database.py database.py
COPY --chown=appuser:appgroup ./src/product-reviews/metrics.py metrics.py

RUN /venv/bin/python -c "from techx_ai_common import guardrails, grounding; import spacy; spacy.load('en_core_web_lg')"

RUN chown -R appuser:appgroup /app

USER 10001

EXPOSE ${PRODUCT_REVIEWS_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "product_reviews_server.py" ]
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
