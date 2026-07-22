#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import io
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.anomaly import V001AnomalyEngine, build_v001_anomaly_engine
from aiops.anomaly import v001 as anomaly_v001
from aiops.anomaly.v001 import EwmaStlDetector, LogTemplateMetricBuilder, ServiceIsolationForestDetector, _metric_group, _point_changed
from aiops.api.app import run_static_pipeline
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.pipeline.runtime import _log_final_root_cause_algorithm_scores
from aiops.rca.graph import GraphTraversalRca
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricPoint, MetricSeries, PipelineRunRequest, RcaResult, RootCauseCandidate, RuntimeConfig
from aiops.shared.series import prepare_detector_series


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


def minute_metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index * 60, value=value) for index, value in enumerate(values)],
    )


def rca_hyperparameters(**overrides):
    config = load_hyperparameters(Path("config/hyperparameters.json"))["rca"]
    return {**config, **overrides}


def anomaly_engine(**overrides) -> V001AnomalyEngine:
    config = rca_hyperparameters()
    min_points = overrides.pop("min_points", 8)
    anomaly = {
        **config["anomaly"],
        "robust_drift_min_baseline_points": min_points,
        "log_history_buckets": 8,
        "log_min_nonzero_buckets": 1,
    }
    config = {**config, "anomaly": anomaly, "min_points": min_points, **overrides}
    return build_v001_anomaly_engine(config)


def rca_engine(config: RuntimeConfig, **combined_overrides) -> V001RcaEngine:
    hyperparameters = rca_hyperparameters()
    combined = {
        **hyperparameters["combined"],
        "min_tail_anomaly_buckets": hyperparameters["anomaly"]["min_tail_anomaly_buckets"],
        "min_relative_change_ratio": hyperparameters["anomaly"]["min_relative_change_ratio"],
        "min_absolute_change": hyperparameters["anomaly"]["min_absolute_change"],
        **combined_overrides,
    }
    return V001RcaEngine(config, hyperparameters["graph"], combined)


def graph_rca(config: RuntimeConfig) -> GraphTraversalRca:
    return GraphTraversalRca(config, **rca_hyperparameters()["graph"])


class V001AnomalyRcaTest(unittest.TestCase):
    def test_cpu_millicores_metric_uses_cpu_thresholds(self):
        self.assertEqual(_metric_group("cpu_millicores"), "cpu")

    def test_cpu_millicores_ignores_small_low_baseline_change(self):
        self.assertFalse(_point_changed(8.75, 8.0, min_relative=0.3, min_absolute=1.0))
        self.assertFalse(_point_changed(8.25, 8.0, min_relative=0.3, min_absolute=1.0))
        self.assertTrue(_point_changed(11.0, 8.0, min_relative=0.3, min_absolute=1.0))

    def test_socket_io_metric_uses_socket_io_thresholds(self):
        self.assertEqual(_metric_group("socket_io_bytes_per_second"), "socket_io")

    def test_detector_bucket_aggregation_matches_metric_type(self):
        series = prepare_detector_series(
            [
                MetricSeries(
                    service="payment",
                    metric="error_rate_5m",
                    signal_id="payment_error_rate_5m",
                    step_seconds=1,
                    detector_bucket_seconds=60,
                    points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate([0.1, 0.9, 0.2])],
                ),
                MetricSeries(
                    service="payment",
                    metric="cpu_millicores",
                    signal_id="payment_cpu_millicores",
                    step_seconds=1,
                    detector_bucket_seconds=60,
                    points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate([10.0, 100.0, 20.0])],
                ),
            ]
        )

        self.assertEqual([item.points[0].value for item in series], [0.9, 130.0 / 3.0])

    def test_ewma_formula_does_not_emit_statsmodels_zero_sse_warning(self):
        detector = EwmaStlDetector(alpha=0.3, z_threshold=3.0, min_points=8, seasonal_period=1)

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            residuals = detector._residuals([1.0] * 8)

        self.assertEqual(len(residuals), 8)

    def test_logs_algorithm_scores_for_final_root_cause_only(self):
        result = RcaResult(root_causes=[RootCauseCandidate(service="checkout", score=1.0, root_cause_metrics=["latency"])])
        findings = [
            AnomalyFinding(algorithm="ewma_stl", service="checkout", metric="latency", signal_id="checkout_latency", score=4.0, timestamp=1),
            AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="latency", signal_id="checkout_latency", score=8.0, timestamp=1),
            AnomalyFinding(algorithm="ewma_stl", service="payment", metric="latency", signal_id="payment_latency", score=99.0, timestamp=1),
        ]

        with self.assertLogs("aiops.pipeline.runtime", level="INFO") as logs:
            _log_final_root_cause_algorithm_scores(result, findings)

        output = "\n".join(logs.output)
        self.assertIn("AIOPS_RCA_FINAL_ALGORITHM_SCORES", output)
        self.assertIn("service=checkout", output)
        self.assertIn("ewma_stl=4.000", output)
        self.assertIn("isolation_forest=8.000", output)
        self.assertNotIn("99.000", output)

    def test_v001_detects_hidden_error_signal_that_ramps_up_slowly(self):
        findings = anomaly_engine().evaluate(
            [
                metric(
                    "payment",
                    "error_ratio_5m",
                    [0.001, 0.001, 0.001, 0.001, 0.001, 0.002, 0.003, 0.005, 0.008, 0.013, 0.021, 0.034],
                )
            ]
        )

        self.assertEqual([(finding.algorithm, finding.service, finding.metric) for finding in findings], [("weighted_sum", "payment", "error_ratio_5m")])
        self.assertGreaterEqual(findings[0].score, rca_hyperparameters()["anomaly"]["weighted_score_threshold"])

    def test_v001_does_not_flag_low_noise_as_hidden_error_signal(self):
        findings = anomaly_engine().evaluate(
            [
                metric(
                    "payment",
                    "error_ratio_5m",
                    [0.001, 0.0012, 0.0009, 0.0011, 0.001, 0.0012, 0.0008, 0.0011, 0.001, 0.0012, 0.0009, 0.001],
                )
            ]
        )

        self.assertEqual(findings, [])

    def test_v001_only_scores_detection_tail(self):
        engine = anomaly_engine(min_points=30)
        old_spike = [1.0] * 45
        old_spike[10] = 200.0
        tail_spike = [1.0] * 45
        tail_spike[35] = 200.0

        self.assertEqual(engine.evaluate([minute_metric("payment", "error_ratio_5m", old_spike)]), [])
        self.assertEqual([(finding.service, finding.metric) for finding in engine.evaluate([minute_metric("payment", "error_ratio_5m", tail_spike)])], [("payment", "error_ratio_5m")])

    def test_v001_drops_short_infra_spike_in_tail(self):
        findings = anomaly_engine().evaluate(
            [
                metric("payment", "cpu_millicores", [100, 100, 100, 100, 100, 100, 100, 100, 300, 100, 100]),
            ]
        )

        self.assertEqual(findings, [])

    def test_v001_keeps_sustained_infra_change_in_tail(self):
        findings = anomaly_engine().evaluate(
            [
                metric("payment", "cpu_millicores", [100, 100, 100, 100, 100, 100, 100, 100, 300, 300, 300]),
            ]
        )

        self.assertEqual([(finding.service, finding.metric) for finding in findings], [("payment", "cpu_millicores")])

    def test_v001_ignores_short_drift_that_recovered_before_latest_point(self):
        findings = anomaly_engine().evaluate(
            [
                metric("payment", "cpu", [1, 1, 1, 1, 1, 100, 100, 1, 1, 1]),
            ]
        )

        self.assertEqual(findings, [])

    def test_isolation_forest_normalizes_rows_before_scoring(self):
        detector = ServiceIsolationForestDetector(score_threshold=4.0, min_points=8)
        rows = detector._rows(
            [
                metric("checkout", "cpu", [10, 10, 10, 10, 10, 10, 10, 20]),
                metric("checkout", "memory", [10000, 10000, 10000, 10000, 10000, 10000, 10000, 20000]),
            ]
        )

        self.assertEqual(rows[-1], [20.0, 20000.0])
        self.assertEqual(detector._normalized_rows(rows)[-1], [1.0, 1.0])

    def test_isolation_forest_scores_tail_with_one_model_fit(self):
        detector = ServiceIsolationForestDetector(score_threshold=1.0, min_points=5)
        calls = []

        def scores(baseline_rows, scored_rows):
            calls.append((len(baseline_rows), len(scored_rows)))
            return [0.2] * len(scored_rows)

        detector._scores = scores

        findings = detector.evaluate(
            [
                metric("checkout", "cpu", [1, 1, 1, 1, 1, 10, 10, 10]),
                metric("checkout", "memory", [1, 1, 1, 1, 1, 10, 10, 10]),
            ]
        )

        self.assertEqual(calls, [(5, 3)])
        self.assertEqual(findings[0].algorithm, "isolation_forest")

    def test_anomaly_builder_requires_configured_log_hyperparameters(self):
        config = rca_hyperparameters()
        anomaly = dict(config["anomaly"])
        del anomaly["log_bucket_seconds"]

        with self.assertRaises(KeyError):
            build_v001_anomaly_engine({**config, "anomaly": anomaly})

    def test_anomaly_builder_requires_tail_significance_hyperparameters(self):
        config = rca_hyperparameters()
        anomaly = dict(config["anomaly"])
        del anomaly["min_tail_anomaly_buckets"]

        with self.assertRaises(KeyError):
            build_v001_anomaly_engine({**config, "anomaly": anomaly})

    def test_weighted_sum_ignores_weak_single_algorithm_without_corroboration(self):
        engine = anomaly_engine()

        findings = engine._weighted_sum(
            [AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=4.0, timestamp=1)]
        )

        self.assertEqual(findings, [])

    def test_weighted_sum_keeps_strong_single_algorithm_detection(self):
        engine = anomaly_engine()

        findings = engine._weighted_sum(
            [AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=10.0, timestamp=1)]
        )

        self.assertEqual([(finding.algorithm, finding.score) for finding in findings], [("weighted_sum", engine.weighted_score_threshold)])

    def test_weighted_sum_combines_normalized_algorithm_scores(self):
        engine = anomaly_engine()

        findings = engine._weighted_sum(
            [
                AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=99.0, timestamp=1),
                AnomalyFinding(algorithm="ewma_stl", service="checkout", metric="cpu", signal_id="checkout_cpu", score=99.0, timestamp=1),
            ]
        )

        weights = rca_hyperparameters()["anomaly"]["algorithm_weights"]
        self.assertEqual([(finding.algorithm, finding.score) for finding in findings], [("weighted_sum", weights["isolation_forest"] + weights["ewma_stl"])])

    def test_busy_cpu_without_failure_signal_is_suppressed(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.5, timestamp=7)
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "p95_latency_5m", [1, 1, 1, 1, 1, 1, 1, 1]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_cpu(findings, series), [])

    def test_busy_cpu_suppress_uses_finding_timestamp(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.5, timestamp=5)
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 100, 10, 10]),
            metric("checkout", "p95_latency_5m", [1, 1, 1, 1, 1, 1, 1, 1]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_cpu(findings, series), [])

    def test_traffic_driven_latency_and_infra_without_hard_failure_are_suppressed(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.5, timestamp=7),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="p95_latency_5m", signal_id="checkout_p95_latency_5m", score=0.5, timestamp=7),
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "cpu_millicores", [1, 1, 1, 1, 1, 1, 1, 10]),
            metric("checkout", "p95_latency_5m", [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_infra(findings, series), [])

    def test_coordinated_load_growth_is_filtered_before_anomaly_detection(self):
        engine = anomaly_engine()
        series = [
            minute_metric("checkout", "request_rate_5m", [10] * 30 + [30] * 15),
            minute_metric("checkout", "cpu_millicores", [100] * 30 + [300] * 15),
            minute_metric("checkout", "memory_usage_bytes", [100_000_000] * 30 + [150_000_000] * 15),
            minute_metric("checkout", "socket_io_bytes_per_second", [1_000_000] * 30 + [3_000_000] * 15),
            minute_metric("checkout", "p95_latency_5m", [0.05] * 30 + [0.10] * 15),
            minute_metric("checkout", "workload_ready_pods", [1] * 30 + [2] * 15),
            minute_metric("checkout", "error_rate_5m", [0] * 45),
        ]

        self.assertEqual(
            [item.metric for item in engine._filter_normal_traffic_growth(series)],
            ["error_rate_5m"],
        )
        series[-1] = minute_metric("checkout", "error_rate_5m", [0] * 44 + [0.01])
        self.assertEqual(engine._filter_normal_traffic_growth(series), series)
        series[-1] = minute_metric("checkout", "error_rate_5m", [0] * 45)
        series[-2] = minute_metric("checkout", "workload_ready_pods", [2] * 30 + [1] * 15)
        self.assertEqual(engine._filter_normal_traffic_growth(series), series)

    def test_normal_growth_allows_one_bucket_timestamp_skew(self):
        engine = anomaly_engine()

        def skewed(name: str, baseline: float, increased: float, offset: int) -> MetricSeries:
            item = minute_metric("checkout", name, [baseline] * 30 + [increased] * 15)
            return item.model_copy(update={"points": [point.model_copy(update={"timestamp": point.timestamp + offset}) for point in item.points]})

        series = [
            skewed("request_rate_5m", 10, 30, 0),
            skewed("cpu_millicores", 100, 300, 10),
            skewed("memory_usage_bytes", 100_000_000, 150_000_000, 20),
            skewed("socket_io_bytes_per_second", 1_000_000, 3_000_000, 30),
            skewed("p95_latency_5m", 0.05, 0.10, 40),
            skewed("error_rate_5m", 0, 0, 0),
        ]

        self.assertEqual([item.metric for item in engine._filter_normal_traffic_growth(series)], ["error_rate_5m"])

    def test_growth_gate_uses_median_three_smoothing_and_logs_rejection(self):
        self.assertTrue(hasattr(anomaly_v001, "_median3"))
        self.assertEqual(anomaly_v001._median3([10, 100, 10]), [10, 10, 10])
        engine = anomaly_engine()
        with self.assertLogs("aiops.anomaly.v001", level="INFO") as logs:
            engine._filter_normal_traffic_growth(
                [
                    minute_metric("checkout", "request_rate_5m", [10] * 45),
                    minute_metric("payment", "request_rate_5m", [10] * 45),
                ]
            )
        self.assertEqual(len(logs.records), 1)
        self.assertIn("reason=missing_metrics", " ".join(logs.output))

    def test_growth_gate_only_measures_detection_tail(self):
        engine = anomaly_engine()
        request_rate = minute_metric("checkout", "request_rate_5m", [10] * 30 + [30] * 15)

        timestamps = engine._increase_timestamps(request_rate, "request_rate")
        cutoff = request_rate.points[-1].timestamp - engine.detection_window_seconds

        self.assertTrue(timestamps)
        self.assertTrue(all(timestamp >= cutoff for timestamp in timestamps))

    def test_staggered_load_growth_is_not_treated_as_simultaneous(self):
        engine = anomaly_engine()

        def values(baseline: float, increased: float, active: set[int]) -> list[float]:
            return [baseline] * 30 + [increased if index in active else baseline for index in range(15)]

        series = [
            minute_metric("checkout", "request_rate_5m", values(10, 30, {0, 1, 2})),
            minute_metric("checkout", "cpu_millicores", values(100, 300, {3, 4, 5})),
            minute_metric("checkout", "memory_usage_bytes", values(100_000_000, 150_000_000, {6, 7, 8})),
            minute_metric("checkout", "socket_io_bytes_per_second", values(1_000_000, 3_000_000, {9, 10, 11})),
            minute_metric("checkout", "p95_latency_5m", values(0.05, 0.10, {12, 13, 14})),
            minute_metric("checkout", "error_rate_5m", [0] * 45),
        ]

        self.assertEqual(engine._filter_normal_traffic_growth(series), series)

    def test_latency_above_slo_is_kept_when_traffic_increases(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="p95_latency_5m", signal_id="checkout_p95_latency_5m", score=0.5, timestamp=7)
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "p95_latency_5m", [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 1.0]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_infra(findings, series), findings)

    def test_busy_disk_without_failure_signal_is_suppressed(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="disk_io_bytes_per_second",
                signal_id="checkout_disk_io_bytes_per_second",
                score=0.5,
                timestamp=7,
            )
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "p95_latency_5m", [1, 1, 1, 1, 1, 1, 1, 1]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_infra(findings, series), [])

    def test_disk_with_failure_signal_is_kept(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="disk_io_bytes_per_second",
                signal_id="checkout_disk_io_bytes_per_second",
                score=0.5,
                timestamp=7,
            ),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=0.5, timestamp=7),
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 10]),
        ]

        self.assertEqual(engine._suppress_busy_infra(findings, series), findings)

    def test_log_metric_does_not_keep_busy_cpu_anomaly(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.5, timestamp=7),
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="log_template_count_abc",
                signal_id="checkout_log_template_count_abc",
                score=0.5,
                timestamp=7,
            ),
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "log_template_count_abc", [0, 0, 0, 0, 0, 0, 0, 10]),
        ]

        self.assertEqual([finding.metric for finding in engine._suppress_busy_cpu(findings, series)], ["log_template_count_abc"])

    def test_memory_growth_without_failure_signal_is_suppressed(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="memory_usage_bytes",
                signal_id="checkout_memory_usage_bytes",
                score=0.5,
                timestamp=7,
            )
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "p95_latency_5m", [1, 1, 1, 1, 1, 1, 1, 1]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 0]),
        ]

        self.assertEqual(engine._suppress_busy_cpu(findings, series), [])

    def test_oom_signal_is_kept(self):
        engine = anomaly_engine()
        findings = [
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="oom_kills",
                signal_id="checkout_oom_kills",
                score=0.5,
                timestamp=7,
            )
        ]
        series = [
            metric("checkout", "request_rate_5m", [10, 10, 10, 10, 10, 10, 10, 100]),
            metric("checkout", "oom_kills", [0, 0, 0, 0, 0, 0, 0, 1]),
        ]

        self.assertEqual(engine._suppress_busy_cpu(findings, series), findings)

    def test_log_template_builder_groups_variable_log_lines_as_metric_series(self):
        builder = LogTemplateMetricBuilder(min_nonzero_buckets=1)
        builder.template_miner = None

        series = builder.build(
            [
                ("checkout", 10, "payment failed order=123 status=500"),
                ("checkout", 11, "payment failed order=456 status=500"),
            ]
        )

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].service, "checkout")
        self.assertTrue(series[0].metric.startswith("log_template_count_"))
        self.assertEqual(series[0].points[-1].value, 2.0)

    def test_v001_engine_drops_log_metrics_without_metric_anomaly(self):
        logs = [("checkout", 10, "payment failed order=123 status=500")] * 8

        findings = anomaly_engine().evaluate([], logs=logs)

        self.assertEqual(findings, [])

    def test_v001_engine_keeps_log_metrics_near_metric_anomaly(self):
        logs = [("checkout", 7, "payment failed order=123 status=500")] * 8

        findings = anomaly_engine().evaluate([metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0, 0, 10])], logs=logs)

        self.assertIn("error_rate_5m", [finding.metric for finding in findings])
        self.assertTrue(any(finding.metric.startswith("log_template_count_") for finding in findings))

    def test_v001_pipeline_ranks_top_root_cause_service_and_metrics(self):
        series = [
            metric("checkout", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 2.0, 2.1, 2.0]),
            metric("payment", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 20.0, 21.0, 22.0]),
            metric("payment", "error", [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 9.0, 10.0, 11.0]),
        ]
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = anomaly_engine(ewma_z_threshold=0.5).evaluate(series)
        result = rca_engine(runtime_config).rank(findings, series, top_k=3)

        self.assertEqual({finding.algorithm for finding in findings}, {"weighted_sum"})
        result_anomalies = [(finding.algorithm, finding.service, finding.metric) for finding in result.anomalies]
        self.assertTrue(all((finding.algorithm, finding.service, finding.metric) in result_anomalies for finding in findings))
        self.assertEqual(result.root_causes[0].service, "payment")
        self.assertEqual(result.root_causes[0].root_cause_metrics, ["error"])
        self.assertFalse(any("robust_score=" in item for item in result.root_causes[0].evidence))
        self.assertTrue(any("weighted_rrf_score=" in item for item in result.root_causes[0].evidence))

    def test_rca_excludes_observability_testing_and_protected_flagd_roots(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            # Higher raw scores, but not valid business root causes.
            AnomalyFinding(algorithm="test", service="jaeger", metric="cpu", signal_id="jaeger_cpu", score=99.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="load-generator", metric="cpu", signal_id="load_generator_cpu", score=98.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="flagd", metric="cpu", signal_id="flagd_cpu", score=97.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="checkout", metric="cpu", signal_id="checkout_cpu", score=7.0, timestamp=1),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        root_services = [candidate.service for candidate in result.root_causes]
        self.assertEqual(root_services[0], "checkout")
        self.assertTrue({"jaeger", "load-generator", "flagd"}.isdisjoint(root_services))

    def test_rca_does_not_rank_robust_score_without_anomaly_gate(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        series = [
            metric("ad", "cpu_millicores", [1, 1, 1, 1, 1, 1, 1, 100]),
            metric("shipping", "cpu_millicores", [1, 1, 1, 1, 1, 1, 1, 90]),
        ]

        result = rca_engine(runtime_config).rank([], series, top_k=5)

        self.assertEqual(result.root_causes, [])

    def test_rca_requires_weighted_anomaly_gate_before_rankers(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        series = [
            metric("payment", "latency", [1, 1, 1, 1, 1, 1, 1, 20]),
            metric("checkout", "latency", [1, 1, 1, 1, 1, 1, 1, 2]),
        ]

        result = rca_engine(runtime_config).rank([], series, top_k=3)

        self.assertEqual(result.root_causes, [])

    def test_rca_outputs_only_services_with_metric_evidence(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=1.0, timestamp=100)
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual([candidate.service for candidate in result.root_causes], ["checkout"])
        self.assertTrue(all(candidate.root_cause_metrics for candidate in result.root_causes))

    def test_rca_does_not_use_log_template_as_root_cause_metric(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(
                algorithm="weighted_sum",
                service="checkout",
                metric="log_template_count_ae9e5cabb7",
                signal_id="checkout_log_template_count_ae9e5cabb7",
                score=1.0,
                timestamp=100,
            )
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes, [])

    def test_rca_returns_top_k_root_causes(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="product-catalog", metric="error_rate_5m", signal_id="product_catalog_error_rate_5m", score=0.65, timestamp=1),
            AnomalyFinding(algorithm="weighted_sum", service="product-reviews", metric="error_rate_5m", signal_id="product_reviews_error_rate_5m", score=0.64, timestamp=1),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual([candidate.service for candidate in result.root_causes], ["product-catalog", "product-reviews"])

    def test_rca_keeps_request_rate_and_latency_as_context_not_root_cause_metrics(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="request_rate_5m", signal_id="checkout_request_rate_5m", score=1.0, timestamp=1),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="p95_latency_5m", signal_id="checkout_p95_latency_5m", score=1.0, timestamp=1),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=1.0, timestamp=1),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes[0].root_cause_metrics, ["error_rate_5m"])

    def test_rca_does_not_use_context_metrics_for_ranking(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="request_rate_5m", signal_id="checkout_request_rate_5m", score=99.0, timestamp=5),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=0.1, timestamp=5),
            AnomalyFinding(algorithm="weighted_sum", service="payment", metric="error_rate_5m", signal_id="payment_error_rate_5m", score=1.0, timestamp=5),
        ]
        series = [
            metric("checkout", "request_rate_5m", [1, 1, 1, 1, 1, 10]),
            metric("checkout", "cpu_millicores", [1, 1, 1, 1, 1, 10]),
            metric("payment", "error_rate_5m", [0, 10, 0, 10, 0, 10]),
        ]

        result = rca_engine(runtime_config, ranker_weights={"graph": 0.0, "earliest_drift": 0.0, "correlation": 1.0}).rank(findings, series, top_k=5)

        self.assertEqual(result.root_causes[0].service, "payment")

    def test_rca_drops_busy_infra_when_traffic_increases_without_failure(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=1.0, timestamp=5)
        ]
        series = [
            metric("checkout", "request_rate_5m", [1, 1, 1, 1, 1, 10]),
            metric("checkout", "cpu_millicores", [1, 1, 1, 1, 1, 10]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 0]),
            metric("checkout", "p95_latency_5m", [1, 1, 1, 1, 1, 1]),
        ]

        result = rca_engine(runtime_config).rank(findings, series, top_k=5)

        self.assertEqual(result.root_causes, [])

    def test_rca_keeps_infra_when_traffic_increases_with_failure_signal(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=1.0, timestamp=5),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=1.0, timestamp=5),
        ]
        series = [
            metric("checkout", "request_rate_5m", [1, 1, 1, 1, 1, 10]),
            metric("checkout", "cpu_millicores", [1, 1, 1, 1, 1, 10]),
            metric("checkout", "error_rate_5m", [0, 0, 0, 0, 0, 10]),
        ]

        result = rca_engine(runtime_config).rank(findings, series, top_k=5)

        self.assertEqual(result.root_causes[0].root_cause_metrics, ["error_rate_5m", "cpu_millicores"])

    def test_rca_drops_tiny_disk_drift(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="recommendation", metric="error_rate_5m", signal_id="recommendation_error_rate_5m", score=1.0, timestamp=10),
        ]
        series = [
            metric("recommendation", "error_rate_5m", [0] * 8 + [10, 10, 10]),
            metric("recommendation", "disk_io_bytes_per_second", [0] * 8 + [3000, 3000, 3000]),
        ]

        result = rca_engine(runtime_config, drift_min_points=8).rank(findings, series, top_k=5)

        self.assertEqual(result.root_causes[0].root_cause_metrics, ["error_rate_5m"])

    def test_rca_prioritizes_error_rate_over_infra_metrics(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="cpu_millicores", signal_id="checkout_cpu_millicores", score=99.0, timestamp=5),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=1.0, timestamp=5),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes[0].root_cause_metrics[:2], ["error_rate_5m", "cpu_millicores"])

    def test_rca_drops_context_only_root_cause_candidates(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="request_rate_5m", signal_id="checkout_request_rate_5m", score=1.0, timestamp=1),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="p95_latency_5m", signal_id="checkout_p95_latency_5m", score=1.0, timestamp=1),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes, [])

    def test_rca_prefers_dependency_that_drifted_before_checkout(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="cart", metric="error_rate_5m", signal_id="cart_error_rate_5m", score=0.8, timestamp=305),
            AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="error_rate_5m", signal_id="checkout_error_rate_5m", score=0.8, timestamp=330),
        ]
        series = [
            metric("cart", "error_rate_5m", [0] * 305 + [10] * 55),
            metric("checkout", "error_rate_5m", [0] * 330 + [10] * 30),
        ]

        result = rca_engine(runtime_config, drift_min_points=5).rank(findings, series, top_k=5)

        self.assertEqual(result.root_causes[0].service, "cart")

    def test_graph_traversal_uses_pagerank_and_timestamp_scoring(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        scores = graph_rca(runtime_config).rank_services(
            [
                AnomalyFinding(algorithm="weighted_sum", service="checkout", metric="latency", signal_id="checkout_latency", score=1.0, timestamp=100),
                AnomalyFinding(algorithm="weighted_sum", service="frontend", metric="latency", signal_id="frontend_latency", score=1.0, timestamp=90),
            ]
        )

        self.assertIn("product-catalog", scores)
        self.assertGreater(scores["checkout"], scores["frontend"])

    def test_graph_traversal_keeps_observed_service_missing_from_topology(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        scores = graph_rca(runtime_config).rank_services(
            [
                AnomalyFinding(algorithm="weighted_sum", service="carts", metric="cpu", signal_id="carts_cpu", score=1.0, timestamp=100),
            ]
        )

        self.assertIn("carts", scores)

    def test_rca_keeps_runtime_service_names_unmodified_without_suffix_config(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="orders-db", metric="diskio", signal_id="orders_db_diskio", score=1.0, timestamp=100),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes[0].service, "orders-db")

    def test_rca_does_not_invent_metric_aliases_without_runtime_config(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="payment", metric="socket", signal_id="payment_socket", score=1.0, timestamp=100),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual(result.root_causes[0].root_cause_metrics, ["socket"])

    def test_pipeline_api_accepts_metric_series_and_returns_rca_result(self):
        series = [
            metric("checkout", "latency", [1] * 350 + [2] * 10),
            metric("payment", "latency", [1] * 350 + [20] * 10),
            metric("payment", "error", [0] * 350 + [20] * 10),
        ]
        with TemporaryDirectory() as tmp:
            settings = Settings().model_copy(update={"state_store_path": Path(tmp) / "aiops.sqlite3"})
            output = io.StringIO()
            with redirect_stdout(output):
                result = run_static_pipeline(PipelineRunRequest(metric_series=series), settings=settings)

        self.assertEqual(result.rca_result.root_causes[0].service, "payment")
        logs = output.getvalue()
        self.assertIn("AIOPS_ANOMALY", logs)
        self.assertIn("AIOPS_ROOT_CAUSE", logs)
        self.assertNotIn("AIOPS_INCIDENT", logs)


if __name__ == "__main__":
    unittest.main()
