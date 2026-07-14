from __future__ import annotations

from typing import Any

import httpx


class HttpApiClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        account: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account:
            headers["X-AIOps-Account"] = account
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, transport=transport, timeout=10.0)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=json)
        response.raise_for_status()
        return response.json()
