"""Deterministic integration-client smoke/contract tests.

The suite uses MockTransport for success and failure paths so optional or
mutating integrations can be verified without contacting a live system.
"""

import base64
import json
import secrets
import unittest
from pathlib import Path

import httpx

from aiops.config import Settings
from aiops.integrations import (
    AieClient,
    CostClient,
    JaegerClient,
    KubernetesClient,
    LiveExecutorClient,
    NotificationClient,
    OpenSearchClient,
    PrometheusClient,
)
from aiops.integrations.http import safe_error_text
from aiops.schemas import NotificationMessage


ROOT = Path(__file__).resolve().parent.parent
TEST_ENV_FILES = (ROOT / ".env", ROOT / ".env.live")


def settings() -> Settings:
    return Settings(_env_file=TEST_ENV_FILES)


def json_response(status_code: int, payload: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload or {"ok": status_code < 400})

    return handler


def notification_message() -> NotificationMessage:
    return NotificationMessage(
        incident_id="inc-1",
        severity="SEV1",
        state="open",
        title="checkout",
        summary="summary",
        flow="checkout",
        service="checkout",
        likely_dependency="unknown",
        runbook_id="RB-CHECKOUT-SLO",
    )


class IntegrationClientTest(unittest.TestCase):
    def test_prometheus_uses_configured_url_and_optional_token(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

        cfg = settings()
        result = PrometheusClient(cfg, transport=httpx.MockTransport(handler)).query("up")

        self.assertEqual(result["status"], "success")
        self.assertEqual(seen[0].url.path, "/api/v1/query")
        self.assertEqual(seen[0].url.params["query"], "up")
        if cfg.prometheus_token:
            self.assertTrue(
                secrets.compare_digest(seen[0].headers.get("authorization", ""), f"Bearer {cfg.prometheus_token}")
            )
        else:
            self.assertNotIn("authorization", seen[0].headers)

    def test_prometheus_raises_on_http_failure(self):
        client = PrometheusClient(settings(), transport=httpx.MockTransport(json_response(503)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.query("up")

        self.assertEqual(caught.exception.response.status_code, 503)

    def test_jaeger_success(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": []})

        result = JaegerClient(settings(), transport=httpx.MockTransport(handler)).search_traces(service="checkout")

        self.assertEqual(result, {"data": []})
        self.assertEqual(seen[0].url.path, "/jaeger/ui/api/traces")

    def test_jaeger_raises_on_http_failure(self):
        client = JaegerClient(settings(), transport=httpx.MockTransport(json_response(401)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.search_traces(service="checkout")

        self.assertEqual(caught.exception.response.status_code, 401)

    def test_opensearch_uses_basic_auth(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"hits": {"total": {"value": 0}, "hits": []}})

        cfg = settings()
        OpenSearchClient(cfg, transport=httpx.MockTransport(handler)).search(
            index="logs-*",
            body={"query": {"match_all": {}}},
        )

        raw = f"{cfg.opensearch_username}:{cfg.opensearch_password}".encode("utf-8")
        expected = "Basic " + base64.b64encode(raw).decode("ascii")
        self.assertTrue(secrets.compare_digest(seen[0].headers.get("authorization", ""), expected))
        self.assertTrue(
            secrets.compare_digest(seen[0].headers.get("x-aiops-account", ""), cfg.opensearch_account)
        )

    def test_opensearch_raises_on_http_failure(self):
        client = OpenSearchClient(settings(), transport=httpx.MockTransport(json_response(403)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.search(index="logs-*", body={"query": {"match_all": {}}})

        self.assertEqual(caught.exception.response.status_code, 403)

    def test_kubernetes_success(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"metadata": {"name": "checkout"}})

        result = KubernetesClient(settings(), transport=httpx.MockTransport(handler)).get_deployment(
            namespace="tf2",
            name="checkout",
        )

        self.assertEqual(result["metadata"]["name"], "checkout")
        self.assertEqual(seen[0].url.path, "/apis/apps/v1/namespaces/tf2/deployments/checkout")

    def test_kubernetes_raises_on_http_failure(self):
        client = KubernetesClient(settings(), transport=httpx.MockTransport(json_response(500)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.get_deployment(namespace="tf2", name="checkout")

        self.assertEqual(caught.exception.response.status_code, 500)

    def test_cost_success(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"current": True})

        result = CostClient(settings(), transport=httpx.MockTransport(handler)).get_status()

        self.assertEqual(result, {"current": True})
        self.assertEqual(seen[0].url.path, "/status")

    def test_cost_raises_on_http_failure(self):
        client = CostClient(settings(), transport=httpx.MockTransport(json_response(503)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.get_status()

        self.assertEqual(caught.exception.response.status_code, 503)

    def test_live_executor_success(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(202, json={"accepted": True, "mode": "dry-run"})

        action = {"action_id": "act-smoke", "mode": "dry-run"}
        result = LiveExecutorClient(settings(), transport=httpx.MockTransport(handler)).submit_action(action)

        self.assertEqual(result["accepted"], True)
        self.assertEqual(seen[0].method, "POST")
        self.assertEqual(seen[0].url.path, "/actions")
        self.assertEqual(json.loads(seen[0].content), action)

    def test_live_executor_raises_on_http_failure(self):
        client = LiveExecutorClient(settings(), transport=httpx.MockTransport(json_response(409)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.submit_action({"action_id": "act-smoke", "mode": "dry-run"})

        self.assertEqual(caught.exception.response.status_code, 409)

    def test_aie_success(self):
        result = AieClient(settings(), transport=httpx.MockTransport(json_response(200, {"current": True}))).get_status()

        self.assertEqual(result, {"current": True})

    def test_notification_client_sends_message(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(202, json={"accepted": True})

        cfg = settings().model_copy(update={"notification_provider": "generic"})
        response = NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(notification_message())

        self.assertEqual(response["accepted"], True)
        self.assertTrue(secrets.compare_digest(str(seen[0].url), cfg.notification_webhook_url))
        if cfg.notification_token:
            self.assertTrue(
                secrets.compare_digest(seen[0].headers.get("authorization", ""), f"Bearer {cfg.notification_token}")
            )
        else:
            self.assertNotIn("authorization", seen[0].headers)
        self.assertEqual(json.loads(seen[0].content)["incident_id"], "inc-1")

    def test_notification_client_raises_on_http_failure(self):
        client = NotificationClient(settings(), transport=httpx.MockTransport(json_response(500)))

        with self.assertRaises(httpx.HTTPStatusError) as caught:
            client.send(notification_message())

        self.assertEqual(caught.exception.response.status_code, 500)

    def test_notification_client_auto_detects_discord_and_sends_embed(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        cfg = settings().model_copy(
            update={
                "notification_provider": "auto",
                "notification_webhook_url": "https://discord.com/api/webhooks/123/secret-token",
            }
        )
        message = NotificationMessage(
            incident_id="inc-discord-1",
            severity="SEV1",
            state="open",
            title="checkout unavailable",
            summary="Checkout error ratio exceeded the SLO.",
            flow="checkout",
            service="checkout",
            likely_dependency="postgresql",
            runbook_id="RB-CHECKOUT-SLO",
        )

        response = NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(message)

        self.assertEqual(response, {"status_code": 204})
        self.assertEqual(str(seen[0].url), "https://discord.com/api/webhooks/123/secret-token")
        self.assertNotIn("authorization", seen[0].headers)
        self.assertNotIn("x-aiops-account", seen[0].headers)
        payload = json.loads(seen[0].content)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["title"], "[SEV1] checkout unavailable")
        self.assertEqual(payload["embeds"][0]["color"], 0xE74C3C)
        fields = {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}
        self.assertEqual(fields["Likely dependency"], "postgresql")
        self.assertEqual(fields["Runbook"], "RB-CHECKOUT-SLO")

    def test_notification_client_accepts_empty_success_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        message = NotificationMessage(
            incident_id="inc-1",
            severity="SEV2",
            state="open",
            title="smoke",
            summary="summary",
            flow="smoke",
            service="smoke",
            likely_dependency="none",
            runbook_id="RB-SMOKE",
        )
        response = NotificationClient(settings(), transport=httpx.MockTransport(handler)).send(message)

        self.assertEqual(response, {"status_code": 204})

    def test_safe_error_text_does_not_expose_webhook_secret(self):
        secret = "do-not-print-this-webhook-token"
        request = httpx.Request(
            "POST",
            f"https://discord.com/api/webhooks/123/{secret}",
            headers={"Authorization": "Bearer do-not-print-this-bearer-token"},
        )
        response = httpx.Response(500, request=request)
        error = httpx.HTTPStatusError("server failed", request=request, response=response)

        rendered = safe_error_text(error)

        self.assertEqual(rendered, "HTTPStatusError: HTTP 500")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("do-not-print-this-bearer-token", rendered)
        self.assertNotIn("discord.com", rendered)

    def test_safe_error_text_does_not_expose_generic_exception_message(self):
        secret = "do-not-print-this-generic-secret"

        rendered = safe_error_text(RuntimeError(f"backend echoed {secret}"))

        self.assertEqual(rendered, "RuntimeError: operation failed")
        self.assertNotIn(secret, rendered)

    def test_safe_error_text_does_not_expose_connect_error_url(self):
        secret = "do-not-print-this-connect-token"
        request = httpx.Request("POST", f"https://notification.example/hooks/{secret}")

        rendered = safe_error_text(httpx.ConnectError(f"failed to connect to {request.url}", request=request))

        self.assertEqual(rendered, "ConnectError: request failed")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("notification.example", rendered)


if __name__ == "__main__":
    unittest.main()
