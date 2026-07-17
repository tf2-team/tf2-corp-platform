import unittest
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.api import create_app
from aiops.api.app import handle_grafana_webhook, run_static_pipeline
from aiops.config import Settings
from aiops.models import Observation as LegacyObservation
from aiops.schemas import GrafanaWebhookEvent, Observation, PipelineRunRequest, SignalQuality
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parent.parent
TEST_ENV_FILES = (ROOT / ".env", ROOT / ".env.live")


def settings() -> Settings:
    return Settings(_env_file=TEST_ENV_FILES)


def grafana_event() -> GrafanaWebhookEvent:
    return GrafanaWebhookEvent(
        receiver="aiops",
        status="firing",
        alerts=[
            {
                "status": "firing",
                "labels": {"alertname": "CheckoutSLOBreach", "severity": "SEV1"},
                "startsAt": "2026-07-14T00:00:00Z",
            }
        ],
    )


class SchemaPackageTest(unittest.TestCase):
    def test_schemas_are_shared_and_legacy_import_still_points_there(self):
        self.assertIs(LegacyObservation, Observation)
        observation = Observation(signal_id="checkout", value="1.2", unit="ratio", window="5m", quality="verified")

        self.assertEqual(observation.value, 1.2)
        self.assertEqual(observation.quality, SignalQuality.VERIFIED)


class FastApiAppTest(unittest.TestCase):
    def test_pipeline_endpoint_returns_pydantic_result(self):
        with TemporaryDirectory() as tmp:
            app_settings = settings().model_copy(update={"state_store_path": Path(tmp) / "aiops.sqlite3"})
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
                settings=app_settings,
            )

        self.assertEqual(result.incidents[0].flow, "checkout")
        self.assertEqual(result.policy_decisions[0].result, "dry-run-recorded")

    def test_fastapi_app_exposes_expected_routes(self):
        paths = {route.path for route in create_app(settings()).routes}

        self.assertIn("/health/live", paths)
        self.assertIn("/api/v1/pipeline/run", paths)
        self.assertIn("/api/v1/incidents", paths)
        self.assertIn("/api/v1/events/grafana", paths)

    def test_grafana_webhook_normalizes_event(self):
        cfg = settings()
        response = handle_grafana_webhook(
            grafana_event(),
            x_aiops_grafana_secret=cfg.grafana_webhook_secret,
            settings=cfg,
        )

        self.assertEqual(response.source, "grafana")
        self.assertEqual(response.status, "firing")
        self.assertEqual(response.labels["alertname"], "CheckoutSLOBreach")
        self.assertEqual(response.schema_version, "1.0")

    def test_grafana_webhook_rejects_invalid_secret(self):
        cfg = settings()
        with self.assertRaises(HTTPException) as caught:
            handle_grafana_webhook(
                grafana_event(),
                x_aiops_grafana_secret="wrong-secret",
                settings=cfg,
            )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertFalse(cfg.grafana_webhook_secret in str(caught.exception.detail))


if __name__ == "__main__":
    unittest.main()
