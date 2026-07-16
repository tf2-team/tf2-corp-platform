from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException

from aiops.collectors import StaticCollector
from aiops.config import Settings, build_detectors, load_runtime_config
from aiops.normalization import load_normalization_schema
from aiops.pipeline import AiopsPipeline
from aiops.qualification import load_qualification_schema
from aiops.remediation import (
    ActionCatalog,
    HistoryRetriever,
    IncidentHistoryStore,
    PolicyEngine,
    RemediationAuditLog,
    RemediationDecisionEngine,
    RemediationFeatureExtractor,
)
from aiops.schemas import GrafanaNormalizedEvent, GrafanaWebhookEvent, HealthResponse, Incident, PipelineResult, PipelineRunRequest
from aiops.storage import SQLiteIncidentStore


def run_static_pipeline(request: PipelineRunRequest, settings: Settings | None = None) -> PipelineResult:
    settings = settings or Settings()
    runtime_config = load_runtime_config(settings.runtime_config_path)
    store = SQLiteIncidentStore(path=settings.state_store_path, environment=settings.environment)
    pipeline = AiopsPipeline(
        collector=StaticCollector(request.observations),
        detectors=build_detectors(runtime_config, settings),
        store=store,
        policy=PolicyEngine(
            mode=settings.policy_mode,
            protected_targets=runtime_config.policy.protected_targets,
            stateful_kinds=runtime_config.policy.stateful_kinds,
            non_actionable_flows=runtime_config.policy.non_actionable_flows,
            action_type=settings.action_type_restart,
            target_kind=settings.action_target_kind_deployment,
            default_replicas=settings.default_action_replicas,
        ),
        runtime_config=runtime_config,
        qualification_schema=load_qualification_schema(settings.qualification_schema_path),
        normalization_schema=load_normalization_schema(settings.normalization_schema_path),
        qualification_dev=settings.qualification_gate_dev,
        qualification_max_sample_age_seconds=settings.qualification_max_sample_age_seconds,
        rca_hyperparameters={
            "enabled": settings.rca_enabled,
            "top_k": settings.rca_top_k,
            "min_points": settings.rca_min_points,
            "ewma_alpha": settings.rca_ewma_alpha,
            "ewma_z_threshold": settings.rca_ewma_z_threshold,
            "seasonal_period": settings.rca_seasonal_period,
            "isolation_score_threshold": settings.rca_isolation_score_threshold,
            "bocpd_score_threshold": settings.rca_bocpd_score_threshold,
            "fallback_split_ratio": settings.rca_fallback_split_ratio,
        },
        remediation=(
            RemediationFeatureExtractor(),
            HistoryRetriever(settings.remediation_similarity_weights, settings.remediation_history_top_k),
            RemediationDecisionEngine(
                ood_threshold=settings.remediation_ood_threshold,
                cost_page=settings.remediation_cost_page,
                blast_radius_limit=settings.remediation_blast_radius_limit,
                confidence_threshold=settings.remediation_confidence_threshold,
            ),
            ActionCatalog(settings.actions_catalog_path),
            IncidentHistoryStore(settings.incidents_history_path),
            RemediationAuditLog(settings.remediation_audit_path),
        ),
    )
    try:
        return pipeline.run_once(metric_series=request.metric_series)
    finally:
        store.close()


def handle_grafana_webhook(
    event: GrafanaWebhookEvent,
    x_aiops_grafana_secret: str,
    settings: Settings | None = None,
) -> GrafanaNormalizedEvent:
    settings = settings or Settings()
    if x_aiops_grafana_secret != settings.grafana_webhook_secret:
        raise HTTPException(status_code=401, detail="invalid grafana webhook secret")
    alert = event.alerts[0]
    alert_name = alert.labels.get("alertname", "unknown")
    return GrafanaNormalizedEvent(
        source="grafana",
        status=event.status,
        alert_id=alert.fingerprint or alert_name,
        received_at=datetime.now(UTC).isoformat(),
        starts_at=alert.starts_at,
        ends_at=alert.ends_at,
        labels=alert.labels,
        annotations_redacted={key: value[:2048] for key, value in alert.annotations.items()},
        links={"generator": alert.generator_url, "dashboard": alert.dashboard_url, "panel": alert.panel_url},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=settings.app_title)

    @app.get(settings.api_health_live_path, response_model=HealthResponse)
    def live() -> HealthResponse:
        return HealthResponse(status=settings.health_status)

    @app.post(settings.api_pipeline_run_path, response_model=PipelineResult)
    def run_pipeline(request: PipelineRunRequest) -> PipelineResult:
        return run_static_pipeline(request, settings)

    @app.get("/api/v1/incidents", response_model=list[Incident])
    def list_incidents() -> list[Incident]:
        store = SQLiteIncidentStore(path=settings.state_store_path, environment=settings.environment)
        try:
            return store.list_incidents()
        finally:
            store.close()

    @app.post("/api/v1/events/grafana", response_model=GrafanaNormalizedEvent)
    def grafana_webhook(
        event: GrafanaWebhookEvent,
        x_aiops_grafana_secret: str = Header(default=""),
    ) -> GrafanaNormalizedEvent:
        return handle_grafana_webhook(event, x_aiops_grafana_secret, settings)

    return app
