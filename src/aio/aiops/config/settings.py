from __future__ import annotations

import os
from pathlib import Path

from pydantic import field_validator
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

    app_title: str
    api_health_live_path: str
    api_pipeline_run_path: str
    health_status: str

    environment: str
    policy_mode: str
    evidence_dir: Path
    state_store_path: Path
    runtime_config_path: Path
    actions_catalog_path: Path
    incidents_history_path: Path
    remediation_audit_path: Path
    remediation_history_top_k: int
    remediation_ood_threshold: float
    remediation_cost_page: float
    remediation_blast_radius_limit: int
    remediation_confidence_threshold: float
    remediation_similarity_weights: dict[str, float]
    no_data_missing_confidence: float
    no_data_unknown_confidence: float
    rca_enabled: bool
    rca_top_k: int
    rca_min_points: int
    rca_ewma_alpha: float
    rca_ewma_z_threshold: float
    rca_seasonal_period: int
    rca_isolation_score_threshold: float
    rca_bocpd_score_threshold: float
    rca_fallback_split_ratio: float

    checkout_slo_detector_id: str
    checkout_bad_ratio_signal_id: str
    checkout_flow: str
    checkout_service: str
    checkout_severity: str
    checkout_slo_runbook_id: str

    dependency_default_severity: str

    no_data_detector_id: str
    no_data_flow: str
    no_data_service: str
    no_data_severity: str
    no_data_runbook_id: str
    no_data_required_signal_ids: list[str]

    action_type_restart: str
    action_target_kind_deployment: str
    default_action_replicas: int
    protected_targets: set[str]
    stateful_kinds: set[str]
    non_actionable_flows: set[str]

    prometheus_base_url: str
    prometheus_token: str
    prometheus_account: str

    grafana_webhook_secret: str

    jaeger_base_url: str
    jaeger_token: str
    jaeger_account: str

    opensearch_base_url: str
    opensearch_username: str
    opensearch_password: str
    opensearch_account: str
    opensearch_verify_tls: bool

    kubernetes_api_url: str
    kubernetes_bearer_token: str
    kubernetes_account: str

    notification_webhook_url: str
    notification_token: str
    notification_account: str

    aie_status_url: str
    aie_token: str
    aie_account: str

    cdo_cost_url: str
    cdo_cost_token: str
    cdo_cost_account: str

    live_executor_url: str
    live_executor_token: str
    live_executor_account: str

    @field_validator("no_data_required_signal_ids", mode="before")
    @classmethod
    def _split_csv_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("protected_targets", "stateful_kinds", "non_actionable_flows", mode="before")
    @classmethod
    def _split_csv_set(cls, value: object) -> object:
        if isinstance(value, str):
            return {item.strip() for item in value.split(",") if item.strip()}
        return value
