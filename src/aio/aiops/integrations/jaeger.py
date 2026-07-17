from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class JaegerClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._base_url = settings.jaeger_base_url.rstrip("/")
        self._http = HttpApiClient(settings.jaeger_base_url, token=settings.jaeger_token, account=settings.jaeger_account, transport=transport)

    def search_traces(self, service: str, limit: int = 20, start: int | None = None, end: int | None = None) -> dict:
        params = {"service": service, "limit": limit}
        if start is not None and end is not None:
            params.update({"start": start, "end": end})
        return self._http.get("/api/traces", params=params)

    def list_services(self) -> dict:
        return self._http.get("/api/services")

    def trace_ui_url(self, trace_id: str) -> str:
        return f"{self._base_url}/trace/{trace_id}"
