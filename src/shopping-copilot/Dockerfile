# syntax=docker/dockerfile:1.7
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM docker.io/library/python:3.12-slim-bookworm AS build-venv

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && \
    apt-get install --no-install-recommends -y gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY ./src/shopping-copilot/requirements.txt requirements.txt

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    python -m venv venv && \
    venv/bin/pip install -r requirements.txt

RUN --mount=type=cache,id=techx-pip-cache,target=/root/.cache/pip,sharing=locked \
    venv/bin/opentelemetry-bootstrap -a install

FROM docker.io/library/python:3.12-slim-bookworm

RUN apt-get update && \
    apt-get install --no-install-recommends -y libgomp1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build-venv /venv/ /venv/

WORKDIR /app

RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --no-create-home appuser && \
    mkdir -p /home/appuser/.cache/huggingface && \
    chown -R appuser:appgroup /home/appuser

ENV HF_HOME=/home/appuser/.cache/huggingface

# Copy generated proto stubs
COPY --chown=appuser:appgroup ./src/product-reviews/demo_pb2_grpc.py demo_pb2_grpc.py
COPY --chown=appuser:appgroup ./src/product-reviews/demo_pb2.py demo_pb2.py

# Copy shared AI code from product-reviews for Docker build
COPY --chown=appuser:appgroup ./src/product-reviews/ai_contracts.py ai_contracts.py
COPY --chown=appuser:appgroup ./src/product-reviews/guardrails.py guardrails.py
COPY --chown=appuser:appgroup ./src/product-reviews/grounding.py grounding.py

# Copy shopping-copilot service code
COPY --chown=appuser:appgroup ./src/shopping-copilot/copilot_contracts.py copilot_contracts.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/bedrock_runtime.py bedrock_runtime.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/bedrock_grounding.py bedrock_grounding.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/intent_parser.py intent_parser.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/catalog_tool.py catalog_tool.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/review_tool.py review_tool.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/cart_tool.py cart_tool.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/copilot_graph.py copilot_graph.py
COPY --chown=appuser:appgroup ./src/shopping-copilot/copilot_server.py copilot_server.py

RUN /venv/bin/python -c "import guardrails, grounding"

RUN chown -R appuser:appgroup /app

USER 10001

EXPOSE ${SHOPPING_COPILOT_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "copilot_server.py" ]
