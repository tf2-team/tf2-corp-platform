import tempfile
import json
import unittest
from pathlib import Path

from aiops.api.app import create_app, run_static_pipeline
from aiops.config import Settings
from aiops.schemas import Observation, PipelineRunRequest, SignalQuality


class SettingsTest(unittest.TestCase):
    def test_live_example_overrides_tracked_defaults(self):
        settings = Settings(_env_file=(".env", ".env.live.example"))

        self.assertEqual(settings.prometheus_base_url, "http://localhost:9090")
        self.assertEqual(settings.jaeger_base_url, "http://localhost:16686/jaeger/ui")
        self.assertFalse(settings.opensearch_verify_tls)
        self.assertEqual(settings.notification_provider, "auto")
        self.assertEqual(settings.runtime_config_path, Path("config/runtime.json"))

    def test_settings_load_from_env_file_and_drive_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            runtime_config_path = Path(directory) / "runtime.json"
            runtime_config = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
            runtime_config["detector_thresholds"]["ops01_checkout_slo"] = 0.5
            runtime_config_path.write_text(json.dumps(runtime_config), encoding="utf-8")
            env_file.write_text(
                Path(".env").read_text(encoding="utf-8")
                + "\n"
                + "\n".join(
                    [
                        "AIOPS_CHECKOUT_SLO_RUNBOOK_ID=RB-TEST",
                        "AIOPS_POLICY_MODE=observe",
                        f"AIOPS_STATE_STORE_PATH={Path(directory) / 'aiops.sqlite3'}",
                        f"AIOPS_RUNTIME_CONFIG_PATH={runtime_config_path}",
                    ]
                ),
                encoding="utf-8",
            )
            settings = Settings(_env_file=env_file)

            result = run_static_pipeline(
                PipelineRunRequest(
                    observations=[
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=0.2,
                            unit="ratio",
                            window="24h",
                            quality=SignalQuality.VERIFIED,
                        )
                    ]
                ),
                settings=settings,
            )

        self.assertEqual(result.incidents, [])

    def test_qualification_dev_env_reaches_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                Path(".env").read_text(encoding="utf-8")
                + "\n"
                + "\n".join(
                    [
                        "AIOPS_QUALIFICATION_GATE_DEV=true",
                        f"AIOPS_STATE_STORE_PATH={Path(directory) / 'aiops.sqlite3'}",
                    ]
                ),
                encoding="utf-8",
            )
            settings = Settings(_env_file=env_file)

            result = run_static_pipeline(
                PipelineRunRequest(
                    observations=[
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=0.2,
                            unit="count",
                            window="24h",
                            quality=SignalQuality.VERIFIED,
                        )
                    ]
                ),
                settings=settings,
            )

        self.assertEqual(result.incidents[0].flow, "checkout")

    def test_pipeline_normalizes_before_strict_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(state_store_path=Path(directory) / "aiops.sqlite3")

            result = run_static_pipeline(
                PipelineRunRequest(
                    observations=[
                        Observation(
                            signal_id="checkout_bad_ratio_24h",
                            value=2.0,
                            unit="percent",
                            window="1d",
                            quality=SignalQuality.UNQUALIFIED,
                            labels={"service_name": "checkout"},
                        )
                    ]
                ),
                settings=settings,
            )

        self.assertEqual(result.features[0].value, 0.02)
        self.assertEqual(result.features[0].unit, "ratio")
        self.assertEqual(result.features[0].window, "24h")
        self.assertEqual(result.features[0].labels["service"], "checkout")
        self.assertEqual(result.candidates[0].detector_id, "ops01_checkout_slo")

    def test_fastapi_routes_come_from_settings(self):
        settings = Settings(api_health_live_path="/livez", api_pipeline_run_path="/run-now")
        paths = {route.path for route in create_app(settings).routes}

        self.assertIn("/livez", paths)
        self.assertIn("/run-now", paths)


if __name__ == "__main__":
    unittest.main()
