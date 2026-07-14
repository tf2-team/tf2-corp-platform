import tempfile
import unittest
from pathlib import Path

from aiops.api.app import create_app
from aiops.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_load_from_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                Path(".env").read_text(encoding="utf-8")
                + "\n"
                + "\n".join(
                    [
                        "AIOPS_CHECKOUT_SLO_THRESHOLD=0.5",
                        "AIOPS_CHECKOUT_SLO_RUNBOOK_ID=RB-TEST",
                        "AIOPS_POLICY_MODE=observe",
                        f"AIOPS_STATE_STORE_PATH={Path(directory) / 'aiops.sqlite3'}",
                    ]
                ),
                encoding="utf-8",
            )
            settings = Settings(_env_file=env_file)

        self.assertEqual(settings.checkout_slo_threshold, 0.5)
        self.assertEqual(settings.checkout_slo_runbook_id, "RB-TEST")
        self.assertEqual(settings.policy_mode, "observe")

    def test_fastapi_routes_come_from_settings(self):
        settings = Settings(api_health_live_path="/livez")
        paths = {route.path for route in create_app(settings).routes}

        self.assertIn("/livez", paths)


if __name__ == "__main__":
    unittest.main()
