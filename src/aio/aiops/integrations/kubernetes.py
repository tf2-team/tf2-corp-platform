#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import ssl

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class KubernetesClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        token = settings.kubernetes_bearer_token
        if not token and settings.kubernetes_bearer_token_file.is_file():
            token = settings.kubernetes_bearer_token_file.read_text(encoding="utf-8").strip()
        verify: bool | ssl.SSLContext = True
        if settings.kubernetes_ca_cert_path.is_file():
            verify = ssl.create_default_context(cafile=str(settings.kubernetes_ca_cert_path))
        self._http = HttpApiClient(
            settings.kubernetes_api_url,
            token=token,
            account=settings.kubernetes_account,
            verify_tls=verify,
            transport=transport,
        )

    def get_deployment(self, namespace: str, name: str) -> dict:
        return self._http.get(f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}")

    def list_pods(self, namespace: str) -> dict:
        return self._http.get(f"/api/v1/namespaces/{namespace}/pods")

    def patch_deployment(self, namespace: str, name: str, patch: dict) -> dict:
        return self._http.patch(
            f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}",
            json=patch,
            headers={"Content-Type": "application/strategic-merge-patch+json"},
        )

