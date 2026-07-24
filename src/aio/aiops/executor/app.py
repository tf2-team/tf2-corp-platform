#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hmac
import sqlite3
from datetime import UTC, datetime
from threading import Lock

from fastapi import FastAPI, Header, HTTPException
from pydantic import Field

from aiops.config import Settings
from aiops.integrations import KubernetesClient
from aiops.schemas import AiopsModel, HealthResponse


class ExecutorActionRequest(AiopsModel):
    operation: str
    incident_id: str
    action_id: str
    target: str
    target_kind: str
    idempotency_key: str
    action_type: str | None = None
    replicas: int | None = None
    rollback: dict = Field(default_factory=dict)


class ExecutorState:
    def __init__(self, settings: Settings):
        self.path = settings.executor_state_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS executor_results (
                    idempotency_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def get(self, key: str) -> dict | None:
        import json

        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT response_json FROM executor_results WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        finally:
            connection.close()
        return json.loads(row[0]) if row else None

    def put(self, key: str, response: dict) -> None:
        import json

        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "INSERT OR IGNORE INTO executor_results (idempotency_key, response_json, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(response, sort_keys=True), datetime.now(UTC).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()


def create_executor_app(
    settings: Settings | None = None,
    kubernetes: KubernetesClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    kubernetes = kubernetes or KubernetesClient(settings)
    state = ExecutorState(settings)
    allowed_targets = {
        target.strip()
        for target in settings.executor_allowed_targets.split(",")
        if target.strip()
    }
    action_lock = Lock()
    app = FastAPI(title="AIOps Scoped Executor")

    @app.get("/health/live", response_model=HealthResponse)
    def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/actions")
    def actions(
        request: ExecutorActionRequest,
        authorization: str = Header(default=""),
    ) -> dict:
        _authorize(settings, authorization)
        with action_lock:
            cached = state.get(request.idempotency_key)
            if cached is not None:
                return cached
            _validate_scope(request, settings, allowed_targets)
            response = _apply(request, settings, kubernetes)
            state.put(request.idempotency_key, response)
            return response

    return app


def _authorize(settings: Settings, authorization: str) -> None:
    expected = settings.executor_shared_secret.strip()
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="executor secret is not configured")
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="invalid executor credential")


def _validate_scope(request: ExecutorActionRequest, settings: Settings, allowed_targets: set[str]) -> None:
    if request.operation not in {"dry-run", "execute", "rollback"}:
        raise HTTPException(status_code=422, detail="unsupported operation")
    if request.target_kind != "Deployment":
        raise HTTPException(status_code=422, detail="only Deployment targets are supported")
    if request.target not in allowed_targets:
        raise HTTPException(status_code=403, detail="target is outside executor allowlist")
    if request.replicas is not None and not 1 <= request.replicas <= settings.executor_max_replicas:
        raise HTTPException(status_code=422, detail="replica count is outside allowed range")


def _apply(request: ExecutorActionRequest, settings: Settings, kubernetes: KubernetesClient) -> dict:
    if request.operation == "rollback":
        patch = _rollback_patch(request.rollback, settings.executor_max_replicas)
        kubernetes.patch_deployment(settings.executor_namespace, request.target, patch)
        return {"status": "rolled-back", "target": request.target}

    deployment = kubernetes.get_deployment(settings.executor_namespace, request.target)
    patch, rollback = _action_patch(request, deployment)
    if request.operation == "dry-run":
        return {
            "status": "validated",
            "target": request.target,
            "action_type": request.action_type,
            "rollback": rollback,
        }
    kubernetes.patch_deployment(settings.executor_namespace, request.target, patch)
    return {
        "status": "succeeded",
        "target": request.target,
        "action_type": request.action_type,
        "rollback": rollback,
    }


def _action_patch(request: ExecutorActionRequest, deployment: dict) -> tuple[dict, dict]:
    if request.action_type == "restart":
        annotations = (
            deployment.get("spec", {})
            .get("template", {})
            .get("metadata", {})
            .get("annotations", {})
        )
        previous = dict(annotations)
        updated = dict(previous)
        updated["aiops.techx.io/restarted-at"] = datetime.now(UTC).isoformat()
        return (
            {"spec": {"template": {"metadata": {"annotations": updated}}}},
            {"action_type": "restart", "annotations": previous},
        )
    if request.action_type == "scale":
        previous = int(deployment.get("spec", {}).get("replicas", 1))
        replicas = request.replicas
        if replicas is None:
            raise HTTPException(status_code=422, detail="scale action requires replicas")
        return (
            {"spec": {"replicas": replicas}},
            {"action_type": "scale", "replicas": previous},
        )
    raise HTTPException(status_code=422, detail="unsupported action type")


def _rollback_patch(rollback: dict, max_replicas: int) -> dict:
    action_type = rollback.get("action_type")
    if action_type == "restart" and isinstance(rollback.get("annotations"), dict):
        annotations = {"$patch": "replace", **rollback["annotations"]}
        return {"spec": {"template": {"metadata": {"annotations": annotations}}}}
    if action_type == "scale" and isinstance(rollback.get("replicas"), int):
        replicas = rollback["replicas"]
        if 1 <= replicas <= max_replicas:
            return {"spec": {"replicas": replicas}}
    raise HTTPException(status_code=422, detail="invalid rollback payload")
