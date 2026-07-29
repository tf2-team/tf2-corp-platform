#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from aiops.live_executor.service import LiveExecutorService


DEFAULT_STORE_PATH = Path("state/live_executor.sqlite3")


def _configured_token() -> str:
    return os.getenv("AIOPS_LIVE_EXECUTOR_TOKEN", "")


def _store_path() -> Path:
    return Path(os.getenv("AIOPS_LIVE_EXECUTOR_STORE_PATH", str(DEFAULT_STORE_PATH)))


def create_app(service: LiveExecutorService | None = None, token: str | None = None) -> FastAPI:
    service = service or LiveExecutorService.from_path(_store_path())
    expected_token = token if token is not None else _configured_token()
    app = FastAPI(title="AIOps Live Executor")
    app.state.live_executor_service = service

    def require_auth(
        authorization: str = Header(default=""),
        x_aiops_account: str = Header(default=""),
        x_request_id: str = Header(default=""),
    ) -> None:
        if expected_token:
            expected = f"Bearer {expected_token}"
            if not hmac.compare_digest(authorization, expected):
                raise HTTPException(status_code=401, detail="invalid executor token")
        if expected_token and (not x_aiops_account or not x_request_id):
            raise HTTPException(status_code=400, detail="missing executor auth context")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        service.catalog()
        service.service_catalog()
        return {"status": "ready"}

    @app.get("/v1/actions/catalog", dependencies=[Depends(require_auth)])
    def catalog() -> list[dict[str, Any]]:
        return service.catalog()

    @app.get("/v1/services/catalog", dependencies=[Depends(require_auth)])
    def services_catalog() -> list[dict[str, Any]]:
        return service.service_catalog()

    @app.post("/v1/actions/plan", dependencies=[Depends(require_auth)])
    def plan(request: dict[str, Any]) -> dict[str, Any]:
        return service.plan(request)

    @app.post("/v1/actions/execute", dependencies=[Depends(require_auth)])
    def execute(request: dict[str, Any]) -> dict[str, Any]:
        return service.execute(request)

    @app.get("/v1/actions/{execution_id}", dependencies=[Depends(require_auth)])
    def status(execution_id: str) -> dict[str, Any]:
        return service.status(execution_id)

    @app.post("/v1/actions/{execution_id}/rollback", dependencies=[Depends(require_auth)])
    def rollback(execution_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return service.rollback(execution_id, request)

    @app.post("/actions", dependencies=[Depends(require_auth)])
    def legacy_actions(request: dict[str, Any]) -> dict[str, Any]:
        return service.legacy_submit(request)

    return app
