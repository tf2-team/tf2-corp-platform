import unittest

from aiops.api.app import create_app
from aiops.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_load_from_env_file(self):
        settings = Settings(_env_file=".env")

        self.assertEqual(settings.checkout_slo_threshold, 0.01)
        self.assertEqual(settings.checkout_slo_runbook_id, "RB-CHECKOUT-SLO")
        self.assertEqual(settings.policy_mode, "dry-run")

    def test_fastapi_routes_come_from_settings(self):
        settings = Settings(api_health_live_path="/livez")
        paths = {route.path for route in create_app(settings).routes}

        self.assertIn("/livez", paths)


if __name__ == "__main__":
    unittest.main()
