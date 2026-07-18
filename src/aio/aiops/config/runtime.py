from __future__ import annotations

import json
from pathlib import Path
from string import Template

from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.config.settings import Settings
from aiops.schemas import RuntimeConfig


def load_runtime_config(path: Path) -> RuntimeConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    service_queries, service_signals = _build_service_prometheus(raw)
    raw["prometheus_queries"] = {**raw.get("prometheus_queries", {}), **service_queries}
    raw["signals"] = [*raw.get("signals", []), *service_signals]
    _expand_detector_signal_groups(raw)
    return RuntimeConfig.model_validate(raw)


def _build_service_prometheus(raw: dict) -> tuple[dict[str, str], list[dict]]:
    topology = {service["name"]: service for service in raw["topology"]["services"]}
    explicit_queries = set(raw.get("prometheus_queries", {}))
    explicit_signals = {signal["id"] for signal in raw.get("signals", [])}
    queries: dict[str, str] = {}
    signals: list[dict] = []
    metric_templates = raw.get("prometheus_metric_templates", {})
    planned_metrics = raw.get("prometheus_metrics", [])
    unknown_metrics = set(planned_metrics) - set(metric_templates)
    if unknown_metrics:
        raise ValueError(f"unknown Prometheus metrics: {sorted(unknown_metrics)}")
    for service in raw.get("prometheus_services", []):
        flow = topology[service]["flow"]
        signal_prefix = service.replace("-", "_")
        for metric in planned_metrics:
            config = metric_templates[metric]
            query_id = f"{service}.{metric}"
            signal_id = f"{signal_prefix}_{metric.replace('.', '_')}"
            if query_id in explicit_queries or signal_id in explicit_signals:
                continue
            queries[query_id] = Template(config["template"]).substitute(service=service)
            signals.append(
                {
                    "id": signal_id,
                    "source": "prometheus",
                    "query_id": query_id,
                    "unit": config["unit"],
                    "window": config["window"],
                    "flow": flow,
                    "service": service,
                    "feature_role": config["feature_role"],
                    "required_labels": config.get("required_labels", []),
                    "labels": config.get("labels", {}),
                }
            )
    return queries, signals


def _expand_detector_signal_groups(raw: dict) -> None:
    prometheus_signal_ids = [signal["id"] for signal in raw.get("signals", []) if signal.get("source") == "prometheus"]
    for detector in raw.get("detectors", []):
        if "__all_prometheus__" in detector.get("signal_ids", []):
            detector["signal_ids"] = prometheus_signal_ids


def build_detectors(
    config: RuntimeConfig,
    settings: Settings | None,
    no_data_hyperparameters: dict[str, float],
    detector_hyperparameters: dict | None = None,
) -> list[Detector]:
    detectors: list[Detector] = []
    detector_hyperparameters = detector_hyperparameters or {}
    thresholds = detector_hyperparameters.get("thresholds") or config.detector_thresholds
    confidences = detector_hyperparameters.get("confidences") or config.detector_confidences
    for item in config.detectors:
        if not item.enabled:
            continue
        if item.type == "threshold":
            detectors.append(
                ThresholdDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "dependency":
            detectors.append(
                DependencyDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    dependency=item.dependency or "unknown",
                    severity=item.severity,
                    confidence=confidences[item.id],
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "no-data":
            detectors.append(
                NoDataDetector(
                    item.signal_ids,
                    detector_id=item.id,
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                    missing_confidence=no_data_hyperparameters["missing_confidence"],
                    unknown_confidence=no_data_hyperparameters["unknown_confidence"],
                )
            )
    return detectors
