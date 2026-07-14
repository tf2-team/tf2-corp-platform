from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from aiops.config import Settings
from aiops.schemas import GrafanaNormalizedEvent, GrafanaWebhookEvent, HealthResponse


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

    @app.post("/api/v1/events/grafana", response_model=GrafanaNormalizedEvent)
    def grafana_webhook(
        event: GrafanaWebhookEvent,
        x_aiops_grafana_secret: str = Header(default=""),
    ) -> GrafanaNormalizedEvent:
        return handle_grafana_webhook(event, x_aiops_grafana_secret, settings)

    return app
