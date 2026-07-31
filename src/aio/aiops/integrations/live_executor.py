#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
from uuid import uuid4

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient

logger = logging.getLogger(__name__)


class LiveExecutorClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.live_executor_url,
            token=settings.live_executor_token,
            account=settings.live_executor_account,
            transport=transport,
        )

    def catalog(self, request_id: str | None = None) -> list[dict]:
        return self._http.get("/v1/actions/catalog", headers=self._request_headers({"request_id": request_id}))

    def ready(self) -> bool:
        response = self._http.get("/readyz")
        return isinstance(response, dict) and response.get("status") == "ready"

    def plan(self, action: dict) -> dict:
        return self._post("/v1/actions/plan", action)

    def execute(self, action: dict) -> dict:
        return self._post("/v1/actions/execute", action)

    def status(self, execution_id: str, request_id: str | None = None) -> dict:
        return self._http.get(
            f"/v1/actions/{execution_id}",
            headers=self._request_headers({"request_id": request_id}),
        )

    def record_verification(self, execution_id: str, verification: dict) -> dict:
        return self._post(f"/v1/actions/{execution_id}/verification", verification)

    def rollback(self, execution_id: str, request: dict) -> dict:
        return self._post(f"/v1/actions/{execution_id}/rollback", request)

    def _post(self, path: str, payload: dict) -> dict:
        operation = path.rsplit("/", 1)[-1]
        logger.info(
            "AIOPS_EXECUTOR_API_CALL operation=%s incident=%s runbook=%s action_type=%s target=%s",
            operation,
            payload.get("incident_id", "unknown"),
            payload.get("runbook_id", "unknown"),
            payload.get("action_type", "unknown"),
            payload.get("target", "unknown"),
        )
        request_payload = dict(payload)
        # Runtime context and policy metadata below are not part of the
        # executor's strict request models. Keep them out of the HTTP body.
        request_payload.pop("runbook_id", None)
        if operation in {"verification", "rollback"}:
            request_payload.pop("action_type", None)
            request_payload.pop("target", None)
        if operation == "rollback":
            request_payload.pop("policy_id", None)
            request_payload.pop("policy_approved", None)
            request_payload.pop("policy_expires_at", None)
        try:
            return self._http.post(
                path,
                json=request_payload,
                headers=self._request_headers(request_payload),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            decoded = self._http._decode_response(exc.response)
            if not isinstance(decoded, dict):
                raise
            return decoded

    @staticmethod
    def _request_headers(payload: dict) -> dict[str, str]:
        request_id = payload.get("request_id") or str(uuid4())
        return {"X-Request-Id": str(request_id)}

    def close(self) -> None:
        self._http.close()
