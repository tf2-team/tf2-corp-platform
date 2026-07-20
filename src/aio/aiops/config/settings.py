#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files() -> str | tuple[str, str]:
    override = os.getenv("AIOPS_ENV_FILE", "").strip()
    return (".env", override) if override and override != ".env" else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_prefix="AIOPS_",
        extra="ignore",
    )

    app_title: str = "AIOps Runtime"
    api_health_live_path: str = "/health/live"
    api_pipeline_run_path: str = "/api/v1/pipeline/run"
    health_status: str = "ok"

    environment: str = "techx-corp-prod"
    policy_mode: str = "dry-run"
    evidence_dir: Path = Path("evidence")
    state_store_path: Path = Path("state/aiops.sqlite3")
    runtime_config_path: Path = Path("config/runtime.json")
    hyperparameters_path: Path = Path("config/hyperparameters.json")
    actions_catalog_path: Path = Path("config/actions.json")
    incidents_history_path: Path = Path("config/incidents_history.json")
    remediation_audit_path: Path = Path("state/remediation_audit.jsonl")
    rca_history_path: Path = Path("state/rca_history.jsonl")

    qualification_gate_dev: bool = False
    qualification_schema_path: Path = Path("config/signal_qualification_schema.json")
    normalization_schema_path: Path = Path("config/signal_normalization_schema.json")
    qualification_max_sample_age_seconds: int = 300
    auto_run_enabled: bool = False
    auto_run_interval_seconds: int = 60

    action_type_restart: str = "restart"
    action_target_kind_deployment: str = "Deployment"
    default_action_replicas: int = 3
    prometheus_base_url: str = ""
    prometheus_token: str = ""
    prometheus_account: str = ""

    grafana_webhook_secret: str = ""

    jaeger_base_url: str = ""
    jaeger_token: str = ""
    jaeger_account: str = ""

    opensearch_base_url: str = ""
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_account: str = ""
    opensearch_verify_tls: bool = True

    kubernetes_api_url: str = ""
    kubernetes_bearer_token: str = ""
    kubernetes_bearer_token_file: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    kubernetes_ca_cert_path: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    kubernetes_account: str = ""

    notification_webhook_url: str = ""
    notification_token: str = ""
    notification_account: str = ""
    notification_provider: Literal["auto", "generic", "grafana", "discord"] = "auto"

    aie_status_url: str = ""
    aie_token: str = ""
    aie_account: str = ""

    cdo_cost_url: str = ""
    cdo_cost_token: str = ""
    cdo_cost_account: str = ""

    live_executor_url: str = ""
    live_executor_token: str = ""
    live_executor_account: str = ""
