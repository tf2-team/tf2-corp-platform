#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json
import re
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from aiops.config import build_detectors, load_hyperparameters, load_prometheus_query_registry, load_runtime_config
from aiops.config import Settings
from aiops.schemas import RuntimeConfig


class RuntimeConfigTest(unittest.TestCase):
    def test_loads_runtime_json_and_builds_detectors(self):
        config = load_runtime_config(Path("config/runtime.json"))
        hyperparameters = load_hyperparameters(Settings().hyperparameters_path)
        detectors = build_detectors(config, Settings(), hyperparameters["no_data"], hyperparameters["detectors"])

        self.assertEqual(config.topology.services[0].name, "checkout")
        self.assertEqual(next(signal for signal in config.signals if signal.id == "checkout_bad_ratio_24h").feature_role, "official_slo")
        self.assertEqual(next(signal for signal in config.signals if signal.id == "checkout_payment_error_rate_5m").feature_role, "dependency_signal")
        self.assertEqual([detector.__class__.__name__ for detector in detectors], ["ThresholdDetector", "NoDataDetector", "DependencyDetector"])
        self.assertEqual([detector.detector_id for detector in detectors], ["ops01_checkout_slo", "ops02_monitoring_loss", "ops03_checkout_payment_dependency"])

    def test_each_service_error_rate_signal_has_auto_detector(self):
        config = load_runtime_config(Path("config/runtime.json"))
        signal_ids = {signal.id for signal in config.signals if signal.query_id.endswith(".error_rate_5m")}
        auto_detectors = [detector for detector in config.detectors if detector.id.startswith("auto_")]
        detector_signal_ids = {detector.signal_id for detector in auto_detectors}

        self.assertEqual(detector_signal_ids, signal_ids)
        self.assertTrue(all(not detector.enabled for detector in auto_detectors))

    def test_prometheus_services_expand_generated_metrics(self):
        raw = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        config = load_runtime_config(Path("config/runtime.json"))

        self.assertNotIn("prometheus_queries", raw)
        self.assertNotIn("prometheus_services", raw)
        self.assertEqual(raw["signals"], [])
        self.assertIn("checkout.p95_latency_5m", config.prometheus_queries)
        self.assertIn("checkout.p99_latency_5m", config.prometheus_queries)
        self.assertIn("payment.p95_latency_5m", config.prometheus_queries)
        self.assertIn("payment.p99_latency_5m", config.prometheus_queries)
        self.assertIn("payment.error_rate_5m", config.prometheus_queries)
        self.assertIn("payment.request_rate_5m", config.prometheus_queries)
        self.assertIn("payment.cpu_millicores", config.prometheus_queries)
        self.assertIn("payment.memory_usage_bytes", config.prometheus_queries)
        self.assertIn("payment.disk_io_bytes_per_second", config.prometheus_queries)
        self.assertIn("payment.socket_io_bytes_per_second", config.prometheus_queries)
        self.assertIn("payment.workload_ready_pods", config.prometheus_queries)
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.error_rate_5m"])
        self.assertIn('service_name="payment"', config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("rpc_server_duration_milliseconds_bucket", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("rpc_server_duration_milliseconds_count", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("or on() vector(0)", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn("or on() vector(0)", config.prometheus_queries["checkout.p95_latency_5m"])
        self.assertTrue(all("or on() vector(0)" in query for query in config.prometheus_queries.values()))
        self.assertNotIn("traces_span_metrics_calls_total", config.prometheus_queries["payment.p95_latency_5m"])
        self.assertIn('container="payment"', config.prometheus_queries["payment.memory_usage_bytes"])
        self.assertNotIn("target_info", config.prometheus_queries["payment.memory_usage_bytes"])
        self.assertNotIn("system_memory_usage_bytes", config.prometheus_queries["payment.memory_usage_bytes"])
        self.assertIn("http_server_request_duration_seconds_count", config.prometheus_queries["cart.error_rate_5m"])
        self.assertIn("rpc_client_duration_milliseconds_count", config.prometheus_queries["checkout.payment_error_rate.5m"])
        self.assertIn("0.000000001", config.prometheus_queries["checkout.payment_error_rate.5m"])
        self.assertTrue(
            {
                "payment_p95_latency_5m",
                "payment_error_rate_5m",
                "payment_request_rate_5m",
                "payment_cpu_millicores",
                "payment_memory_usage_bytes",
                "payment_disk_io_bytes_per_second",
                "payment_socket_io_bytes_per_second",
                "payment_workload_ready_pods",
            }.issubset({signal.id for signal in config.signals})
        )
        self.assertEqual([signal.id for signal in config.signals].count("product_catalog_cpu_millicores"), 1)

    def test_no_data_detector_covers_required_prometheus_signals(self):
        config = load_runtime_config(Path("config/runtime.json"))
        prometheus_signal_ids = {
            signal.id
            for signal in config.signals
            if signal.source == "prometheus" and config.prometheus_query_specs[signal.query_id].required_for_monitoring
        }
        no_data_signal_ids = {
            signal_id
            for detector in config.detectors
            if detector.type == "no-data"
            for signal_id in detector.signal_ids
        }

        self.assertEqual(no_data_signal_ids, prometheus_signal_ids)

    def test_registry_owns_one_second_collection_contract(self):
        registry = load_prometheus_query_registry(Path("config/prometheus_queries.json"))
        profile = registry.collection_profiles["one_second"]

        self.assertEqual(profile.step_seconds, 1)
        self.assertEqual(profile.required_source_resolution_seconds, 1)
        self.assertEqual(profile.detector_bucket_seconds, 30)
        self.assertEqual(profile.lookback_seconds, 3600)
        self.assertEqual(profile.lookback_seconds // profile.detector_bucket_seconds, 120)
        self.assertEqual(registry.result_defaults.on_empty, "zero")

    def test_template_can_override_default_empty_result_policy(self):
        raw = json.loads(Path("config/prometheus_queries.json").read_text(encoding="utf-8"))
        raw["templates"]["red.grpc.p95_latency"]["result"] = {"on_empty": "missing"}

        with tempfile.TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "prometheus_queries.json"
            registry_path.write_text(json.dumps(raw), encoding="utf-8")
            config = load_runtime_config(Path("config/runtime.json"), registry_path)

        self.assertNotIn("vector(0)", config.prometheus_queries["checkout.p95_latency_5m"])
        self.assertIn("vector(0)", config.prometheus_queries["checkout.error_rate_5m"])

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
