#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aiops.live_executor.kubernetes import KubernetesDeploymentGateway
from aiops.live_executor.service import DEFAULT_ENVIRONMENT, POLICY_EXPIRES_AT, POLICY_ID, LiveExecutorService
from runbooks.actions.common import AUTHORIZED_REQUESTER, DEFAULT_KUBERNETES_API_URL, DEFAULT_KUBERNETES_CA_CERT_PATH


DEFAULT_STORE_PATH = Path("state/live_executor.sqlite3")


class RootCauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = ""
    score: float = Field(default=0, ge=0)
    metrics: list[str] = Field(default_factory=list)
    evidence_scores: dict[str, float] = Field(default_factory=dict)


class SafetyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protected_targets: list[str] = Field(default_factory=list)
    blast_radius_services: list[str] = Field(default_factory=list)
    cost_status_current: bool = False


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    request_id: str = Field(min_length=8)
    incident_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    action_type: str
    target: str = Field(min_length=1)
    target_kind: str
    namespace: str = Field(min_length=1)
    replicas: int | None = Field(default=None, ge=0)
    policy_id: str = Field(min_length=1)
    policy_approved: bool
    policy_expires_at: str | None = None
    approval_id: str | None = None
    plan_hash: str | None = None
    rollback_token: str | None = None
    idempotency_key: str = Field(min_length=16)
    reason: str = Field(min_length=1)
    requested_by: str
    dry_run: bool
    root_cause: RootCauseRequest | None = None
    safety: SafetyRequest | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str) -> str:
        if value not in {"scale_deployment", "restore_deployment_replicas", "restart_deployment", "page"}:
            raise ValueError("unsupported action type")
        return value

    @field_validator("target_kind")
    @classmethod
    def validate_target_kind(cls, value: str) -> str:
        if value not in {"Deployment", "OnCall"}:
            raise ValueError("unsupported target kind")
        return value

    @field_validator("requested_by")
    @classmethod
    def validate_requester(cls, value: str) -> str:
        if value != AUTHORIZED_REQUESTER:
            raise ValueError("unsupported requester")
        return value

    @field_validator("policy_expires_at")
    @classmethod
    def validate_policy_expiry(cls, value: str | None) -> str | None:
        if value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8)
    incident_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=16)
    passed: bool
    query_id: str | None = None
    message: str | None = None
    requested_by: str = AUTHORIZED_REQUESTER


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8)
    incident_id: str = Field(min_length=1)
    rollback_token: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requested_by: str = AUTHORIZED_REQUESTER
    idempotency_key: str = Field(min_length=16)


def _configured_token() -> str:
    return os.getenv("AIOPS_LIVE_EXECUTOR_TOKEN", "")


def _store_path() -> Path:
    return Path(os.getenv("AIOPS_LIVE_EXECUTOR_STORE_PATH", str(DEFAULT_STORE_PATH)))


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_service() -> LiveExecutorService:
    allow_live_apply = _env_flag("AIOPS_LIVE_EXECUTOR_ALLOW_LIVE_APPLY")
    gateway = None
    if allow_live_apply:
        gateway = KubernetesDeploymentGateway(
            os.getenv("AIOPS_KUBERNETES_API_URL", DEFAULT_KUBERNETES_API_URL),
            bearer_token=os.getenv("AIOPS_KUBERNETES_BEARER_TOKEN", ""),
            bearer_token_file=Path(
                os.getenv(
                    "AIOPS_KUBERNETES_BEARER_TOKEN_FILE",
                    "/var/run/secrets/kubernetes.io/serviceaccount/token",
                )
            ),
            ca_cert_path=Path(
                os.getenv(
                    "AIOPS_KUBERNETES_CA_CERT_PATH",
                    DEFAULT_KUBERNETES_CA_CERT_PATH,
                )
            ),
            timeout_seconds=float(os.getenv("AIOPS_LIVE_EXECUTOR_KUBERNETES_TIMEOUT_SECONDS", "10")),
        )
    return LiveExecutorService.from_path(
        _store_path(),
        deployment_gateway=gateway,
        allow_live_apply=allow_live_apply,
        cooldown_seconds=int(os.getenv("AIOPS_LIVE_EXECUTOR_COOLDOWN_SECONDS", "900")),
        action_budget_window_seconds=int(os.getenv("AIOPS_LIVE_EXECUTOR_ACTION_BUDGET_WINDOW_SECONDS", "3600")),
        action_budget_max_executions=int(os.getenv("AIOPS_LIVE_EXECUTOR_ACTION_BUDGET_MAX_EXECUTIONS", "10")),
        policy_id=os.getenv("AIOPS_LIVE_EXECUTOR_POLICY_ID", POLICY_ID),
        policy_expires_at=os.getenv("AIOPS_LIVE_EXECUTOR_POLICY_EXPIRES_AT", POLICY_EXPIRES_AT),
        approval_id=os.getenv("AIOPS_LIVE_EXECUTOR_APPROVAL_ID", ""),
        environment=os.getenv("AIOPS_ENVIRONMENT", DEFAULT_ENVIRONMENT),
    )


def create_app(service: LiveExecutorService | None = None, token: str | None = None) -> FastAPI:
    service = service or _build_service()
    expected_token = token if token is not None else _configured_token()
    if service.allow_live_apply and not expected_token:
        raise RuntimeError("live executor token is required when live apply is enabled")
    if service.allow_live_apply and not service.approval_id:
        raise RuntimeError("live executor approval id is required when live apply is enabled")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="AIOps Live Executor", lifespan=lifespan)
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
        if expected_token and x_aiops_account != AUTHORIZED_REQUESTER:
            raise HTTPException(status_code=403, detail="invalid executor account")

    def require_matching_request_id(header_request_id: str, body_request_id: str) -> None:
        if expected_token and not hmac.compare_digest(header_request_id, body_request_id):
            raise HTTPException(status_code=400, detail="request id header does not match body")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        try:
            service.catalog()
            service.service_catalog()
            ready = service.ready()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="executor dependencies are not ready") from exc
        if not ready:
            raise HTTPException(status_code=503, detail="executor store is not ready")
        return {"status": "ready"}

    @app.get("/v1/actions/catalog", dependencies=[Depends(require_auth)])
    def catalog() -> list[dict[str, Any]]:
        return service.catalog()

    @app.get("/v1/services/catalog", dependencies=[Depends(require_auth)])
    def services_catalog() -> list[dict[str, Any]]:
        return service.service_catalog()

    @app.post("/v1/actions/plan", dependencies=[Depends(require_auth)])
    def plan(request: ActionRequest, x_request_id: str = Header(default="")) -> dict[str, Any]:
        require_matching_request_id(x_request_id, request.request_id)
        return service.plan(request.model_dump())

    @app.post("/v1/actions/execute", dependencies=[Depends(require_auth)])
    def execute(request: ActionRequest, x_request_id: str = Header(default="")) -> dict[str, Any]:
        require_matching_request_id(x_request_id, request.request_id)
        return service.execute(request.model_dump())

    @app.get("/v1/actions/{execution_id}", dependencies=[Depends(require_auth)])
    def status(execution_id: str) -> dict[str, Any]:
        return service.status(execution_id)

    @app.post("/v1/actions/{execution_id}/verification", dependencies=[Depends(require_auth)])
    def verification(
        execution_id: str,
        request: VerificationRequest,
        x_request_id: str = Header(default=""),
    ) -> dict[str, Any]:
        require_matching_request_id(x_request_id, request.request_id)
        return service.record_verification(execution_id, request.model_dump())

    @app.post("/v1/actions/{execution_id}/rollback", dependencies=[Depends(require_auth)])
    def rollback(
        execution_id: str,
        request: RollbackRequest,
        x_request_id: str = Header(default=""),
    ) -> dict[str, Any]:
        require_matching_request_id(x_request_id, request.request_id)
        return service.rollback(execution_id, request.model_dump())

    return app
