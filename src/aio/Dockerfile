FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt ./
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system aiops \
    && useradd --system --gid aiops --home-dir /app aiops \
    && mkdir -p /app/state /app/evidence \
    && chown -R aiops:aiops /app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

WORKDIR /app
COPY --chown=aiops:aiops aiops ./aiops
COPY --chown=aiops:aiops config ./config
COPY --chown=aiops:aiops runbooks ./runbooks

USER aiops
ENTRYPOINT ["python", "-m", "aiops.serve"]
