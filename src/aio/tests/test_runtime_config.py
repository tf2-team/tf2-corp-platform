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
        signals = {signal.id: signal for signal in config.signals}
        self.assertEqual(signals["checkout_bad_ratio_24h"].feature_role, "official_slo")
        self.assertEqual(signals["prometheus_collection_health"].feature_role, "diagnostic")
        self.assertEqual(len(detectors), 11)
        self.assertEqual(
            [detector.detector_id for detector in detectors],
            [
                "ops01_checkout_slo",
                "ops02_monitoring_loss",
                "ops03_checkout_payment_dependency",
                "ops04_checkout_latency_p95",
                "ops06_product_catalog_cpu",
                "auto_checkout_error_rate",
                "auto_payment_error_rate",
                "auto_product_catalog_error_rate",
                "auto_cart_error_rate",
                "ops07_checkout_fast_burn",
                "ops08_checkout_slow_burn",
            ],
        )

    def test_each_service_error_rate_signal_has_auto_detector(self):
        config = load_runtime_config(Path("config/runtime.json"))
        signal_ids = {signal.id for signal in config.signals if signal.query_id.endswith(".error_rate_5m")}
        auto_detectors = [detector for detector in config.detectors if detector.id.startswith("auto_")]
        detector_signal_ids = {detector.signal_id for detector in auto_detectors}

        self.assertEqual(detector_signal_ids, signal_ids)
        self.assertTrue(all(detector.enabled for detector in auto_detectors))

    def test_prometheus_services_expand_generated_metrics(self):
        raw = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        config = load_runtime_config(Path("config/runtime.json"))

        self.assertNotIn("payment.error_rate_5m", raw["prometheus_queries"])
        self.assertIn("payment", raw["prometheus_services"])
        self.assertIn("payment.p95_latency_5m", config.prometheus_queries)
        self.assertIn("payment.error_rate_5m", config.prometheus_queries)
        self.assertIn("payment.request_rate_5m", config.prometheus_queries)
        self.assertIn("payment.cpu_millicores", config.prometheus_queries)
        self.assertNotIn("payment.memory_usage_bytes", config.prometheus_queries)
        self.assertNotIn("payment.disk_io_bytes_per_second", config.prometheus_queries)
        self.assertNotIn("payment.socket_io_bytes_per_second", config.prometheus_queries)
        self.assertNotIn("payment.workload_ready_pods", config.prometheus_queries)
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.error_rate_5m"])
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("traces_span_metrics_duration_milliseconds_bucket", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("traces_span_metrics_duration_milliseconds_count", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertNotIn("vector(0)", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertNotIn("vector(0)", config.prometheus_queries["checkout.p95_latency.5m"])
        self.assertTrue(all("vector(0)" not in config.prometheus_queries[signal.query_id] for signal in config.signals if signal.source == "prometheus" and signal.feature_role == "anomaly_input"))
        self.assertNotIn("traces_span_metrics_calls_total", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("traces_span_metrics_calls_total", config.prometheus_queries["cart.error_rate_5m"])
        self.assertIn("* 1000", config.prometheus_queries["product-catalog.cpu_millicores"])
        self.assertTrue(
            {
                "payment_p95_latency_5m",
                "payment_error_rate_5m",
                "payment_request_rate_5m",
                "payment_cpu_millicores",
            }.issubset({signal.id for signal in config.signals})
        )
        self.assertEqual([signal.id for signal in config.signals].count("product_catalog_cpu_millicores"), 1)

    def test_no_data_detector_uses_dedicated_collection_health_signal(self):
        config = load_runtime_config(Path("config/runtime.json"))
        prometheus_signal_ids = {signal.id for signal in config.signals if signal.source == "prometheus"}
        no_data_signal_ids = {
            signal_id
            for detector in config.detectors
            if detector.type == "no-data"
            for signal_id in detector.signal_ids
        }

        self.assertEqual(no_data_signal_ids, {"prometheus_collection_health"})
        self.assertTrue(no_data_signal_ids.issubset(prometheus_signal_ids))

    def test_runtime_query_budget_is_bounded_by_configured_scope(self):
        config = load_runtime_config(Path("config/runtime.json"))
        instant_queries = len([signal for signal in config.signals if signal.source == "prometheus"])
        range_queries = len(
            [signal for signal in config.signals if signal.source == "prometheus" and signal.feature_role == "anomaly_input"]
        )

        self.assertEqual(instant_queries, 21)
        self.assertEqual(range_queries, 16)

    def test_service_promql_templates_are_loaded_from_runtime_config(self):
        raw = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        raw["prometheus_metric_templates"]["request_rate_5m"]["template"] = 'sum(up{job="$service"})'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            config = load_runtime_config(path)

        self.assertEqual(config.prometheus_queries["payment.request_rate_5m"], 'sum(up{job="payment"})')

    def test_enabled_detector_runbooks_have_canonical_files(self):
        config = load_runtime_config(Path("config/runtime.json"))
        runbook_ids = {detector.runbook_id for detector in config.detectors if detector.enabled}

        self.assertTrue(runbook_ids.issubset({path.stem for path in Path("runbooks").glob("*.md")}))

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
