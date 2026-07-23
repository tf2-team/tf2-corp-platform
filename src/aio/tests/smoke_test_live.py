#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Strict smoke tests for AIOps integrations through AWS EKS port-forwards.

Preparation (run from ``src/aio``):

1. ``powershell -File scripts/port_forward.ps1``
2. Start AIOps in another terminal when testing the inbound Grafana webhook:
   ``python -m uvicorn aiops.api.app:create_app --factory --port 8000``
3. ``python -B tests/smoke_test_live.py``

Run one group by passing its name, for example ``TestPrometheus``. Missing
configuration, authentication failures, unreachable services, and non-2xx
responses are failures. This suite deliberately has no implicit SKIP path.
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE env file without overwriting shell variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env_file(ROOT / ".env")

from aiops.api.app import build_enricher  # noqa: E402
from aiops.config import Settings, load_runtime_config  # noqa: E402
from aiops.integrations import (  # noqa: E402
    JaegerClient,
    KubernetesClient,
    NotificationClient,
    OpenSearchClient,
    PrometheusClient,
)
from aiops.schemas import CandidateEvent, Feature, NotificationMessage, SignalQuality  # noqa: E402


NAMESPACE = os.getenv("AIOPS_SMOKE_NAMESPACE", "techx-corp-prod")
DEPLOYMENT = os.getenv("AIOPS_SMOKE_DEPLOYMENT", "checkout")


class MissingConfiguration(RuntimeError):
    pass


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def is_placeholder(value: str) -> bool:
    upper = value.upper()
    return (
        not value
        or "CHANGE_ME" in upper
        or "<FILL_IN" in upper
        or value.endswith(".example")
        or ".example/" in value
    )


def required_env(key: str) -> str:
    value = env(key)
    if is_placeholder(value):
        raise MissingConfiguration(f"{key} is missing or still contains a placeholder")
    return value


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    error: str = ""


results: list[TestResult] = []


def smoke(name: str):
    """Run a smoke check with timing and consistent failure reporting."""

    def decorator(func):
        def wrapper():
            start = time.perf_counter()
            try:
                detail = func()
                elapsed = (time.perf_counter() - start) * 1000
                results.append(TestResult(name=name, passed=True, duration_ms=elapsed, detail=str(detail or "")))
                print(f"  PASS  {name}  ({elapsed:.0f}ms)")
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                error = f"{type(exc).__name__}: {exc}"
                results.append(TestResult(name=name, passed=False, duration_ms=elapsed, error=error))
                print(f"  FAIL  {name}  ({elapsed:.0f}ms)")
                print(textwrap.indent(error, "        "))

        wrapper._smoke_name = name
        return wrapper

    return decorator


def print_secret_audit() -> None:
    checks = [
        ("Prometheus token", False, env("AIOPS_PROMETHEUS_TOKEN")),
        ("Jaeger token", False, env("AIOPS_JAEGER_TOKEN")),
        ("Kubernetes bearer token", False, env("AIOPS_KUBERNETES_BEARER_TOKEN")),
        ("Grafana webhook shared secret", True, env("AIOPS_GRAFANA_WEBHOOK_SECRET")),
        ("OpenSearch username", True, env("AIOPS_OPENSEARCH_USERNAME")),
        ("OpenSearch password", True, env("AIOPS_OPENSEARCH_PASSWORD")),
        ("Notification webhook URL", True, env("AIOPS_NOTIFICATION_WEBHOOK_URL")),
        ("Notification token", False, env("AIOPS_NOTIFICATION_TOKEN")),
    ]
    print("Configuration/secret audit (values are never printed):")
    for label, required, value in checks:
        configured = not is_placeholder(value)
        if configured:
            status = "configured"
        elif required:
            status = "MISSING (required)"
        else:
            status = "not set (allowed through port-forward/receiver policy)"
        print(f"  - {label}: {status}")
    print()


# Prometheus -----------------------------------------------------------------


@smoke("prometheus_instant_query")
def test_prometheus_up():
    data = PrometheusClient(settings()).query("up")
    assert data.get("status") == "success", f"unexpected response status: {data.get('status')}"
    series = data.get("data", {}).get("result", [])
    assert series, "query succeeded but returned no series"
    return f"status=success, series={len(series)}"


@smoke("prometheus_query_range")
def test_prometheus_query_range():
    now = datetime.now(UTC).timestamp()
    data = PrometheusClient(settings()).query_range("up", str(now - 3600), str(now), "60")
    assert data.get("status") == "success", f"unexpected response status: {data.get('status')}"
    return f"status=success, series={len(data.get('data', {}).get('result', []))}"


@smoke("prometheus_targets")
def test_prometheus_targets():
    data = PrometheusClient(settings()).targets()
    targets = data.get("data", {}).get("activeTargets", [])
    assert targets, "Prometheus has no active scrape targets"
    return f"active_targets={len(targets)}"


# Jaeger ---------------------------------------------------------------------


@smoke("jaeger_services")
def test_jaeger_services():
    data = JaegerClient(settings()).list_services()
    services = data.get("data", [])
    assert services, "Jaeger returned no services"
    return f"services={len(services)}"


@smoke("jaeger_traces")
def test_jaeger_traces():
    service = env("AIOPS_SMOKE_JAEGER_SERVICE", "frontend")
    data = JaegerClient(settings()).search_traces(service=service, limit=1)
    traces = data.get("data", [])
    return f"service={service}, traces={len(traces)}"


# On-demand enrichment -------------------------------------------------------


@smoke("enrichment_trace_evidence")
def test_enrichment_trace_evidence():
    service = env("AIOPS_SMOKE_ENRICHMENT_SERVICE", env("AIOPS_SMOKE_JAEGER_SERVICE", "frontend"))
    candidate = CandidateEvent(
        detector_id="smoke_enrichment",
        flow="smoke-test",
        service=service,
        severity="SEV2",
        signal_id="smoke_signal",
        value=1.0,
        unit="count",
        window="5m",
        threshold=0.0,
        quality=SignalQuality.VERIFIED,
        reason="smoke_enrichment",
        runbook_id="RB-SMOKE-TEST",
        contributing_signals=("smoke_signal",),
    )
    feature = Feature(
        signal_id="smoke_signal",
        value=1.0,
        unit="count",
        window="5m",
        quality=SignalQuality.VERIFIED,
        status="ready",
    )
    enricher = build_enricher(settings(), load_runtime_config(settings().runtime_config_path))
    enriched = enricher.enrich([candidate], [feature])[0]
    trace_items = [item for item in enriched.evidence if item.source == "trace"]
    failures = [item for item in enriched.evidence if item.source == "enrichment_failure"]

    assert trace_items, f"no trace evidence for service={service}; failures={[item.reference + ':' + item.summary for item in failures]}"
    return f"service={service}, trace_ref={trace_items[0].reference}, evidence={len(enriched.evidence)}"


# OpenSearch -----------------------------------------------------------------


def require_opensearch_credentials() -> None:
    required_env("AIOPS_OPENSEARCH_USERNAME")
    required_env("AIOPS_OPENSEARCH_PASSWORD")


@smoke("opensearch_cluster_info")
def test_opensearch_cluster():
    require_opensearch_credentials()
    data = OpenSearchClient(settings()).info()
    return f"cluster={data.get('cluster_name', 'unknown')}, version={data.get('version', {}).get('number', '?')}"


@smoke("opensearch_cat_indices")
def test_opensearch_indices():
    require_opensearch_credentials()
    indices = OpenSearchClient(settings()).list_indices()
    assert indices, "OpenSearch returned no indices"
    return f"indices={len(indices)}"


@smoke("opensearch_search_logs")
def test_opensearch_search():
    require_opensearch_credentials()
    client = OpenSearchClient(settings())
    candidates = [item.strip() for item in env("AIOPS_SMOKE_OPENSEARCH_INDICES", "otel-logs-*").split(",") if item.strip()]
    last_error: Exception | None = None
    for index in candidates:
        try:
            data = client.search(index=index, body={"query": {"match_all": {}}, "size": 1})
            total = data.get("hits", {}).get("total", 0)
            if isinstance(total, dict):
                total = total.get("value", 0)
            return f"index={index}, total_hits={total}"
        except httpx.HTTPStatusError as exc:
            last_error = exc
    raise RuntimeError(f"no configured OpenSearch index was searchable: {last_error}")


# Kubernetes API -------------------------------------------------------------


@smoke("kubernetes_list_pods")
def test_k8s_list_pods():
    data = KubernetesClient(settings()).list_pods(namespace=NAMESPACE)
    pods = data.get("items", [])
    assert pods, f"namespace {NAMESPACE} contains no pods"
    running = sum(1 for pod in pods if pod.get("status", {}).get("phase") == "Running")
    return f"pods={len(pods)}, running={running}"


@smoke("kubernetes_get_deployment")
def test_k8s_deployment():
    data = KubernetesClient(settings()).get_deployment(namespace=NAMESPACE, name=DEPLOYMENT)
    ready = data.get("status", {}).get("readyReplicas", 0)
    desired = data.get("spec", {}).get("replicas", 0)
    assert ready == desired and desired > 0, f"deployment is not ready: ready={ready}, desired={desired}"
    return f"deployment={DEPLOYMENT}, ready={ready}/{desired}"


# Grafana and inbound webhook ------------------------------------------------


@smoke("grafana_health")
def test_grafana_health():
    base_url = env("AIOPS_SMOKE_GRAFANA_BASE_URL", "http://localhost:3000").rstrip("/")
    response = httpx.get(f"{base_url}/api/health", timeout=10)
    response.raise_for_status()
    data = response.json()
    assert data.get("database") == "ok", f"Grafana database is not healthy: {data}"
    return f"database={data.get('database')}, version={data.get('version', '?')}"


@smoke("grafana_webhook_inbound")
def test_grafana_webhook():
    base_url = env("AIOPS_SMOKE_AIOPS_BASE_URL", "http://localhost:8000").rstrip("/")
    secret = required_env("AIOPS_GRAFANA_WEBHOOK_SECRET")
    payload = {
        "receiver": "aiops-smoke-test",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "AIOpsSmokeTest", "severity": "warning", "service": "checkout"},
                "annotations": {"summary": "Synthetic AIOps webhook smoke test"},
                "startsAt": datetime.now(UTC).isoformat(),
                "endsAt": None,
                "generatorURL": f"{base_url}/smoke-test",
                "fingerprint": "aiops-smoke-test-001",
            }
        ],
    }
    response = httpx.post(
        f"{base_url}/api/v1/events/grafana",
        json=payload,
        headers={"X-AIOps-Grafana-Secret": secret},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    assert data.get("source") == "grafana", f"unexpected webhook response: {data}"
    return f"source=grafana, alert_id={data.get('alert_id')}"


# Notification webhook -------------------------------------------------------


@smoke("notification_webhook")
def test_notification_webhook():
    required_env("AIOPS_NOTIFICATION_WEBHOOK_URL")
    message = NotificationMessage(
        incident_id="smoke-test-inc-001",
        severity="SEV2",
        state="open",
        title="AIOps notification smoke test",
        summary="Synthetic smoke-test notification. No operator action is required.",
        flow="smoke-test",
        service="smoke-test",
        likely_dependency="none",
        runbook_id="RB-SMOKE-TEST",
    )
    response = NotificationClient(settings()).send(message)
    return f"receiver_response={response}"


ALL_TESTS = [
    test_prometheus_up,
    test_prometheus_query_range,
    test_prometheus_targets,
    test_jaeger_services,
    test_jaeger_traces,
    test_enrichment_trace_evidence,
    test_opensearch_cluster,
    test_opensearch_indices,
    test_opensearch_search,
    test_k8s_list_pods,
    test_k8s_deployment,
    test_grafana_health,
    test_grafana_webhook,
    test_notification_webhook,
]

GROUPS = {
    "TestPrometheus": [test_prometheus_up, test_prometheus_query_range, test_prometheus_targets],
    "TestJaeger": [test_jaeger_services, test_jaeger_traces],
    "TestEnrichment": [test_enrichment_trace_evidence],
    "TestOpenSearch": [test_opensearch_cluster, test_opensearch_indices, test_opensearch_search],
    "TestKubernetes": [test_k8s_list_pods, test_k8s_deployment],
    "TestGrafana": [test_grafana_health, test_grafana_webhook],
    "TestNotification": [test_notification_webhook],
}


def main() -> None:
    print_secret_audit()
    if len(sys.argv) > 1:
        group_name = sys.argv[1]
        tests_to_run = GROUPS.get(group_name)
        if tests_to_run is None:
            print(f"Unknown test group: {group_name}")
            print(f"Available: {', '.join(GROUPS)}")
            raise SystemExit(2)
        title = group_name
    else:
        tests_to_run = ALL_TESTS
        title = "All required endpoints"

    print(f"AIOps live smoke test - {title}\n")
    for test_fn in tests_to_run:
        test_fn()

    failed = [result for result in results if not result.passed]
    print("\nSummary:")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        detail = result.detail or result.error
        print(f"  {status:<4} {result.name:<35} {result.duration_ms:>7.0f}ms  {detail[:120]}")
    print(f"\nTotal={len(results)} Passed={len(results) - len(failed)} Failed={len(failed)}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
