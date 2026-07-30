#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import base64
import json
import unittest
from datetime import UTC, datetime

import httpx

from aiops.config import Settings
from aiops.integrations import (
    JaegerClient,
    KubernetesClient,
    LiveExecutorClient,
    NotificationClient,
    OpenSearchClient,
    PrometheusClient,
)
from aiops.schemas import NotificationMessage


def settings() -> Settings:
    return Settings(_env_file=None)


def fixed_settings(**updates) -> Settings:
    return settings().model_copy(
        update={"notification_dev_webhook_url": "", "notification_user_webhook_url": "", **updates}
    )


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
        cfg = fixed_settings(
            jaeger_base_url="https://jaeger.example/jaeger/ui",
            opensearch_base_url="https://opensearch.example",
            kubernetes_api_url="https://kubernetes.example",
            live_executor_url="https://executor.example",
        )

        JaegerClient(cfg, transport=transport).search_traces(service="checkout")
        OpenSearchClient(cfg, transport=transport).search(index="logs-*", body={"query": {"match_all": {}}})
        KubernetesClient(cfg, transport=transport).get_deployment(namespace="tf2", name="checkout")
        LiveExecutorClient(cfg, transport=transport).plan({"action_id": "act-1"})

        self.assertIn(("GET", "/jaeger/ui/api/traces"), calls)
        self.assertIn(("POST", "/logs-*/_search"), calls)
        self.assertIn(("GET", "/apis/apps/v1/namespaces/tf2/deployments/checkout"), calls)
        self.assertIn(("POST", "/v1/actions/plan"), calls)

    def test_live_executor_accepts_contract_blocking_response_with_http_409(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "ok": True,
                    "allowed": False,
                    "executed": False,
                    "status": "blocked",
                    "reasons": ["target_cooldown"],
                },
            )

        client = LiveExecutorClient(
            fixed_settings(
                live_executor_url="https://executor.example",
                live_executor_account="aiops-runtime",
            ),
            transport=httpx.MockTransport(handler),
        )
        response = client.execute({"request_id": "req-409"})

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reasons"], ["target_cooldown"])

    def test_live_executor_logs_runbook_and_action_type(self):
        client = LiveExecutorClient(
            fixed_settings(live_executor_url="https://executor.example"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "planned"})),
        )

        with self.assertLogs("aiops.integrations.live_executor", level="INFO") as logs:
            client.plan(
                {
                    "incident_id": "inc-1",
                    "runbook_id": "RB-SERVICE-RESOURCE",
                    "action_type": "scale",
                    "target": "checkout",
                }
            )

        self.assertIn(
            "operation=plan incident=inc-1 runbook=RB-SERVICE-RESOURCE action_type=scale target=checkout",
            logs.output[0],
        )

    def test_live_executor_readiness_calls_ready_endpoint(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": "ready"})

        client = LiveExecutorClient(
            fixed_settings(live_executor_url="https://executor.example"),
            transport=httpx.MockTransport(handler),
        )
        try:
            self.assertTrue(client.ready())
            self.assertEqual(seen[0].url.path, "/readyz")
        finally:
            client.close()

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
        client = NotificationClient(cfg, transport=httpx.MockTransport(handler))
        response = client.send(message)
        client.close()

        self.assertEqual(response["accepted"], True)
        self.assertEqual(str(seen[0].url), "https://notification.example")
        self.assertEqual(seen[0].headers["authorization"], "Bearer CHANGE_ME_NOTIFICATION_TOKEN")
        self.assertEqual(json.loads(seen[0].content)["incident_id"], "inc-1")
        with self.assertRaises(RuntimeError):
            client.send(message)

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

        before_send = datetime.now(UTC)
        response = NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(message)
        after_send = datetime.now(UTC)

        self.assertEqual(response, {"status_code": 204})
        self.assertEqual(str(seen[0].url), "https://discord.com/api/webhooks/123/secret-token")
        self.assertNotIn("authorization", seen[0].headers)
        self.assertNotIn("x-aiops-account", seen[0].headers)
        payload = json.loads(seen[0].content)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["title"], "[SEV1] checkout unavailable")
        self.assertEqual(payload["embeds"][0]["color"], 0xE74C3C)
        sent_at = datetime.fromisoformat(payload["embeds"][0]["timestamp"])
        self.assertLessEqual(before_send, sent_at)
        self.assertLessEqual(sent_at, after_send)
        fields = {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}
        self.assertEqual(fields["Likely dependency"], "postgresql")
        self.assertEqual(fields["Runbook"], "RB-CHECKOUT-SLO")

    def test_notification_client_sends_to_dev_and_user_discord_channels(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        cfg = fixed_settings(
            notification_provider="auto",
            notification_dev_webhook_url="https://discord.com/api/webhooks/dev/token",
            notification_user_webhook_url="https://discord.com/api/webhooks/user/token",
        )
        message = NotificationMessage(
            incident_id="inc-broadcast",
            severity="SEV2",
            state="open",
            title="cart incident",
            summary="summary",
            flow="checkout",
            service="cart",
            likely_dependency="unknown",
            runbook_id="RB-CART-ERROR-RATE",
        )

        client = NotificationClient(cfg, transport=httpx.MockTransport(handler))
        response = client.send(message)
        client.close()

        self.assertEqual(response, {"dev": {"status_code": 204}, "user": {"status_code": 204}})
        self.assertEqual({request.url.path for request in seen}, {"/api/webhooks/dev/token", "/api/webhooks/user/token"})

    def test_user_discord_rca_summary_uses_confidence_bands_without_technical_values(self):
        descriptions = {}

        def handler(request: httpx.Request) -> httpx.Response:
            descriptions[request.url.path] = json.loads(request.content)["embeds"][0]["description"]
            return httpx.Response(204)

        cfg = fixed_settings(notification_provider="discord", notification_user_webhook_url="https://discord.com/api/webhooks/user/token")
        cases = (
            (0.29, "cpu", "low confidence", "I have not found"),
            (0.35, "cpu, memory", "fairly reliable", "Other possible root causes: cpu, memory"),
            (0.5, "cpu, memory", "very high confidence", None),
        )
        for score, metrics, expected, alternatives in cases:
            message = NotificationMessage(
                incident_id=f"inc-{score}", severity="SEV2", state="open", title="RCA root cause: cart",
                summary=f"Root: cart\nDetected: rca_root_cause\nMetric: {metrics}\nRCA score: {score}\nValue: 1\nThreshold: 0.24\nEvidence:\n- trace_failure operation=POST /cart\n- evidence_strength=1.000\n- graph_score=0.900\nAction: inspect\nRunbook: RB-SERVICE-RESOURCE",
                flow="checkout", service="cart", likely_dependency="unknown", runbook_id="RB-SERVICE-RESOURCE",
            )
            NotificationClient(cfg, transport=httpx.MockTransport(handler)).send(message)
            description = descriptions["/api/webhooks/user/token"]
            self.assertIn(expected, description)
            self.assertIn(f"Metrics: {metrics}.", description)
            self.assertIn("Evidence:\n- trace_failure operation=POST /cart", description)
            self.assertNotIn("score", description.lower())
            self.assertNotIn("Value", description)
            self.assertNotIn("Threshold", description)
            self.assertNotIn("evidence_strength", description)
            if alternatives:
                self.assertIn(alternatives, description)
            else:
                self.assertNotIn("Other possible root causes", description)

    def test_notification_client_hides_unknown_discord_dependency(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        message = NotificationMessage(
            incident_id="inc-discord-2",
            severity="SEV1",
            state="open",
            title="edge incident",
            summary="summary",
            flow="edge",
            service="frontend-proxy",
            likely_dependency="unknown",
            runbook_id="RB-SERVICE-LATENCY",
        )

        NotificationClient(
            settings().model_copy(update={"notification_provider": "discord", "notification_webhook_url": "https://discord.com/api/webhooks/123/secret-token"}),
            transport=httpx.MockTransport(handler),
        ).send(message)

        fields = {field["name"]: field["value"] for field in json.loads(seen[0].content)["embeds"][0]["fields"]}
        self.assertNotIn("Likely dependency", fields)
        self.assertEqual(fields["Runbook"], "RB-SERVICE-LATENCY")

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
        response = NotificationClient(
            fixed_settings(notification_webhook_url="https://notify.example/"),
            transport=httpx.MockTransport(handler),
        ).send(message)

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
