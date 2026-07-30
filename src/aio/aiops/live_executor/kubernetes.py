#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any, Protocol

import httpx


class DeploymentGateway(Protocol):
    def snapshot(self, namespace: str, name: str) -> dict[str, Any]: ...

    def scale(
        self,
        namespace: str,
        name: str,
        replicas: int,
        resource_version: str,
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class KubernetesDeploymentGateway:
    """Namespace-scoped deployment access for the executor service.

    The caller must still be constrained by Kubernetes RBAC. Optimistic
    concurrency is enforced by including the planned resourceVersion in each
    mutation request.
    """

    def __init__(
        self,
        api_url: str,
        *,
        bearer_token: str = "",
        bearer_token_file: Path | None = None,
        ca_cert_path: Path | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        token = bearer_token
        if not token and bearer_token_file is not None and bearer_token_file.is_file():
            token = bearer_token_file.read_text(encoding="utf-8").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        verify: bool | ssl.SSLContext = True
        if ca_cert_path is not None and ca_cert_path.is_file():
            verify = ssl.create_default_context(cafile=str(ca_cert_path))
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers=headers,
            verify=verify,
            timeout=timeout_seconds,
            transport=transport,
        )

    def snapshot(self, namespace: str, name: str) -> dict[str, Any]:
        deployment_response = self._client.get(self._deployment_path(namespace, name))
        deployment_response.raise_for_status()
        deployment = deployment_response.json()
        autoscaler = self._get_horizontal_pod_autoscaler(namespace, name)
        return self._snapshot_from_resources(deployment, autoscaler)

    def scale(
        self,
        namespace: str,
        name: str,
        replicas: int,
        resource_version: str,
    ) -> dict[str, Any]:
        autoscaler = self._get_horizontal_pod_autoscaler(namespace, name)
        if autoscaler is not None:
            maximum = int((autoscaler.get("spec") or {}).get("maxReplicas") or 0)
            if replicas > maximum:
                raise ValueError("requested replicas exceed autoscaler maximum")
            response = self._client.patch(
                self._horizontal_pod_autoscaler_path(namespace, name),
                headers={"Content-Type": "application/merge-patch+json"},
                json={
                    "metadata": {"resourceVersion": resource_version},
                    "spec": {"minReplicas": replicas},
                },
            )
            response.raise_for_status()
            deployment_response = self._client.get(self._deployment_path(namespace, name))
            deployment_response.raise_for_status()
            return self._snapshot_from_resources(deployment_response.json(), response.json())

        response = self._client.patch(
            self._deployment_path(namespace, name),
            headers={"Content-Type": "application/merge-patch+json"},
            json={
                "metadata": {"resourceVersion": resource_version},
                "spec": {"replicas": replicas},
            },
        )
        response.raise_for_status()
        return self._snapshot_from_resources(response.json(), None)

    @staticmethod
    def _deployment_path(namespace: str, name: str) -> str:
        return f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}"

    @staticmethod
    def _horizontal_pod_autoscaler_path(namespace: str, name: str) -> str:
        return f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers/{name}"

    def _get_horizontal_pod_autoscaler(self, namespace: str, name: str) -> dict[str, Any] | None:
        response = self._client.get(self._horizontal_pod_autoscaler_path(namespace, name))
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _snapshot_from_resources(
        deployment: dict[str, Any],
        autoscaler: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = deployment.get("metadata") or {}
        spec = deployment.get("spec") or {}
        status = deployment.get("status") or {}
        snapshot = {
            "kind": deployment.get("kind", "Deployment"),
            "namespace": metadata.get("namespace"),
            "name": metadata.get("name"),
            "replicas": int(spec.get("replicas") or 0),
            "ready_replicas": int(status.get("readyReplicas") or 0),
            "scaling_controller": "Deployment",
            "control_replicas": int(spec.get("replicas") or 0),
            "resource_version": str(metadata.get("resourceVersion") or ""),
        }
        if autoscaler is None:
            return snapshot

        autoscaler_metadata = autoscaler.get("metadata") or {}
        autoscaler_spec = autoscaler.get("spec") or {}
        autoscaler_status = autoscaler.get("status") or {}
        snapshot.update(
            {
                "replicas": int(
                    autoscaler_status.get("currentReplicas")
                    or autoscaler_status.get("desiredReplicas")
                    or snapshot["replicas"]
                ),
                "scaling_controller": "HorizontalPodAutoscaler",
                "control_replicas": int(autoscaler_spec.get("minReplicas") or 1),
                "autoscaler_max_replicas": int(autoscaler_spec.get("maxReplicas") or 0),
                "autoscaler_name": autoscaler_metadata.get("name"),
                "deployment_resource_version": snapshot["resource_version"],
                "resource_version": str(autoscaler_metadata.get("resourceVersion") or ""),
            }
        )
        return snapshot

    def close(self) -> None:
        self._client.close()
