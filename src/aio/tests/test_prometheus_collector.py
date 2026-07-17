import unittest
from pathlib import Path

from aiops.collectors import PrometheusCollector
from aiops.config import load_runtime_config
from aiops.schemas import SignalQuality


class FakePrometheus:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, query: str) -> dict:
        self.queries.append(query)
        return {"data": {"result": [{"metric": {}, "value": [123.0, "0.2"]}]}}


class PrometheusCollectorTest(unittest.TestCase):
    def test_collects_runtime_signals_as_observations(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FakePrometheus()
        observations = PrometheusCollector(client, config).collect()

        prometheus_signals = [signal for signal in config.signals if signal.source == "prometheus"]
        signal_query_ids = {signal.query_id for signal in config.signals if signal.source == "prometheus"}
        services_with_metrics = {signal.service for signal in config.signals if signal.query_id.endswith(".error_rate.5m")}

        self.assertTrue(signal_query_ids.issubset(config.prometheus_queries))
        self.assertEqual(client.queries, [config.prometheus_queries[signal.query_id] for signal in prometheus_signals])
        self.assertEqual(services_with_metrics, {service.name for service in config.topology.services})
        self.assertEqual(len(observations), len(signal_query_ids))
        self.assertEqual(observations[0].value, 0.2)
        self.assertEqual(observations[0].labels["query_id"], "checkout.bad_ratio.24h")
        self.assertEqual(observations[1].labels["dependency"], "payment")
        self.assertEqual(observations[0].quality, SignalQuality.UNQUALIFIED)


if __name__ == "__main__":
    unittest.main()
