import io
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.anomaly import V001AnomalyEngine
from aiops.anomaly.v001 import BaroBocpdDetector, EwmaStlDetector
from aiops.api.app import run_static_pipeline
from aiops.config import Settings, load_runtime_config
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricPoint, MetricSeries, PipelineRunRequest, RuntimeConfig


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


class V001AnomalyRcaTest(unittest.TestCase):
    def test_ewma_formula_does_not_emit_statsmodels_zero_sse_warning(self):
        detector = EwmaStlDetector(alpha=0.3, z_threshold=3.0, min_points=8, seasonal_period=1)

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            residuals = detector._residuals([1.0] * 8)

        self.assertEqual(len(residuals), 8)

    def test_v001_detects_hidden_error_signal_that_ramps_up_slowly(self):
        findings = V001AnomalyEngine(
            ewma_alpha=0.3,
            ewma_z_threshold=3.0,
            isolation_score_threshold=4.0,
            min_points=8,
            seasonal_period=1,
        ).evaluate(
            [
                metric(
                    "payment",
                    "error_ratio_5m",
                    [0.001, 0.001, 0.001, 0.001, 0.001, 0.002, 0.003, 0.005, 0.008, 0.013, 0.021, 0.034],
                )
            ]
        )

        self.assertEqual([(finding.algorithm, finding.service, finding.metric) for finding in findings], [("weighted_sum", "payment", "error_ratio_5m")])
        self.assertGreaterEqual(findings[0].score, 0.4)

    def test_v001_does_not_flag_low_noise_as_hidden_error_signal(self):
        findings = V001AnomalyEngine(
            ewma_alpha=0.3,
            ewma_z_threshold=3.0,
            isolation_score_threshold=4.0,
            min_points=8,
            seasonal_period=1,
        ).evaluate(
            [
                metric(
                    "payment",
                    "error_ratio_5m",
                    [0.001, 0.0012, 0.0009, 0.0011, 0.001, 0.0012, 0.0008, 0.0011, 0.001, 0.0012, 0.0009, 0.001],
                )
            ]
        )

        self.assertEqual(findings, [])

    def test_baro_bocpd_requires_correlated_metric_change(self):
        detector = BaroBocpdDetector(score_threshold=4.0, min_points=8)

        findings = detector.evaluate(
            [
                metric("checkout", "latency", [1, 1, 1, 1, 1, 1, 1, 20]),
                metric("payment", "error", [0, 0, 0, 0, 0, 0, 0, 0]),
            ]
        )

        self.assertEqual(findings, [])

    def test_baro_bocpd_detects_correlated_metric_change(self):
        detector = BaroBocpdDetector(score_threshold=4.0, min_points=8)

        findings = detector.evaluate(
            [
                metric("checkout", "latency", [1, 1, 1, 1, 1, 1, 1, 20]),
                metric("payment", "error", [0, 0, 0, 0, 0, 0, 0, 10]),
            ]
        )

        self.assertEqual({finding.algorithm for finding in findings}, {"baro_bocpd"})
        self.assertEqual({finding.service for finding in findings}, {"checkout", "payment"})

    def test_weighted_sum_ignores_isolation_forest_without_corroboration(self):
        engine = V001AnomalyEngine(
            ewma_alpha=0.3,
            ewma_z_threshold=3.0,
            isolation_score_threshold=4.0,
            min_points=8,
            seasonal_period=1,
        )

        findings = engine._weighted_sum(
            [AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=99.0, timestamp=1)]
        )

        self.assertEqual(findings, [])

    def test_weighted_sum_combines_normalized_algorithm_scores(self):
        engine = V001AnomalyEngine(
            ewma_alpha=0.3,
            ewma_z_threshold=3.0,
            isolation_score_threshold=4.0,
            min_points=8,
            seasonal_period=1,
        )

        findings = engine._weighted_sum(
            [
                AnomalyFinding(algorithm="isolation_forest", service="checkout", metric="cpu", signal_id="checkout_cpu", score=99.0, timestamp=1),
                AnomalyFinding(algorithm="baro_bocpd", service="checkout", metric="cpu", signal_id="checkout_cpu", score=99.0, timestamp=1),
            ]
        )

        self.assertEqual([(finding.algorithm, finding.score) for finding in findings], [("weighted_sum", 0.6)])

    def test_v001_pipeline_ranks_top_root_cause_service_and_metrics(self):
        series = [
            metric("checkout", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 2.0, 2.1, 2.0]),
            metric("payment", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 20.0, 21.0, 22.0]),
            metric("payment", "error", [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 9.0, 10.0, 11.0]),
        ]
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        rca_hyperparameters = {
            "top_k": 3,
            "min_points": 8,
            "ewma_alpha": 0.3,
            "ewma_z_threshold": 0.5,
            "seasonal_period": 1,
            "isolation_score_threshold": 4.0,
        }

        findings = V001AnomalyEngine(
            ewma_alpha=rca_hyperparameters["ewma_alpha"],
            ewma_z_threshold=rca_hyperparameters["ewma_z_threshold"],
            isolation_score_threshold=rca_hyperparameters["isolation_score_threshold"],
            min_points=rca_hyperparameters["min_points"],
            seasonal_period=rca_hyperparameters["seasonal_period"],
        ).evaluate(series)
        result = V001RcaEngine(runtime_config).rank(findings, series, top_k=3)

        self.assertEqual({finding.algorithm for finding in findings}, {"weighted_sum"})
        self.assertEqual(result.anomalies, findings)
        self.assertEqual(result.root_causes[0].service, "payment")
        self.assertIn("latency", result.root_causes[0].root_cause_metrics)
        self.assertTrue(any("robust_score=" in item for item in result.root_causes[0].evidence))

    def test_rca_excludes_observability_testing_and_protected_flagd_roots(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        findings = [
            # Higher raw scores, but not valid business root causes.
            AnomalyFinding(algorithm="test", service="jaeger", metric="cpu", signal_id="jaeger_cpu", score=99.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="load-generator", metric="cpu", signal_id="load_generator_cpu", score=98.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="flagd", metric="cpu", signal_id="flagd_cpu", score=97.0, timestamp=1),
            AnomalyFinding(algorithm="test", service="checkout", metric="cpu", signal_id="checkout_cpu", score=7.0, timestamp=1),
        ]

        result = V001RcaEngine(runtime_config).rank(findings, [], top_k=5)

        root_services = [candidate.service for candidate in result.root_causes]
        self.assertEqual(root_services[0], "checkout")
        self.assertTrue({"jaeger", "load-generator", "flagd"}.isdisjoint(root_services))

    def test_rca_does_not_rank_robust_score_without_anomaly_gate(self):
        runtime_config = load_runtime_config(Path("config/runtime.json"))
        series = [
            metric("ad", "cpu_millicores", [1, 1, 1, 1, 1, 1, 1, 100]),
            metric("shipping", "cpu_millicores", [1, 1, 1, 1, 1, 1, 1, 90]),
        ]

        result = V001RcaEngine(runtime_config).rank([], series, top_k=5)

        self.assertEqual(result.root_causes, [])

    def test_pipeline_api_accepts_metric_series_and_returns_rca_result(self):
        series = [
            metric("checkout", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 2.0, 2.1, 2.0]),
            metric("payment", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 20.0, 21.0, 22.0]),
            metric("payment", "error", [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 9.0, 10.0, 11.0]),
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
