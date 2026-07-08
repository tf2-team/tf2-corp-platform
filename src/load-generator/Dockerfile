# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM python:3.12-slim-bookworm AS base

FROM base AS builder
RUN apt-get -qq update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY ./src/load-generator/requirements.txt .
RUN pip install --prefix="/reqs" -r requirements.txt

FROM base
WORKDIR /usr/src/app/

RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser

COPY --from=builder /reqs /usr/local
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install --with-deps chromium

COPY --chown=appuser:appgroup ./src/load-generator/locustfile.py .
COPY --chown=appuser:appgroup ./src/load-generator/people.json .

RUN chown -R appuser:appgroup /usr/src/app /opt/pw-browsers

USER 10001

ENTRYPOINT ["locust", "--skip-log-setup"]
