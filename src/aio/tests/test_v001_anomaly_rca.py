import io
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.anomaly import V001AnomalyEngine
from aiops.anomaly.v001 import AnomalyMergeQueue, EwmaStlDetector, LogTemplateAnomalyDetector, ServiceIsolationForestDetector
from aiops.api.app import run_static_pipeline
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.rca.graph import GraphTraversalRca
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricPoint, MetricSeries, PipelineRunRequest, RuntimeConfig


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


def rca_hyperparameters(**overrides):
    config = load_hyperparameters(Path("config/hyperparameters.json"))["rca"]
    return {**config, **overrides}


def anomaly_engine(**overrides) -> V001AnomalyEngine:
    config = rca_hyperparameters()
    config = {**config, "min_points": overrides.pop("min_points", 8), **overrides}
    return V001AnomalyEngine(
        ewma_alpha=config["ewma_alpha"],
        ewma_z_threshold=config["ewma_z_threshold"],
        isolation_score_threshold=config["isolation_score_threshold"],
        min_points=config["min_points"],
        seasonal_period=config["seasonal_period"],
        algorithm_weights=config["anomaly"]["algorithm_weights"],
        weighted_score_threshold=config["anomaly"]["weighted_score_threshold"],
        log_history_buckets=8,
        log_min_nonzero_buckets=1,
        single_algorithm_min_normalized_score=config["anomaly"]["single_algorithm_min_normalized_score"],
    )


def rca_engine(config: RuntimeConfig) -> V001RcaEngine:
    hyperparameters = rca_hyperparameters()
    return V001RcaEngine(config, hyperparameters["graph"], hyperparameters["combined"])


def graph_rca(config: RuntimeConfig) -> GraphTraversalRca:
    return GraphTraversalRca(config, **rca_hyperparameters()["graph"])


class V001AnomalyRcaTest(unittest.TestCase):
    def test_ewma_formula_does_not_emit_statsmodels_zero_sse_warning(self):
        detector = EwmaStlDetector(alpha=0.3, z_threshold=3.0, min_points=8, seasonal_period=1)

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            residuals = detector._residuals([1.0] * 8)

        self.assertEqual(len(residuals), 8)

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

    def test_weighted_sum_ignores_weak_single_algorithm_without_corroboration(self):
        engine = anomaly_engine()

        findings = engine._weighted_sum(
            [AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=4.0, timestamp=1)]
        )

        self.assertEqual(findings, [])

    def test_weighted_sum_keeps_strong_single_algorithm_detection(self):
        engine = anomaly_engine()

        findings = engine._weighted_sum(
            [AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=8.0, timestamp=1)]
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

    def test_memory_growth_is_kept_as_early_oom_signal(self):
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

        self.assertEqual(engine._suppress_busy_cpu(findings, series), findings)

    def test_anomaly_merge_queue_drains_detector_findings_fifo(self):
        queue = AnomalyMergeQueue()
        ewma = AnomalyFinding(algorithm="ewma_stl", service="checkout", metric="latency", signal_id="checkout_latency", score=4.0, timestamp=1)
        isolation = AnomalyFinding(
            algorithm="isolation_forest",
            service="checkout",
            metric="latency",
            signal_id="checkout_latency",
            score=8.0,
            timestamp=1,
        )

        queue.push_many([ewma])
        queue.push_many([isolation])

        self.assertEqual([finding.algorithm for finding in queue.drain()], ["ewma_stl", "isolation_forest"])
        self.assertEqual(queue.drain(), [])

    def test_log_template_builder_groups_variable_log_lines_as_metric_series(self):
        builder = LogTemplateAnomalyDetector(min_nonzero_buckets=1)
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
        self.assertIn("latency", result.root_causes[0].root_cause_metrics)
        self.assertTrue(any("robust_score=" in item for item in result.root_causes[0].evidence))
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

    def test_rca_returns_only_top_root_cause(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            AnomalyFinding(algorithm="weighted_sum", service="product-catalog", metric="request_rate_5m", signal_id="product_catalog_request_rate_5m", score=0.65, timestamp=1),
            AnomalyFinding(algorithm="weighted_sum", service="product-reviews", metric="request_rate_5m", signal_id="product_reviews_request_rate_5m", score=0.64, timestamp=1),
        ]

        result = rca_engine(runtime_config).rank(findings, [], top_k=5)

        self.assertEqual([candidate.service for candidate in result.root_causes], ["product-catalog"])

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

    def test_pipeline_api_accepts_metric_series_and_returns_rca_result(self):
        series = [
            metric("checkout", "latency", [1] * 59 + [2]),
            metric("payment", "latency", [1] * 59 + [20]),
            metric("payment", "error", [0] * 59 + [20]),
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
