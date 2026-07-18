from __future__ import annotations

import json
from pathlib import Path
from string import Template

from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.config.settings import Settings
from aiops.schemas import RuntimeConfig


PROMETHEUS_SERVICE_METRICS = {
    "p95_latency_5m": {
        "template": '((histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="$service"}[5m])) by (le, service_name)) / 1000) and on(service_name) (sum(rate(traces_span_metrics_duration_milliseconds_count{service_name="$service"}[5m])) by (service_name) > 0)) or on() vector(0)',
        "unit": "seconds",
    },
    "error_rate_5m": {
        "template": '((((sum(rate(traces_span_metrics_calls_total{service_name="$service",status_code="STATUS_CODE_ERROR"}[5m])) or vector(0)) / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="$service"}[5m])), 0.000001)) and on() (sum(rate(traces_span_metrics_calls_total{service_name="$service"}[5m])) > 0)) or on() vector(0))',
        "unit": "ratio",
    },
    "request_rate_5m": {
        "template": 'sum(rate(traces_span_metrics_calls_total{service_name="$service"}[5m])) or on() vector(0)',
        "unit": "requests_per_second",
    },
    "cpu_millicores": {
        "template": '((sum(rate(container_cpu_usage_seconds_total{container="$service"}[5m])) * 1000) or (sum(rate(container_cpu_usage_total{container_name=~".*$service.*"}[5m])) * 1000) or sum(k8s_pod_cpu_usage{k8s_deployment_name="$service"})) or on() vector(0)',
        "unit": "count",
    },
    "memory_usage_bytes": {
        "template": '(sum(container_memory_usage_bytes{container="$service"}) or sum(container_memory_usage_bytes{container_name=~".*$service.*"}) or sum(k8s_pod_memory_usage{k8s_deployment_name="$service"})) or on() vector(0)',
        "unit": "bytes",
    },
    "disk_io_bytes_per_second": {
        "template": '((sum(rate(container_fs_reads_bytes_total{container="$service"}[5m])) + sum(rate(container_fs_writes_bytes_total{container="$service"}[5m]))) or sum(rate(container_blockio_io_service_bytes_recursive{container_name=~".*$service.*"}[5m]))) or on() vector(0)',
        "unit": "bytes",
    },
    "socket_io_bytes_per_second": {
        "template": '((sum(rate(container_network_receive_bytes_total{pod=~"$service.*"}[5m])) + sum(rate(container_network_transmit_bytes_total{pod=~"$service.*"}[5m]))) or (sum(rate(container_network_io_usage_rx_bytes{container_name=~".*$service.*"}[5m])) + sum(rate(container_network_io_usage_tx_bytes{container_name=~".*$service.*"}[5m])))) or on() vector(0)',
        "unit": "bytes",
    },
    "workload_ready_pods": {
        "template": '(sum(k8s_pod_ready{k8s_deployment_name="$service"}) or sum(kube_pod_status_ready{pod=~"$service.*",condition="true"})) or on() vector(0)',
        "unit": "count",
    },
}


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
    for service in raw.get("prometheus_services", []):
        flow = topology[service]["flow"]
        signal_prefix = service.replace("-", "_")
        for metric, config in PROMETHEUS_SERVICE_METRICS.items():
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
                    "window": "5m",
                    "flow": flow,
                    "service": service,
                    "feature_role": "anomaly_input",
                    "required_labels": [],
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
