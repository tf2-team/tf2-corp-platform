import json
import re
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from aiops.config import build_detectors, load_hyperparameters, load_runtime_config
from aiops.config import Settings
from aiops.schemas import RuntimeConfig


class RuntimeConfigTest(unittest.TestCase):
    def test_loads_runtime_json_and_builds_detectors(self):
        config = load_runtime_config(Path("config/runtime.json"))
        hyperparameters = load_hyperparameters(Settings().hyperparameters_path)
        detectors = build_detectors(config, Settings(), hyperparameters["no_data"], hyperparameters["detectors"])

        self.assertEqual(config.topology.services[0].name, "checkout")
        self.assertEqual(config.signals[0].feature_role, "official_slo")
        self.assertEqual(config.signals[1].feature_role, "diagnostic")
        self.assertEqual([detector.__class__.__name__ for detector in detectors[:3]], ["ThresholdDetector", "NoDataDetector", "DependencyDetector"])
        self.assertTrue(any(detector.detector_id == "ops04_checkout_latency_p95" for detector in detectors))
        self.assertTrue(any(detector.detector_id == "ops06_product_catalog_cpu" for detector in detectors))

    def test_each_service_error_rate_signal_has_auto_detector(self):
        config = load_runtime_config(Path("config/runtime.json"))
        signal_ids = {signal.id for signal in config.signals if signal.query_id.endswith(".error_rate.5m")}
        detector_signal_ids = {detector.signal_id for detector in config.detectors if detector.id.startswith("auto_")}

        self.assertEqual(detector_signal_ids, signal_ids)

    def test_prometheus_services_expand_generated_metrics(self):
        raw = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        config = load_runtime_config(Path("config/runtime.json"))

        self.assertNotIn("payment.error_rate.5m", raw["prometheus_queries"])
        self.assertIn("payment", raw["prometheus_services"])
        self.assertIn("payment.error_rate.5m", config.prometheus_queries)
        self.assertIn("payment.cpu_millicores", config.prometheus_queries)
        self.assertIn("payment.memory_usage_bytes", config.prometheus_queries)
        self.assertIn("payment.disk_io_bytes_per_second", config.prometheus_queries)
        self.assertIn("payment.socket_io_bytes_per_second", config.prometheus_queries)
        self.assertIn("payment.workload_ready_pods", config.prometheus_queries)
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.error_rate.5m"])
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.memory_usage_bytes"])
        self.assertNotIn("target_info", config.prometheus_queries["payment.memory_usage_bytes"])
        self.assertIn("traces_span_metrics_calls_total", config.prometheus_queries["cart.error_rate.5m"])
        self.assertTrue(
            {
                "payment_error_rate_5m",
                "payment_cpu_millicores",
                "payment_memory_usage_bytes",
                "payment_disk_io_bytes_per_second",
                "payment_socket_io_bytes_per_second",
                "payment_workload_ready_pods",
            }.issubset({signal.id for signal in config.signals})
        )
        self.assertEqual([signal.id for signal in config.signals].count("product_catalog_cpu_millicores"), 1)

    def test_no_data_detector_covers_all_prometheus_signals(self):
        config = load_runtime_config(Path("config/runtime.json"))
        prometheus_signal_ids = {signal.id for signal in config.signals if signal.source == "prometheus"}
        no_data_signal_ids = {
            signal_id
            for detector in config.detectors
            if detector.type == "no-data"
            for signal_id in detector.signal_ids
        }

        self.assertEqual(no_data_signal_ids, prometheus_signal_ids)

    def test_enabled_detector_runbooks_have_canonical_files(self):
        config = load_runtime_config(Path("config/runtime.json"))
        runbook_ids = {detector.runbook_id for detector in config.detectors if detector.enabled}

        self.assertEqual({path.stem for path in Path("runbooks").glob("*.md")}, runbook_ids)

    def test_rejects_detector_with_unknown_signal(self):
        config = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        config["detectors"][0]["signal_id"] = "missing_signal"

        with self.assertRaises(ValidationError):
            RuntimeConfig.model_validate(config)

    def test_api_markdown_json_schemas_are_parseable(self):
        text = Path("docs/các API cần kết nối.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json[^\n]*\n(.*?)\n```", text, re.S)

        self.assertEqual(len(blocks), 18)
        for block in blocks:
            schema = json.loads(block)
            self.assertIn("$schema", schema)
            self.assertIn("$id", schema)
            self.assertEqual(schema.get("type"), "object")
            self.assertIsInstance(schema.get("required", []), list)


if __name__ == "__main__":
    unittest.main()
