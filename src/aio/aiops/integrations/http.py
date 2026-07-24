#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import ssl
from typing import Any

import httpx


class HttpApiClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        account: str = "",
        basic_auth: tuple[str, str] | None = None,
        verify_tls: bool | ssl.SSLContext = True,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account:
            headers["X-AIOps-Account"] = account
        auth = httpx.BasicAuth(*basic_auth) if basic_auth else None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            auth=auth,
            verify=verify_tls,
            transport=transport,
            timeout=timeout,
        )

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        if not response.content:
            return {"status_code": response.status_code}
        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "text": response.text}

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return self._decode_response(response)

    def post(self, path: str, json: dict[str, Any]) -> Any:
        response = self._client.post(path, json=json)
        response.raise_for_status()
        return self._decode_response(response)

    def patch(self, path: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        response = self._client.patch(path, json=json, headers=headers)
        response.raise_for_status()
        return self._decode_response(response)
