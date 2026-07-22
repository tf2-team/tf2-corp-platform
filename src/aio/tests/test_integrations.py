#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import base64
import json
import unittest

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
from aiops.schemas import NotificationMessage


def settings() -> Settings:
    return Settings()


def fixed_settings(**updates) -> Settings:
    return settings().model_copy(update=updates)


class IntegrationClientTest(unittest.TestCase):
    def test_prometheus_uses_env_url_and_token(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

        cfg = fixed_settings(
            prometheus_base_url="https://prometheus.example",
            prometheus_token="CHANGE_ME_PROMETHEUS_TOKEN",
            prometheus_account="CHANGE_ME_PROMETHEUS_ACCOUNT",
        )
        result = PrometheusClient(cfg, transport=httpx.MockTransport(handler)).query("up")

        self.assertEqual(result["status"], "success")
        self.assertEqual(str(seen[0].url), "https://prometheus.example/api/v1/query?query=up")
        self.assertEqual(seen[0].headers["authorization"], "Bearer CHANGE_ME_PROMETHEUS_TOKEN")

    def test_prometheus_uses_configured_timeout(self):
        cfg = fixed_settings(prometheus_base_url="https://prometheus.example", prometheus_timeout_seconds=42.0)

        client = PrometheusClient(cfg)

        self.assertEqual(client._http._client.timeout.read, 42.0)

    def test_all_direct_clients_build_expected_requests(self):
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        cfg = settings()

        JaegerClient(cfg, transport=transport).search_traces(service="checkout")
        OpenSearchClient(cfg, transport=transport).search(index="logs-*", body={"query": {"match_all": {}}})
        KubernetesClient(cfg, transport=transport).get_deployment(namespace="tf2", name="checkout")
        AieClient(cfg, transport=transport).get_status()
        CostClient(cfg, transport=transport).get_status()
        LiveExecutorClient(cfg, transport=transport).submit_action({"action_id": "act-1"})

        self.assertIn(("GET", "/jaeger/ui/api/traces"), calls)
        self.assertIn(("POST", "/logs-*/_search"), calls)
        self.assertIn(("GET", "/apis/apps/v1/namespaces/tf2/deployments/checkout"), calls)
        self.assertIn(("GET", "/status"), calls)
        self.assertIn(("POST", "/actions"), calls)

    def test_opensearch_uses_basic_auth(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"hits": {"total": {"value": 0}, "hits": []}})

        cfg = fixed_settings(
            opensearch_base_url="https://opensearch.example",
            opensearch_username="CHANGE_ME_OPENSEARCH_USERNAME",
            opensearch_password="CHANGE_ME_OPENSEARCH_PASSWORD",
            opensearch_account="CHANGE_ME_OPENSEARCH_ACCOUNT",
        )
        OpenSearchClient(cfg, transport=httpx.MockTransport(handler)).search(
            index="logs-*",
            body={"query": {"match_all": {}}},
        )

        raw = b"CHANGE_ME_OPENSEARCH_USERNAME:CHANGE_ME_OPENSEARCH_PASSWORD"
        expected = "Basic " + base64.b64encode(raw).decode("ascii")
        self.assertEqual(seen[0].headers["authorization"], expected)
        self.assertEqual(seen[0].headers["x-aiops-account"], "CHANGE_ME_OPENSEARCH_ACCOUNT")

    def test_notification_client_sends_message(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(202, json={"accepted": True})

        message = NotificationMessage(
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
        cfg = fixed_settings(
            notification_webhook_url="https://notification.example",
            notification_token="CHANGE_ME_NOTIFICATION_TOKEN",
            notification_account="CHANGE_ME_NOTIFICATION_ACCOUNT",
        )
        response = NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(message)

        self.assertEqual(response["accepted"], True)
        self.assertEqual(str(seen[0].url), "https://notification.example")
        self.assertEqual(seen[0].headers["authorization"], "Bearer CHANGE_ME_NOTIFICATION_TOKEN")
        self.assertEqual(json.loads(seen[0].content)["incident_id"], "inc-1")

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

    def test_notification_client_grafana_provider_uses_json_webhook(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(202, json={"routed": True})

        cfg = fixed_settings(
            notification_provider="grafana",
            notification_webhook_url="https://grafana.example/api/plugins/grafana-oncall-app/resources/integrations/v1/example/",
            notification_token="grafana-token",
            notification_account="tf2",
        )
        message = NotificationMessage(
            incident_id="inc-grafana-1",
            severity="SEV1",
            state="open",
            title="checkout",
            summary="summary",
            flow="checkout",
            service="checkout",
            likely_dependency="unknown",
            runbook_id="RB-CHECKOUT-SLO",
        )

        response = NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(message)

        self.assertEqual(response, {"routed": True})
        self.assertEqual(seen[0].headers["authorization"], "Bearer grafana-token")
        self.assertEqual(json.loads(seen[0].content)["incident_id"], "inc-grafana-1")


if __name__ == "__main__":
    unittest.main()
