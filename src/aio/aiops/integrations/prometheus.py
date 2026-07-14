from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class PrometheusClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.prometheus_base_url,
            token=settings.prometheus_token,
            account=settings.prometheus_account,
            transport=transport,
        )

    def query(self, query: str) -> dict:
        return self._http.get("/api/v1/query", params={"query": query})

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        return self._http.get("/api/v1/query_range", params={"query": query, "start": start, "end": end, "step": step})
