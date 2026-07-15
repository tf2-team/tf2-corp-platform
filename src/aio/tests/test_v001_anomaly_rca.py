import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.anomaly import V001AnomalyEngine
from aiops.api.app import run_static_pipeline
from aiops.config import Settings, load_runtime_config
from aiops.rca import V001RcaEngine
from aiops.schemas import MetricPoint, MetricSeries, PipelineRunRequest, RuntimeConfig


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


class V001AnomalyRcaTest(unittest.TestCase):
    def test_v001_pipeline_ranks_top_root_cause_service_and_metrics(self):
        series = [
            metric("checkout", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 2.0, 2.1, 2.0]),
            metric("payment", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 20.0, 21.0, 22.0]),
            metric("payment", "error", [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 9.0, 10.0, 11.0]),
        ]
        config_data = load_runtime_config(Path("config/runtime.json")).model_dump()
        config_data["rca"].update({"top_k": 3, "ewma_z_threshold": 0.5, "bocpd_score_threshold": 1.0})
        runtime_config = RuntimeConfig.model_validate(config_data)

        findings = V001AnomalyEngine(
            ewma_alpha=runtime_config.rca.ewma_alpha,
            ewma_z_threshold=runtime_config.rca.ewma_z_threshold,
            isolation_score_threshold=runtime_config.rca.isolation_score_threshold,
            bocpd_score_threshold=runtime_config.rca.bocpd_score_threshold,
            min_points=runtime_config.rca.min_points,
            seasonal_period=runtime_config.rca.seasonal_period,
        ).evaluate(series)
        result = V001RcaEngine(runtime_config).rank(findings, series, top_k=3)

        self.assertTrue({finding.algorithm for finding in findings} >= {"ewma_stl", "isolation_forest", "baro_bocpd"})
        self.assertEqual(result.root_causes[0].service, "payment")
        self.assertIn("latency", result.root_causes[0].root_cause_metrics)

    def test_pipeline_api_accepts_metric_series_and_returns_rca_result(self):
        series = [
            metric("checkout", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 2.0, 2.1, 2.0]),
            metric("payment", "latency", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 20.0, 21.0, 22.0]),
            metric("payment", "error", [0.0, 0.1, 0.0, 0.1, 0.0, 0.1, 0.0, 9.0, 10.0, 11.0]),
        ]
        with TemporaryDirectory() as tmp:
            settings = Settings().model_copy(update={"state_store_path": Path(tmp) / "aiops.sqlite3"})
            result = run_static_pipeline(PipelineRunRequest(metric_series=series), settings=settings)

        self.assertEqual(result.rca_result.root_causes[0].service, "payment")


if __name__ == "__main__":
    unittest.main()
