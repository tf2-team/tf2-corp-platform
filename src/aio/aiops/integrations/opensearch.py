from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class OpenSearchClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.opensearch_base_url,
            account=settings.opensearch_account,
            basic_auth=(settings.opensearch_username, settings.opensearch_password),
            verify_tls=settings.opensearch_verify_tls,
            transport=transport,
        )

    def info(self) -> dict:
        return self._http.get("/")

    def list_indices(self) -> list[dict]:
        return self._http.get("/_cat/indices", params={"format": "json"})

    def search(self, index: str, body: dict) -> dict:
        return self._http.post(f"/{index}/_search", json=body)

