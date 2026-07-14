from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class KubernetesClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.kubernetes_api_url,
            token=settings.kubernetes_bearer_token,
            account=settings.kubernetes_account,
            transport=transport,
        )

    def get_deployment(self, namespace: str, name: str) -> dict:
        return self._http.get(f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}")

    def list_pods(self, namespace: str) -> dict:
        return self._http.get(f"/api/v1/namespaces/{namespace}/pods")
