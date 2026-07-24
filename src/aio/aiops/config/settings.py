#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_STATE_STORE_PATH = Path("state/aiops.sqlite3")
DEFAULT_REMEDIATION_AUDIT_PATH = Path("state/remediation_audit.jsonl")
DEFAULT_RCA_HISTORY_PATH = Path("state/rca_history.jsonl")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    state_store_path: Path = DEFAULT_STATE_STORE_PATH
    runtime_config_path: Path = Path("config/runtime.json")
    prometheus_registry_path: Path = Path("config/prometheus_queries.json")
    hyperparameters_path: Path = Path("config/hyperparameters.json")
    actions_catalog_path: Path = Path("config/actions.json")
    incidents_history_path: Path = Path("config/incidents_history.json")
    remediation_audit_path: Path = DEFAULT_REMEDIATION_AUDIT_PATH
    rca_history_path: Path = DEFAULT_RCA_HISTORY_PATH

    qualification_gate_dev: bool = False
    qualification_schema_path: Path = Path("config/signal_qualification_schema.json")
    normalization_schema_path: Path = Path("config/signal_normalization_schema.json")
    qualification_max_sample_age_seconds: int = 300
    auto_run_enabled: bool = False
    auto_run_interval_seconds: int = 60
    closed_loop_enabled: bool = False
    live_action_approved: bool = False
    action_cooldown_seconds: int = 900
    action_blast_radius_limit: int = 3
    action_verification_attempts: int = 3
    action_verification_interval_seconds: float = 20.0

    action_type_restart: str = "restart"
    action_target_kind_deployment: str = "Deployment"
    default_action_replicas: int = 3
    prometheus_base_url: str = ""
    prometheus_token: str = ""
    prometheus_account: str = ""
    prometheus_timeout_seconds: float = 30.0

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
    executor_shared_secret: str = ""
    executor_allowed_targets: str = ""
    executor_namespace: str = "techx-corp-prod"
    executor_max_replicas: int = 10
    executor_state_path: Path = Path("state/executor.sqlite3")

    @model_validator(mode="after")
    def align_state_paths(self) -> "Settings":
        if self.state_store_path == DEFAULT_STATE_STORE_PATH:
            return self
        state_dir = self.state_store_path.parent
        if self.remediation_audit_path == DEFAULT_REMEDIATION_AUDIT_PATH:
            self.remediation_audit_path = state_dir / DEFAULT_REMEDIATION_AUDIT_PATH.name
        if self.rca_history_path == DEFAULT_RCA_HISTORY_PATH:
            self.rca_history_path = state_dir / DEFAULT_RCA_HISTORY_PATH.name
        return self
