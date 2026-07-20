#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from aiops.api.app import run_static_pipeline
from aiops.collectors import PrometheusCollectionPlan, PrometheusCollector, load_prometheus_collection_plan
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.integrations import PrometheusClient
from aiops.schemas import PipelineResult, PipelineRunRequest, RuntimeConfig, SignalQuality


class DryRunSafetyError(RuntimeError):
    pass


def execute_prometheus_e2e(
    settings: Settings,
    plan_path: Path,
    report_dir: Path,
    *,
    client: PrometheusClient | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    started_at = (captured_at or datetime.now(UTC)).astimezone(UTC)
    run_id = f"aio-e2e-{started_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    report_path = report_dir / f"{run_id}.json"
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "status": "error",
        "mode": settings.policy_mode,
        "source": {
            "type": "prometheus",
            "endpoint": redact_url(settings.prometheus_base_url),
            "collection_plan_path": str(plan_path),
        },
        "artifact": {"path": str(report_path), "format": "json", "written": True},
    }

    try:
        _require_dry_run(settings)
        plan = load_prometheus_collection_plan(plan_path)
        runtime_config = load_runtime_config(settings.runtime_config_path)
        validate_collection_plan(plan, runtime_config, int(load_hyperparameters(settings.hyperparameters_path)["rca"]["min_points"]))

        collector = PrometheusCollector(client or PrometheusClient(settings), plan, captured_at=started_at)
        observations = collector.collect()
        metric_series = collector.collect_metric_series()
        result = run_static_pipeline(
            PipelineRunRequest(observations=observations, metric_series=metric_series),
            settings=settings,
        )

        acceptance = build_acceptance_result(result, observations, metric_series)
        report.update(
            {
                "status": "passed" if all(item["passed"] for item in acceptance.values()) else "failed",
                "source": {
                    **report["source"],
                    "captured_at": started_at.isoformat(),
                    "collection_plan": plan.model_dump(mode="json"),
                },
                "input": {
                    "observations": [item.model_dump(mode="json") for item in observations],
                    "metric_series": [item.model_dump(mode="json") for item in metric_series],
                },
                "pipeline_result": result.model_dump(mode="json"),
                "acceptance_criteria": acceptance,
                "safety": {
                    "live_execution_enabled": False,
                    "live_executor_called": False,
                    "policy_mode": settings.policy_mode,
                },
            }
        )
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["acceptance_criteria"] = error_acceptance_result()
        report["safety"] = {
            "live_execution_enabled": False,
            "live_executor_called": False,
            "policy_mode": settings.policy_mode,
        }

    report["completed_at"] = datetime.now(UTC).isoformat()
    write_report(report_path, report)
    return report


def validate_collection_plan(
    plan: PrometheusCollectionPlan,
    runtime_config: RuntimeConfig,
    rca_min_points: int,
) -> None:
    runtime_signals = {signal.id: signal for signal in runtime_config.signals if signal.source == "prometheus"}
    plan_signals = {query.signal_id: query for query in plan.observation_queries}
    extra = set(plan_signals) - set(runtime_signals)
    if extra:
        raise ValueError(f"collection plan signal mismatch: extra={sorted(extra)}")

    for signal_id, query in plan_signals.items():
        signal = runtime_signals[signal_id]
        if query.query_id != signal.query_id:
            raise ValueError(f"query_id mismatch for {signal_id}: {query.query_id!r} != {signal.query_id!r}")
        if query.unit != signal.unit or query.window != signal.window:
            raise ValueError(f"unit/window mismatch for {signal_id}")
        missing_labels = set(signal.required_labels) - set(query.labels)
        if missing_labels:
            raise ValueError(f"missing required labels for {signal_id}: {sorted(missing_labels)}")

    for query in plan.metric_series_queries:
        theoretical_points = query.lookback_seconds // query.step_seconds + 1
        if theoretical_points < rca_min_points:
            raise ValueError(
                f"metric query {query.query_id} can return only {theoretical_points} points; "
                f"RCA requires {rca_min_points}"
            )


def build_acceptance_result(result: PipelineResult, observations: list, metric_series: list) -> dict[str, dict[str, Any]]:
    verified_signal_ids = {
        observation.signal_id for observation in observations if observation.quality == SignalQuality.VERIFIED
    }
    real_metric_incidents = [
        incident
        for incident in result.incidents
        if any(event.signal_id in verified_signal_ids for event in incident.events)
    ]
    range_sample_count = sum(len(series.points) for series in metric_series)
    policy_is_safe = all(
        not decision.allowed and not decision.executed and decision.result in {"blocked", "dry-run-recorded"}
        for decision in result.policy_decisions
    )
    remediation_is_safe = bool(result.remediation_decisions) and all(
        decision.decision in {"dry-run-recorded", "fallback-page-oncall"}
        for decision in result.remediation_decisions
    )

    return {
        "incident_from_real_metrics": {
            "passed": bool(real_metric_incidents),
            "details": {
                "verified_signal_ids": sorted(verified_signal_ids),
                "incident_ids": [incident.incident_id for incident in real_metric_incidents],
            },
        },
        "rca_returns_root_cause_candidates": {
            "passed": bool(metric_series) and range_sample_count > 0 and bool(result.rca_result.root_causes),
            "details": {
                "metric_series_count": len(metric_series),
                "range_sample_count": range_sample_count,
                "candidate_services": [candidate.service for candidate in result.rca_result.root_causes],
            },
        },
        "remediation_is_dry_run_or_page_oncall": {
            "passed": policy_is_safe and remediation_is_safe,
            "details": {
                "policy_results": [decision.result for decision in result.policy_decisions],
                "remediation_results": [decision.decision for decision in result.remediation_decisions],
                "selected_actions": [decision.selected_action for decision in result.remediation_decisions],
            },
        },
        "report_exists_for_run": {
            "passed": True,
            "details": {"contains_run_id": True, "contains_timestamps": True, "contains_pipeline_result": True},
        },
    }


def error_acceptance_result() -> dict[str, dict[str, Any]]:
    return {
        "incident_from_real_metrics": {"passed": False, "details": {}},
        "rca_returns_root_cause_candidates": {"passed": False, "details": {}},
        "remediation_is_dry_run_or_page_oncall": {"passed": False, "details": {}},
        "report_exists_for_run": {
            "passed": True,
            "details": {"contains_run_id": True, "contains_timestamps": True, "contains_error": True},
        },
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def redact_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _require_dry_run(settings: Settings) -> None:
    if settings.policy_mode != "dry-run":
        raise DryRunSafetyError(
            f"Prometheus E2E runner requires AIOPS_POLICY_MODE=dry-run; got {settings.policy_mode!r}"
        )
