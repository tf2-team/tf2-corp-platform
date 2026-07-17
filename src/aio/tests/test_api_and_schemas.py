import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.api import create_app
from aiops.api.app import build_enricher, handle_grafana_webhook, run_static_pipeline
from aiops.config import Settings, load_runtime_config
from aiops.models import Observation as LegacyObservation
from aiops.schemas import GrafanaWebhookEvent, Observation, PipelineRunRequest, SignalQuality


class SchemaPackageTest(unittest.TestCase):
    def test_schemas_are_shared_and_legacy_import_still_points_there(self):
        self.assertIs(LegacyObservation, Observation)
        observation = Observation(signal_id="checkout", value="1.2", unit="ratio", window="5m", quality="verified")

        self.assertEqual(observation.value, 1.2)
        self.assertEqual(observation.quality, SignalQuality.VERIFIED)


class FastApiAppTest(unittest.TestCase):
    def test_pipeline_endpoint_returns_pydantic_result(self):
        with TemporaryDirectory() as tmp:
            settings = Settings().model_copy(update={"state_store_path": Path(tmp) / "aiops.sqlite3"})
            result = run_static_pipeline(
                PipelineRunRequest(
                    observations=[
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=0.02,
                            unit="ratio",
                            window="24h",
                            quality=SignalQuality.VERIFIED,
                        )
                    ]
                ),
                settings=settings,
            )

        self.assertEqual(result.incidents[0].flow, "checkout")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")

    def test_fastapi_app_exposes_expected_routes(self):
        paths = {route.path for route in create_app().routes}

        self.assertIn("/health/live", paths)
        self.assertIn("/api/v1/pipeline/run", paths)
        self.assertIn("/api/v1/incidents", paths)
        self.assertIn("/api/v1/events/grafana", paths)

    def test_template_settings_do_not_enable_external_enrichment_clients(self):
        settings = Settings()
        enricher = build_enricher(settings, load_runtime_config(settings.runtime_config_path))

        self.assertIsNone(enricher.jaeger)
        self.assertIsNone(enricher.opensearch)
        self.assertIsNone(enricher.kubernetes)

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
        self.assertEqual(response.labels["alertname"], "CheckoutSLOBreach")
        self.assertEqual(response.schema_version, "1.0")


if __name__ == "__main__":
    unittest.main()
