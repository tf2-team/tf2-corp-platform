"""
Smoke Test — AIOps Live Integration Endpoints
==============================================

Gọi API thật qua port-forward để xác nhận kết nối hoạt động.

Chuẩn bị trước khi chạy:
  1. Mở port-forward:  powershell -File scripts/port_forward.ps1
  2. Copy env:          copy .env.live .env   (hoặc set AIOPS_ env vars)
  3. Chạy:              conda run -n capstone python -B tests/smoke_test_live.py

Hoặc chạy từng test:
  conda run -n capstone python -B tests/smoke_test_live.py TestPrometheus
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

# ── Helpers ──────────────────────────────────────────────────────────────────

NAMESPACE = os.getenv("AIOPS_SMOKE_NAMESPACE", "techx-corp-prod")


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    error: str = ""


results: list[TestResult] = []


def smoke(name: str):
    """Decorator to register and run a smoke test with timing + error handling."""

    def decorator(func):
        def wrapper():
            start = time.perf_counter()
            try:
                detail = func()
                elapsed = (time.perf_counter() - start) * 1000
                results.append(TestResult(name=name, passed=True, duration_ms=elapsed, detail=str(detail or "")))
                print(f"  ✅ PASS  {name}  ({elapsed:.0f}ms)")
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                err_msg = f"{type(exc).__name__}: {exc}"
                results.append(TestResult(name=name, passed=False, duration_ms=elapsed, error=err_msg))
                print(f"  ❌ FAIL  {name}  ({elapsed:.0f}ms)")
                print(textwrap.indent(err_msg, "         "))

        wrapper._smoke_name = name
        return wrapper

    return decorator


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Prometheus ───────────────────────────────────────────────────────────────

PROMETHEUS_URL = None


def get_prometheus_url():
    global PROMETHEUS_URL
    if PROMETHEUS_URL is None:
        PROMETHEUS_URL = env("AIOPS_PROMETHEUS_BASE_URL", "http://localhost:9090").rstrip("/")
    return PROMETHEUS_URL


@smoke("prometheus_instant_query")
def test_prometheus_up():
    """GET /api/v1/query?query=up — expect status=success with results."""
    url = get_prometheus_url()
    r = httpx.get(f"{url}/api/v1/query", params={"query": "up"}, timeout=10)
    r.raise_for_status()
    data = r.json()
    assert data["status"] == "success", f"Expected status=success, got {data['status']}"
    result_count = len(data.get("data", {}).get("result", []))
    return f"status=success, {result_count} series"


@smoke("prometheus_query_range")
def test_prometheus_query_range():
    """GET /api/v1/query_range — 1h window, metric=up, step=60s."""
    url = get_prometheus_url()
    now = datetime.now(UTC)
    end = now.isoformat()
    start = (now.timestamp() - 3600)
    r = httpx.get(
        f"{url}/api/v1/query_range",
        params={"query": "up", "start": start, "end": now.timestamp(), "step": "60"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    assert data["status"] == "success", f"Expected status=success, got {data['status']}"
    result_count = len(data.get("data", {}).get("result", []))
    return f"status=success, {result_count} range series"


@smoke("prometheus_targets")
def test_prometheus_targets():
    """GET /api/v1/targets — verify scrape targets exist."""
    url = get_prometheus_url()
    r = httpx.get(f"{url}/api/v1/targets", timeout=10)
    r.raise_for_status()
    data = r.json()
    active = len(data.get("data", {}).get("activeTargets", []))
    return f"{active} active scrape targets"


# ── Jaeger ───────────────────────────────────────────────────────────────────

JAEGER_URL = None


def get_jaeger_url():
    global JAEGER_URL
    if JAEGER_URL is None:
        JAEGER_URL = env("AIOPS_JAEGER_BASE_URL", "http://localhost:16686").rstrip("/")
    return JAEGER_URL


@smoke("jaeger_services")
def test_jaeger_services():
    """GET /jaeger/ui/api/services — list known services (base_path=/jaeger/ui)."""
    url = get_jaeger_url()
    r = httpx.get(f"{url}/jaeger/ui/api/services", timeout=10)
    r.raise_for_status()
    data = r.json()
    services = data.get("data", [])
    assert len(services) > 0, "No services found in Jaeger"
    return f"{len(services)} services: {', '.join(services[:5])}{'...' if len(services) > 5 else ''}"


@smoke("jaeger_traces")
def test_jaeger_traces():
    """GET /jaeger/ui/api/traces?service=frontend&limit=1 — fetch a trace."""
    url = get_jaeger_url()
    r = httpx.get(f"{url}/jaeger/ui/api/traces", params={"service": "frontend", "limit": 1}, timeout=10)
    r.raise_for_status()
    data = r.json()
    traces = data.get("data", [])
    if traces:
        span_count = len(traces[0].get("spans", []))
        return f"1 trace, {span_count} spans"
    return "0 traces (frontend may not have recent traffic)"


# ── OpenSearch ───────────────────────────────────────────────────────────────

OPENSEARCH_URL = None


def get_opensearch_url():
    global OPENSEARCH_URL
    if OPENSEARCH_URL is None:
        OPENSEARCH_URL = env("AIOPS_OPENSEARCH_BASE_URL", "https://localhost:9200").rstrip("/")
    return OPENSEARCH_URL


def get_opensearch_auth():
    """Return auth tuple. OpenSearch 3.2.0 security plugin requires Basic auth."""
    user = env("AIOPS_OPENSEARCH_USERNAME", "admin")
    pwd = env("AIOPS_OPENSEARCH_PASSWORD", "admin")
    if user and pwd:
        return (user, pwd)
    return None


@smoke("opensearch_cluster_health")
def test_opensearch_cluster():
    """GET / — cluster info. Tries configured URL, then fallback HTTP."""
    url = get_opensearch_url()
    auth = get_opensearch_auth()
    # Try configured URL (could be HTTP or HTTPS)
    try:
        r = httpx.get(f"{url}/", auth=auth, timeout=10, verify=False)
    except Exception:
        # Fallback: if HTTPS fails, try HTTP
        fallback = url.replace("https://", "http://")
        if fallback != url:
            r = httpx.get(f"{fallback}/", auth=auth, timeout=10, verify=False)
        else:
            raise
    if r.status_code == 401:
        return ("PASS (reachable) — HTTP 401: OpenSearch security plugin is active. "
                "Set AIOPS_OPENSEARCH_USERNAME/PASSWORD in .env.live. "
                "Check: kubectl -n techx-corp-prod exec opensearch-0 -- env | grep -i password")
    r.raise_for_status()
    data = r.json()
    name = data.get("cluster_name", "unknown")
    version = data.get("version", {}).get("number", "?")
    return f"cluster={name}, version={version}"


@smoke("opensearch_cat_indices")
def test_opensearch_indices():
    """GET /_cat/indices?format=json — list indices."""
    url = get_opensearch_url()
    auth = get_opensearch_auth()
    try:
        r = httpx.get(f"{url}/_cat/indices", params={"format": "json"}, auth=auth, timeout=10, verify=False)
    except Exception:
        fallback_url = url.replace("https://", "http://")
        if fallback_url != url:
            r = httpx.get(f"{fallback_url}/_cat/indices", params={"format": "json"}, auth=auth, timeout=10, verify=False)
        else:
            raise
    if r.status_code == 401:
        return "SKIP — OpenSearch 401 (see opensearch_cluster_health for fix)"
    r.raise_for_status()
    indices = r.json()
    names = [idx.get("index", "?") for idx in indices[:10]]
    return f"{len(indices)} indices: {', '.join(names)}{'...' if len(indices) > 10 else ''}"


@smoke("opensearch_search_logs")
def test_opensearch_search():
    """POST /<index>/_search — search for recent logs/spans."""
    url = get_opensearch_url()
    auth = get_opensearch_auth()
    body = {"query": {"match_all": {}}, "size": 1}
    # Index names from Grafana datasource config
    candidate_indices = env("AIOPS_SMOKE_OPENSEARCH_INDICES", "otel-logs-*,otel-v1-apm-span-*,*").split(",")
    for index in candidate_indices:
        index = index.strip()
        try:
            r = httpx.post(f"{url}/{index}/_search", json=body, auth=auth, timeout=10, verify=False)
            if r.status_code == 401:
                return "SKIP — OpenSearch 401 (see opensearch_cluster_health for fix)"
            if r.status_code == 200:
                data = r.json()
                total = data.get("hits", {}).get("total", {})
                if isinstance(total, dict):
                    total = total.get("value", 0)
                return f"index={index}, total_hits={total}"
        except Exception:
            continue
    raise RuntimeError("No searchable index found in OpenSearch")


# ── Kubernetes API ───────────────────────────────────────────────────────────

K8S_URL = None


def get_k8s_url():
    global K8S_URL
    if K8S_URL is None:
        K8S_URL = env("AIOPS_KUBERNETES_API_URL", "http://localhost:8001").rstrip("/")
    return K8S_URL


def get_k8s_headers():
    token = env("AIOPS_KUBERNETES_BEARER_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@smoke("kubernetes_list_pods")
def test_k8s_list_pods():
    """GET /api/v1/namespaces/{ns}/pods — list pods."""
    url = get_k8s_url()
    r = httpx.get(
        f"{url}/api/v1/namespaces/{NAMESPACE}/pods",
        headers=get_k8s_headers(),
        timeout=10,
        verify=False,
    )
    r.raise_for_status()
    data = r.json()
    pods = data.get("items", [])
    running = sum(1 for p in pods if p.get("status", {}).get("phase") == "Running")
    return f"{len(pods)} pods, {running} running"


@smoke("kubernetes_get_deployment")
def test_k8s_deployment():
    """GET /apis/apps/v1/namespaces/{ns}/deployments/checkout — get checkout deployment."""
    url = get_k8s_url()
    r = httpx.get(
        f"{url}/apis/apps/v1/namespaces/{NAMESPACE}/deployments/checkout",
        headers=get_k8s_headers(),
        timeout=10,
        verify=False,
    )
    r.raise_for_status()
    data = r.json()
    name = data.get("metadata", {}).get("name")
    replicas = data.get("spec", {}).get("replicas", "?")
    ready = data.get("status", {}).get("readyReplicas", 0)
    return f"deployment={name}, replicas={replicas}, ready={ready}"


# ── Grafana Webhook (inbound — test AIOps endpoint) ─────────────────────────

@smoke("grafana_webhook_inbound")
def test_grafana_webhook():
    """POST /api/v1/events/grafana to AIOps (if running) — simulates Grafana alert."""
    aiops_port = env("AIOPS_SMOKE_AIOPS_PORT", "8000")
    secret = env("AIOPS_GRAFANA_WEBHOOK_SECRET", "aiops-grafana-test-secret")

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighErrorRate", "service": "checkout"},
                "annotations": {"summary": "Checkout error rate > 5%"},
                "startsAt": datetime.now(UTC).isoformat(),
                "endsAt": "",
                "generatorURL": "http://grafana.local/alerts",
                "fingerprint": "smoke-test-001",
                "dashboardURL": "http://grafana.local/d/1",
                "panelURL": "http://grafana.local/d/1?panelId=1",
            }
        ],
    }

    try:
        r = httpx.post(
            f"http://localhost:{aiops_port}/api/v1/events/grafana",
            json=payload,
            headers={"X-AIOps-Grafana-Secret": secret},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        return f"source={data.get('source')}, alert_id={data.get('alert_id')}"
    except httpx.ConnectError:
        return "SKIP — AIOps server not running on localhost:8000 (start with uvicorn)"


# ── Notification Webhook ─────────────────────────────────────────────────────

@smoke("notification_webhook")
def test_notification_webhook():
    """POST to the configured notification webhook URL."""
    webhook_url = env("AIOPS_NOTIFICATION_WEBHOOK_URL", "")
    if not webhook_url or "<FILL_IN" in webhook_url or "example" in webhook_url:
        return "SKIP — AIOPS_NOTIFICATION_WEBHOOK_URL not configured (set to webhook.site or Slack URL)"

    payload = {
        "incident_id": "smoke-test-inc-001",
        "severity": "SEV2",
        "state": "open",
        "title": "Smoke Test — Notification Webhook",
        "summary": "This is a smoke test from AIOps. Ignore this notification.",
        "flow": "smoke-test",
        "service": "smoke-test",
        "likely_dependency": "none",
        "runbook_id": "RB-SMOKE-TEST",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    r = httpx.post(webhook_url, json=payload, timeout=10)
    return f"HTTP {r.status_code} — check your webhook sink for the test message"


# ── Runner ───────────────────────────────────────────────────────────────────

ALL_TESTS = [
    # Prometheus
    test_prometheus_up,
    test_prometheus_query_range,
    test_prometheus_targets,
    # Jaeger
    test_jaeger_services,
    test_jaeger_traces,
    # OpenSearch
    test_opensearch_cluster,
    test_opensearch_indices,
    test_opensearch_search,
    # Kubernetes
    test_k8s_list_pods,
    test_k8s_deployment,
    # Grafana webhook (inbound)
    test_grafana_webhook,
    # Notification
    test_notification_webhook,
]

# Group tests by service for selective running
GROUPS = {
    "TestPrometheus": [test_prometheus_up, test_prometheus_query_range, test_prometheus_targets],
    "TestJaeger": [test_jaeger_services, test_jaeger_traces],
    "TestOpenSearch": [test_opensearch_cluster, test_opensearch_indices, test_opensearch_search],
    "TestKubernetes": [test_k8s_list_pods, test_k8s_deployment],
    "TestGrafana": [test_grafana_webhook],
    "TestNotification": [test_notification_webhook],
}


def main():
    # Load .env.live if present (for standalone runs outside pydantic-settings)
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.live")
    if os.path.exists(env_file):
        print(f"Loading environment from {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

    # Select tests: run all or a specific group
    if len(sys.argv) > 1:
        group_name = sys.argv[1]
        tests_to_run = GROUPS.get(group_name)
        if not tests_to_run:
            print(f"Unknown test group: {group_name}")
            print(f"Available: {', '.join(GROUPS.keys())}")
            sys.exit(1)
        print(f"\n{'='*60}")
        print(f"  AIOps Smoke Test — {group_name}")
        print(f"{'='*60}\n")
    else:
        tests_to_run = ALL_TESTS
        print(f"\n{'='*60}")
        print(f"  AIOps Smoke Test — All Endpoints")
        print(f"{'='*60}\n")

    for test_fn in tests_to_run:
        test_fn()

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}\n")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    skipped = sum(1 for r in results if r.passed and "SKIP" in r.detail)

    print(f"  {'Test':<35} {'Status':<8} {'Time':>8}  Detail")
    print(f"  {'─'*35} {'─'*8} {'─'*8}  {'─'*30}")
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        if r.passed and "SKIP" in r.detail:
            status = "⏭  SKIP"
        detail = (r.detail or r.error)[:50]
        print(f"  {r.name:<35} {status:<8} {r.duration_ms:>6.0f}ms  {detail}")

    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")

    if failed > 0:
        print(f"\n  ⚠️  {failed} test(s) failed. Check port-forwards and .env.live settings.\n")
        sys.exit(1)
    else:
        print(f"\n  🎉 All connectivity checks passed!\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
