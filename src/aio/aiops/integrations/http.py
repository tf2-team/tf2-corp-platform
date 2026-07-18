from __future__ import annotations

from typing import Any

import httpx


def safe_error_text(exc: Exception) -> str:
    """Return an operator-facing error without request URLs or credentials.

    ``httpx`` status errors include the complete request URL in their default
    string representation. That is unsafe for notification webhooks because a
    webhook token is commonly embedded in the URL path.
    """

    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{name}: HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"{name}: request failed"
    return f"{name}: operation failed"


class HttpApiClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        account: str = "",
        basic_auth: tuple[str, str] | None = None,
        verify_tls: bool = True,
        transport: httpx.BaseTransport | None = None,
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
            timeout=10.0,
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

