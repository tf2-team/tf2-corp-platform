import unittest

from aiops.api import create_app
from aiops.api.app import handle_grafana_webhook
from aiops.models import Observation as LegacyObservation
from aiops.schemas import GrafanaWebhookEvent, Observation, SignalQuality


class SchemaPackageTest(unittest.TestCase):
    def test_schemas_are_shared_and_legacy_import_still_points_there(self):
        self.assertIs(LegacyObservation, Observation)
        observation = Observation(signal_id="checkout", value="1.2", unit="ratio", window="5m", quality="verified")

        self.assertEqual(observation.value, 1.2)
        self.assertEqual(observation.quality, SignalQuality.VERIFIED)


class FastApiAppTest(unittest.TestCase):
    def test_fastapi_app_exposes_expected_routes(self):
        paths = {route.path for route in create_app().routes}

        self.assertIn("/health/live", paths)
        self.assertIn("/api/v1/events/grafana", paths)
        self.assertNotIn("/api/v1/pipeline/run", paths)

    def test_grafana_webhook_normalizes_event(self):
        response = handle_grafana_webhook(
            GrafanaWebhookEvent(
                receiver="aiops",
                status="firing",
                alerts=[
                    {
                        "status": "firing",
                        "labels": {"alertname": "CheckoutSLOBreach", "severity": "SEV1"},
                        "startsAt": "2026-07-14T00:00:00Z",
                    }
                ],
            ),
            x_aiops_grafana_secret="CHANGE_ME_GRAFANA_WEBHOOK_SECRET",
        )

        self.assertEqual(response.source, "grafana")
        self.assertEqual(response.status, "firing")


if __name__ == "__main__":
    unittest.main()
