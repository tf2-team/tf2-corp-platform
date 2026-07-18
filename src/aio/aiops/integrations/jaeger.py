from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class JaegerClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(settings.jaeger_base_url, token=settings.jaeger_token, account=settings.jaeger_account, transport=transport)

    def search_traces(self, service: str, limit: int = 20) -> dict:
        return self._http.get("/api/traces", params={"service": service, "limit": limit})

    def list_services(self) -> dict:
        return self._http.get("/api/services")

