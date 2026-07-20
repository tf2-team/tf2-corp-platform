# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN groupadd --gid 10001 aiops \
    && useradd --uid 10001 --gid aiops --no-create-home --shell /usr/sbin/nologin aiops

COPY requirements.lock ./requirements.lock
RUN python -m pip install --requirement requirements.lock

COPY aiops ./aiops
COPY config ./config
COPY runbooks ./runbooks

RUN mkdir -p /app/state /tmp/matplotlib \
    && chown -R aiops:aiops /app/state /tmp/matplotlib

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "aiops.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
