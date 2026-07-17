import unittest
from datetime import UTC, datetime
from pathlib import Path

from aiops.collectors import PrometheusCollector
from aiops.config import load_runtime_config
from aiops.schemas import SignalQuality


class FakePrometheus:
    def __init__(self):
        self.queries: list[str] = []
        self.range_queries: list[tuple[str, str, str, str]] = []

    def query(self, query: str) -> dict:
        self.queries.append(query)
        return {"data": {"result": [{"metric": {}, "value": [123.0, "0.2"]}]}}

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        return {"data": {"result": [{"metric": {}, "values": [[123 + index, str(index)] for index in range(8)]}]}}


class FailingRangePrometheus(FakePrometheus):
    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        raise RuntimeError("prometheus rejected query")


class PrometheusCollectorTest(unittest.TestCase):
    def test_collects_runtime_signals_as_observations(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FakePrometheus()
        observations = PrometheusCollector(client, config).collect()

        prometheus_signals = [signal for signal in config.signals if signal.source == "prometheus"]
        signal_query_ids = {signal.query_id for signal in config.signals if signal.source == "prometheus"}
        services_with_metrics = {signal.service for signal in config.signals if signal.query_id.endswith(".error_rate.5m")}
        app_services = {service.name for service in config.topology.services if service.name not in {"postgresql", "valkey-cart"}}

        self.assertTrue(signal_query_ids.issubset(config.prometheus_queries))
        self.assertEqual(client.queries, [config.prometheus_queries[signal.query_id] for signal in prometheus_signals])
        self.assertEqual(services_with_metrics, app_services)
        self.assertEqual(len(observations), len(signal_query_ids))
        self.assertEqual(observations[0].value, 0.2)
        self.assertEqual(observations[0].labels["query_id"], "checkout.bad_ratio.24h")
        self.assertEqual(observations[1].labels["dependency"], "payment")
        self.assertEqual(observations[0].quality, SignalQuality.UNQUALIFIED)

    def test_collects_runtime_anomaly_inputs_as_metric_series(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FakePrometheus()
        captured_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

        series = PrometheusCollector(client, config, captured_at=captured_at).collect_metric_series(lookback_seconds=3600, step_seconds=60)

        anomaly_signals = [signal for signal in config.signals if signal.source == "prometheus" and signal.feature_role == "anomaly_input"]
        self.assertEqual([item.signal_id for item in series], [signal.id for signal in anomaly_signals])
        self.assertEqual(client.range_queries, [(config.prometheus_queries[signal.query_id], "1784199600.0", "1784203200.0", "60") for signal in anomaly_signals])
        self.assertTrue(all(len(item.points) == 8 for item in series))
        self.assertIn("p95_latency_5m", {item.metric for item in series})
        self.assertIn("cpu_millicores", {item.metric for item in series})

    def test_runtime_metric_series_query_failure_returns_empty_series(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FailingRangePrometheus()

        series = PrometheusCollector(client, config).collect_metric_series(lookback_seconds=3600, step_seconds=60)

        self.assertEqual(len(series), len(client.range_queries))
        self.assertTrue(all(item.points == [] for item in series))


if __name__ == "__main__":
    unittest.main()
