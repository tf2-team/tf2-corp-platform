from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from aiops.collectors import StaticCollector
from aiops.config import Settings
from aiops.detectors import NoDataDetector, ThresholdDetector
from aiops.pipeline import AiopsPipeline
from aiops.remediation import PolicyEngine
from aiops.schemas import GrafanaNormalizedEvent, GrafanaWebhookEvent, HealthResponse, PipelineResult, PipelineRunRequest
from aiops.storage import SQLiteIncidentStore


def run_static_pipeline(request: PipelineRunRequest, settings: Settings | None = None) -> PipelineResult:
    settings = settings or Settings()
    store = SQLiteIncidentStore(path=settings.state_store_path, environment=settings.environment)
    pipeline = AiopsPipeline(
        collector=StaticCollector(request.observations),
        detectors=[
            ThresholdDetector(
                detector_id=settings.checkout_slo_detector_id,
                signal_id=settings.checkout_bad_ratio_signal_id,
                threshold=settings.checkout_slo_threshold,
                flow=settings.checkout_flow,
                service=settings.checkout_service,
                severity=settings.checkout_severity,
                runbook_id=settings.checkout_slo_runbook_id,
            ),
            NoDataDetector(
                settings.no_data_required_signal_ids,
                detector_id=settings.no_data_detector_id,
                flow=settings.no_data_flow,
                service=settings.no_data_service,
                severity=settings.no_data_severity,
                runbook_id=settings.no_data_runbook_id,
            ),
        ],
        store=store,
        policy=PolicyEngine(
            mode=settings.policy_mode,
            protected_targets=settings.protected_targets,
            stateful_kinds=settings.stateful_kinds,
            non_actionable_flows=settings.non_actionable_flows,
            action_type=settings.action_type_restart,
            target_kind=settings.action_target_kind_deployment,
            default_replicas=settings.default_action_replicas,
        ),
    )
    try:
        return pipeline.run_once()
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
    return GrafanaNormalizedEvent(
        source="grafana",
        status=event.status,
        alert_count=len(event.alerts),
        alert_names=[alert.labels.get("alertname", "unknown") for alert in event.alerts],
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

    @app.post("/api/v1/events/grafana", response_model=GrafanaNormalizedEvent)
    def grafana_webhook(
        event: GrafanaWebhookEvent,
        x_aiops_grafana_secret: str = Header(default=""),
    ) -> GrafanaNormalizedEvent:
        return handle_grafana_webhook(event, x_aiops_grafana_secret, settings)

    return app
