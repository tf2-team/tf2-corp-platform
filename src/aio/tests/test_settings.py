#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import tempfile
import json
import unittest
from pathlib import Path

from aiops.api.app import create_app, run_static_pipeline
from aiops.config import Settings, build_detectors, load_hyperparameters, load_prometheus_query_registry, load_runtime_config
from aiops.schemas import Observation, PipelineRunRequest, SignalQuality


class SettingsTest(unittest.TestCase):
    def test_example_loads_local_integration_defaults(self):
        settings = Settings(_env_file=".env.example")

        self.assertEqual(settings.prometheus_base_url, "http://localhost:9090")
        self.assertEqual(settings.jaeger_base_url, "http://localhost:16686/jaeger/ui")
        self.assertFalse(settings.opensearch_verify_tls)
        self.assertEqual(settings.notification_provider, "auto")
        self.assertEqual(settings.runtime_config_path, Path("config/runtime.json"))

    def test_settings_load_from_env_file_and_drive_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            runtime_config_path = Path(directory) / "runtime.json"
            hyperparameters_path = Path(directory) / "hyperparameters.json"
            runtime_config = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
            runtime_config_path.write_text(json.dumps(runtime_config), encoding="utf-8")
            hyperparameters = json.loads(Path("config/hyperparameters.json").read_text(encoding="utf-8"))
            hyperparameters["detectors"]["thresholds"]["ops01_checkout_slo"] = 0.5
            hyperparameters_path.write_text(json.dumps(hyperparameters), encoding="utf-8")
            env_file.write_text(
                "\n".join(
                    [
                        "AIOPS_POLICY_MODE=observe",
                        f"AIOPS_STATE_STORE_PATH={Path(directory) / 'aiops.sqlite3'}",
                        f"AIOPS_RUNTIME_CONFIG_PATH={runtime_config_path}",
                        f"AIOPS_HYPERPARAMETERS_PATH={hyperparameters_path}",
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

    def test_hyperparameters_load_from_config_file(self):
        config = load_hyperparameters(Path("config/hyperparameters.json"))

        self.assertEqual(config["rca"]["top_k"], 5)
        self.assertEqual(config["rca"]["ewma_alpha"], 0.1)
        self.assertEqual(config["rca"]["ewma_z_threshold"], 4.0)
        self.assertEqual(config["rca"]["isolation_score_threshold"], 5.0)
        self.assertEqual(config["rca"]["anomaly"]["algorithm_weights"], {"robust_drift": 0.8, "ewma_stl": 0.8, "isolation_forest": 0.2})
        self.assertEqual(config["rca"]["anomaly"]["weighted_score_threshold"], 1.0)
        self.assertEqual(config["rca"]["anomaly"]["single_algorithm_min_normalized_score"], 2.0)
        self.assertEqual(config["rca"]["anomaly"]["robust_drift_threshold"], 4.0)
        self.assertEqual(config["rca"]["anomaly"]["robust_drift_min_baseline_points"], 30)
        self.assertEqual(config["rca"]["anomaly"]["detection_window_seconds"], 900)
        self.assertEqual(config["rca"]["anomaly"]["evidence_window_seconds"], 900)
        self.assertEqual(config["rca"]["anomaly"]["no_evidence_multiplier"], 0.5)
        self.assertEqual(config["rca"]["anomaly"]["single_evidence_bonus"], 0.15)
        self.assertEqual(config["rca"]["anomaly"]["dual_evidence_bonus"], 0.3)
        self.assertEqual(config["rca"]["anomaly"]["min_tail_anomaly_buckets"]["latency"], 3)
        self.assertEqual(config["rca"]["anomaly"]["min_tail_anomaly_buckets"]["cpu"], 3)
        self.assertEqual(config["rca"]["anomaly"]["min_relative_change_ratio"]["cpu"], 0.3)
        self.assertEqual(config["rca"]["anomaly"]["min_absolute_change"]["cpu"], 10.0)
        self.assertEqual(config["rca"]["anomaly"]["min_absolute_change"]["error"], 0.005)
        self.assertEqual(config["rca"]["anomaly"]["min_tail_anomaly_buckets"]["socket_io"], 3)
        self.assertEqual(config["rca"]["anomaly"]["min_relative_change_ratio"]["socket_io"], 0.5)
        self.assertEqual(config["rca"]["anomaly"]["min_absolute_change"]["socket_io"], 1048576.0)
        self.assertEqual(config["rca"]["anomaly"]["correlation_lag_buckets"], {"cpu": 1, "socket_io": 1, "memory": 4})
        self.assertEqual(config["rca"]["min_points"], 30)
        self.assertEqual(config["rca"]["anomaly"]["log_correlation_window_seconds"], 120)
        self.assertEqual(config["rca"]["anomaly"]["log_history_buckets"], 45)
        self.assertEqual(config["rca"]["anomaly"]["log_min_nonzero_buckets"], 3)
        self.assertEqual(config["rca"]["graph"]["damping"], 0.85)
        self.assertEqual(config["rca"]["graph"]["pagerank_weight"], 0.7)
        self.assertEqual(config["rca"]["graph"]["timestamp_weight"], 0.3)
        self.assertEqual(config["correlation"]["suppress_window_seconds"], 300)
        self.assertEqual(config["incident"]["count_reset_seconds"], 300)
        self.assertEqual(config["incident"]["notification_cooldown_seconds"], 300)
        self.assertEqual(config["incident"]["rca_dedup_seconds"], 300)
        self.assertEqual(config["incident"]["slo_dedup_seconds"], 300)
        self.assertNotIn("direct_slo_suppress_seconds", config["incident"])
        self.assertEqual(
            config["detectors"]["latency_slo_overrides"],
            {
                "frontend": 1,
                "frontend-proxy": 1.5,
                "checkout": 2,
                "payment": 1.5,
                "cart": 1,
                "currency": 0.3,
                "product-catalog": 1,
                "product-reviews": 1.2,
                "recommendation": 1.0,
                "ad": 1.0,
                "shipping": 1.0,
                "email": 1.0,
                "quote": 1.0,
                "fraud-detection": 1.0,
            },
        )
        self.assertEqual(config["correlation"]["suppress_min_root_score"], 0.8)
        self.assertEqual(config["correlation"]["topology_max_hops"], 1)
        self.assertEqual(
            config["rca"]["combined"],
            {
                "rrf_k": 20,
                "drift_min_points": 30,
                "drift_score_threshold": 4.0,
                "detection_window_seconds": 900,
                "canonical_service_suffixes": [],
                "metric_aliases": {},
                "ranker_weights": {"graph": 0.3, "earliest_drift": 0.5, "correlation": 0.1},
            },
        )
        self.assertEqual(config["remediation"]["similarity_weights"]["service"], 0.35)
        self.assertEqual(config["remediation"]["similarity_weights"]["trace"], 0.2)
        self.assertEqual(config["no_data"]["missing_confidence"], 1.0)
        self.assertNotIn("ops01_checkout_slo", config["detectors"]["thresholds"])
        profile = load_prometheus_query_registry(Path("config/prometheus_queries.json")).collection_profiles["one_second"]
        self.assertEqual(profile.step_seconds, 1)
        self.assertEqual(profile.lookback_seconds, 3600)
        self.assertGreaterEqual(
            profile.lookback_seconds // profile.detector_bucket_seconds + 1,
            config["rca"]["min_points"],
        )

    def test_build_detectors_gets_no_data_confidence_from_hyperparameters(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        detectors = build_detectors(
            runtime_config,
            None,
            no_data_hyperparameters={"missing_confidence": 0.42, "unknown_confidence": 0.24},
            detector_hyperparameters=load_hyperparameters(Path("config/hyperparameters.json"))["detectors"],
        )
        no_data = next(item for item in detectors if item.detector_id == "ops02_monitoring_loss")

        self.assertEqual(no_data.missing_confidence, 0.42)
        self.assertEqual(no_data.unknown_confidence, 0.24)

    def test_qualification_dev_env_reaches_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "\n".join(
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
                            signal_id="checkout_p95_latency_5m",
                            value=16.0,
                            unit="count",
                            window="5m",
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
                            value=7.0,
                            unit="percent",
                            window="1d",
                            quality=SignalQuality.UNQUALIFIED,
                            labels={"service_name": "checkout"},
                        )
                    ]
                ),
                settings=settings,
            )

        self.assertEqual(result.features[0].value, 0.07)
        self.assertEqual(result.features[0].unit, "ratio")
        self.assertEqual(result.features[0].window, "24h")
        self.assertEqual(result.features[0].labels["service"], "checkout")
        self.assertEqual(result.candidates, [])

    def test_fastapi_routes_come_from_settings(self):
        settings = Settings(api_health_live_path="/livez", api_pipeline_run_path="/run-now")
        paths = {route.path for route in create_app(settings).routes}

        self.assertIn("/livez", paths)
        self.assertIn("/run-now", paths)


if __name__ == "__main__":
    unittest.main()
