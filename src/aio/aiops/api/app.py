#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException

from aiops.collectors import PrometheusCollector, StaticCollector
from aiops.config import Settings, build_detectors, load_hyperparameters, load_runtime_config
from aiops.enrichment import Enricher
from aiops.integrations import JaegerClient, KubernetesClient, LiveExecutorClient, NotificationClient, OpenSearchClient, PrometheusClient
from aiops.normalization import load_normalization_schema
from aiops.observability.logging import configure_root_logging
from aiops.observability import metrics_response, record_pipeline_failure, record_pipeline_success
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
    SelfHealConfig,
    SelfHealOrchestrator,
)
from aiops.schemas import GrafanaNormalizedEvent, GrafanaWebhookEvent, HealthResponse, Incident, PipelineResult, PipelineRunRequest
from aiops.shared.evidence import STRONG_TRACE_MARKER
from aiops.storage import SQLiteIncidentStore
from aiops.topology import TopologyGraph


logger = logging.getLogger(__name__)
# ponytail: process-local lock; use a distributed lease if the API runs with multiple workers.
_LIVE_PIPELINE_LOCK = Lock()


def configure_logging() -> None:
    configure_root_logging(
        level=os.getenv("AIOPS_LOG_LEVEL", "INFO"),
        output_format=os.getenv("AIOPS_LOG_FORMAT", "pretty"),
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("drain3").setLevel(logging.WARNING)


def run_static_pipeline(request: PipelineRunRequest, settings: Settings | None = None) -> PipelineResult:
    settings = settings or Settings()
    runtime_config = load_runtime_config(settings.runtime_config_path, settings.prometheus_registry_path)
    return run_pipeline_with_collector(
        StaticCollector(request.observations),
        settings,
        runtime_config,
        metric_series=request.metric_series,
    )


def run_live_pipeline(settings: Settings | None = None) -> PipelineResult:
    with _LIVE_PIPELINE_LOCK:
        settings = settings or Settings()
        runtime_config = load_runtime_config(settings.runtime_config_path, settings.prometheus_registry_path)
        collector = PrometheusCollector(
            PrometheusClient(settings),
            runtime_config,
            cache_namespace=settings.prometheus_base_url,
        )
        try:
            metric_series = collector.collect_metric_series()
        except Exception:
            collector.close()
            raise
        return run_pipeline_with_collector(collector, settings, runtime_config, metric_series=metric_series)


def run_pipeline_with_collector(collector, settings: Settings, runtime_config, metric_series=None) -> PipelineResult:
    started = time.monotonic()
    try:
        if settings.self_heal_enabled:
            if settings.policy_mode != "live-approved":
                raise RuntimeError("self-heal requires AIOPS_POLICY_MODE=live-approved")
            if not _configured_url(settings.live_executor_url):
                raise RuntimeError("self-heal requires a configured live executor URL")
            if not settings.self_heal_approval_id:
                raise RuntimeError("self-heal requires a signed approval id")
            if not _notification_configured(settings):
                raise RuntimeError("self-heal requires an escalation notification webhook")
    except Exception:
        _close_if_supported(collector)
        raise
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    topology_graph = TopologyGraph(runtime_config)
    store = SQLiteIncidentStore(
        path=settings.state_store_path,
        environment=settings.environment,
        notification_cooldown_seconds=int(hyperparameters["incident"]["notification_cooldown_seconds"]),
        slo_dedup_seconds=int(hyperparameters["incident"]["slo_dedup_seconds"]),
        rca_dedup_seconds=int(hyperparameters["incident"]["rca_dedup_seconds"]),
        incident_count_reset_seconds=int(hyperparameters["incident"]["count_reset_seconds"]),
        recovery_consecutive_buckets=int(hyperparameters["incident"]["recovery_consecutive_buckets"]),
        notification_retry_base_seconds=int(hyperparameters["incident"]["notification_retry_base_seconds"]),
        notification_retry_max_seconds=int(hyperparameters["incident"]["notification_retry_max_seconds"]),
        notification_error_max_chars=int(hyperparameters["incident"]["notification_error_max_chars"]),
        topology_graph=topology_graph,
    )
    enricher = build_enricher(settings, runtime_config, hyperparameters["enrichment"])
    notification_sender = NotificationClient(settings) if _notification_configured(settings) else None
    executor_client = None
    self_heal = None
    if settings.self_heal_enabled:
        executor_client = LiveExecutorClient(settings)
        self_heal = SelfHealOrchestrator(
            executor_client,
            store,
            SelfHealConfig(
                namespace=settings.environment,
                policy_id=settings.self_heal_policy_id,
                policy_expires_at=settings.self_heal_policy_expires_at,
                approval_id=settings.self_heal_approval_id,
                protected_targets=frozenset(runtime_config.policy.protected_targets),
                verification_deadline_seconds=settings.self_heal_verification_deadline_seconds,
                min_fresh_samples=settings.self_heal_min_fresh_samples,
                consecutive_passes=settings.self_heal_consecutive_passes,
                failure_samples=settings.self_heal_failure_samples,
                min_incident_occurrences=int(hyperparameters["self_heal"]["min_incident_occurrences"]),
                min_incident_score=float(hyperparameters["self_heal"]["min_incident_score"]),
                min_occurrence_interval_seconds=int(hyperparameters["self_heal"]["min_occurrence_interval_seconds"]),
                queue_ttl_seconds=int(hyperparameters["self_heal"]["queue_ttl_seconds"]),
                verification_callback_max_attempts=int(hyperparameters["self_heal"]["verification_callback_max_attempts"]),
                rollback_max_attempts=int(hyperparameters["self_heal"]["rollback_max_attempts"]),
                rollback_after_executions=int(hyperparameters["self_heal"]["rollback_after_executions"]),
                rollback_failure_runbook_id=str(hyperparameters["self_heal"]["rollback_failure_runbook_id"]),
            ),
        )
    pipeline = AiopsPipeline(
        collector=collector,
        detectors=build_detectors(runtime_config, hyperparameters["no_data"], hyperparameters["detectors"]),
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
        qualification_max_sample_age_seconds=int(hyperparameters["qualification"]["max_sample_age_seconds"]),
        rca_hyperparameters=hyperparameters["rca"],
        correlation_hyperparameters=hyperparameters["correlation"],
        remediation_hyperparameters=hyperparameters["remediation"],
        enricher=enricher,
        remediation=(
            RemediationFeatureExtractor(),
            HistoryRetriever(
                hyperparameters["remediation"]["similarity_weights"],
                hyperparameters["remediation"]["history_top_k"],
                hyperparameters["remediation"]["metric_similarity_epsilon"],
            ),
            RemediationDecisionEngine(
                ood_threshold=hyperparameters["remediation"]["ood_threshold"],
                cost_page=hyperparameters["remediation"]["cost_page"],
                blast_radius_limit=hyperparameters["remediation"]["blast_radius_limit"],
                confidence_threshold=hyperparameters["remediation"]["confidence_threshold"],
                downtime_cost_multiplier=hyperparameters["remediation"]["downtime_cost_multiplier"],
                outcome_weights=hyperparameters["remediation"]["outcome_weights"],
                fallback_action_id=hyperparameters["remediation"]["fallback_action_id"],
                fallback_target=hyperparameters["remediation"]["fallback_target"],
            ),
            ActionCatalog(settings.actions_catalog_path),
            IncidentHistoryStore(settings.incidents_history_path),
            RemediationAuditLog(settings.remediation_audit_path),
        ),
        notification_sender=notification_sender,
        rca_history_path=settings.rca_history_path,
        self_heal=self_heal,
    )
    try:
        result = pipeline.run_once(metric_series=metric_series or [])
        record_pipeline_success(result, time.monotonic() - started)
        print_rca_result(result)
        return result
    except Exception:
        record_pipeline_failure(time.monotonic() - started)
        raise
    finally:
        store.close()
        _close_if_supported(notification_sender)
        _close_if_supported(executor_client)
        _close_if_supported(enricher)
        _close_if_supported(collector)


def print_rca_result(result: PipelineResult) -> None:
    root_pairs = {(root.service, metric) for root in result.rca_result.root_causes for metric in root.root_cause_metrics}
    for anomaly in result.rca_result.anomalies:
        if root_pairs and (anomaly.service, anomaly.metric) not in root_pairs:
            continue
        print(
            "AIOPS_ANOMALY "
            f"algorithm={anomaly.algorithm} "
            f"service={anomaly.service} "
            f"metric={anomaly.metric} "
            f"signal={anomaly.signal_id} "
            f"score={anomaly.score:.3f} "
            f"timestamp={anomaly.timestamp}",
            flush=True,
        )
    for root in result.rca_result.root_causes:
        trace = next((item for item in root.evidence if item.startswith(STRONG_TRACE_MARKER)), "")
        print(
            "AIOPS_ROOT_CAUSE "
            f"service={root.service} "
            f"score={root.score:.3f} "
            f"metrics={','.join(root.root_cause_metrics)}"
            f"{' ' + trace if trace else ''}",
            flush=True,
        )


async def auto_run_loop(settings: Settings) -> None:
    while True:
        started = asyncio.get_running_loop().time()
        try:
            await asyncio.to_thread(run_live_pipeline, settings)
        except Exception:
            logger.exception("AIOps live pipeline run failed")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0.0, settings.auto_run_interval_seconds - elapsed))


def build_enricher(settings: Settings, runtime_config, enrichment_hyperparameters: dict | None = None) -> Enricher:
    jaeger = JaegerClient(settings) if _configured_url(settings.jaeger_base_url) else None
    opensearch = (
        OpenSearchClient(settings)
        if _configured_url(settings.opensearch_base_url) and _configured_secret(settings.opensearch_username) and _configured_secret(settings.opensearch_password)
        else None
    )
    kubernetes = KubernetesClient(settings) if _configured_kubernetes(settings) else None
    return Enricher(
        runtime_config=runtime_config,
        jaeger=jaeger,
        opensearch=opensearch,
        kubernetes=kubernetes,
        hyperparameters=enrichment_hyperparameters,
    )


def _configured_url(value: str) -> bool:
    return _configured_secret(value) and ".example" not in value


def _notification_configured(settings: Settings) -> bool:
    return any(
        _configured_url(url)
        for url in (
            settings.notification_dev_webhook_url,
            settings.notification_user_webhook_url,
            settings.notification_webhook_url,
        )
    )


def _configured_secret(value: str) -> bool:
    text = value.strip().upper()
    return bool(text) and "CHANGE_ME" not in text and "<FILL_IN" not in text


def _close_if_supported(component) -> None:
    close = getattr(component, "close", None)
    if callable(close):
        close()


def _configured_kubernetes(settings: Settings) -> bool:
    if not _configured_secret(settings.kubernetes_api_url):
        return False
    host = urlparse(settings.kubernetes_api_url).hostname or ""
    return (
        _configured_secret(settings.kubernetes_bearer_token)
        or settings.kubernetes_bearer_token_file.is_file()
        or host in {"localhost", "127.0.0.1"}
    )


def readiness(settings: Settings) -> HealthResponse:
    try:
        load_runtime_config(settings.runtime_config_path, settings.prometheus_registry_path)
        load_hyperparameters(settings.hyperparameters_path)
        load_qualification_schema(settings.qualification_schema_path)
        load_normalization_schema(settings.normalization_schema_path)
        if settings.auto_run_enabled and not _configured_url(settings.prometheus_base_url):
            raise RuntimeError("automatic runs require Prometheus")
        if settings.auto_run_enabled and not _notification_configured(settings):
            raise RuntimeError("automatic runs require an incident notification webhook")
        if settings.auto_run_enabled:
            prometheus_client = PrometheusClient(settings)
            try:
                response = prometheus_client.query("vector(1)")
                if response.get("status") != "success" or not (response.get("data") or {}).get("result"):
                    raise RuntimeError("Prometheus query dependency is not ready")
            finally:
                prometheus_client.close()
        if settings.self_heal_enabled and settings.policy_mode != "live-approved":
            raise RuntimeError("self-heal requires live-approved policy mode")
        if settings.self_heal_enabled and not _configured_url(settings.live_executor_url):
            raise RuntimeError("self-heal requires the live executor")
        if settings.self_heal_enabled and not settings.self_heal_approval_id:
            raise RuntimeError("self-heal requires an approval id")
        if settings.self_heal_enabled and not _notification_configured(settings):
            raise RuntimeError("self-heal requires an escalation notification webhook")
        if settings.self_heal_enabled:
            executor_client = LiveExecutorClient(settings)
            try:
                if not executor_client.ready():
                    raise RuntimeError("live executor is not ready")
            finally:
                executor_client.close()
        if not _configured_secret(settings.grafana_webhook_secret):
            raise RuntimeError("Grafana webhook secret is not configured")
        state_parent = settings.state_store_path.parent
        if not state_parent.is_dir() or not os.access(state_parent, os.W_OK):
            raise RuntimeError("state directory is not writable")
    except Exception as exc:
        logger.warning("AIOps readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="runtime dependencies are not ready") from exc
    return HealthResponse(status="ready")


def handle_grafana_webhook(
    event: GrafanaWebhookEvent,
    x_aiops_grafana_secret: str,
    settings: Settings | None = None,
) -> GrafanaNormalizedEvent:
    settings = settings or Settings()
    max_annotation_chars = int(load_hyperparameters(settings.hyperparameters_path).get("api", {}).get("grafana_annotation_max_chars", 2048))
    if not _configured_secret(settings.grafana_webhook_secret):
        raise HTTPException(status_code=503, detail="grafana webhook is not configured")
    if not hmac.compare_digest(x_aiops_grafana_secret, settings.grafana_webhook_secret):
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
        annotations_redacted={key: value[:max_annotation_chars] for key, value in alert.annotations.items()},
        links={"generator": alert.generator_url, "dashboard": alert.dashboard_url, "panel": alert.panel_url},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.aiops_auto_run_task = None
        if settings.auto_run_enabled:
            app.state.aiops_auto_run_task = asyncio.create_task(auto_run_loop(settings))
        try:
            yield
        finally:
            task = app.state.aiops_auto_run_task
            if task is not None:
                task.cancel()

    app = FastAPI(title=settings.app_title, lifespan=lifespan)

    @app.get(settings.api_health_live_path, response_model=HealthResponse)
    def live() -> HealthResponse:
        return HealthResponse(status=settings.health_status)

    @app.get("/health/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        return readiness(settings)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return metrics_response()

    @app.post(settings.api_pipeline_run_path, response_model=PipelineResult)
    def run_pipeline(request: PipelineRunRequest) -> PipelineResult:
        return run_static_pipeline(request, settings)

    @app.post("/api/v1/pipeline/run/live", response_model=PipelineResult)
    def run_live() -> PipelineResult:
        return run_live_pipeline(settings)

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
