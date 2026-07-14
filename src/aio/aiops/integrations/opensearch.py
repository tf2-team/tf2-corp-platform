from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class OpenSearchClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.opensearch_base_url,
            token=settings.opensearch_password,
            account=settings.opensearch_account or settings.opensearch_username,
            transport=transport,
        )

    def search(self, index: str, body: dict) -> dict:
        return self._http.post(f"/{index}/_search", json=body)
