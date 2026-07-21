#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
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

    def query(self, query: str, time: str | None = None) -> dict:
        self.queries.append(query)
        return {"data": {"result": [{"metric": {}, "value": [123.0, "0.2"]}]}}

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        first = int(start)
        spacing = int(step)
        return {"data": {"result": [{"metric": {}, "values": [[first + index * spacing, str(index)] for index in range(8)]}]}}


class FailingRangePrometheus(FakePrometheus):
    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        raise RuntimeError("prometheus rejected query")


class EmptyPrometheus(FakePrometheus):
    def query(self, query: str, time: str | None = None) -> dict:
        self.queries.append(query)
        return {"data": {"result": []}}


class ZeroFallbackPrometheus(FakePrometheus):
    def query(self, query: str, time: str | None = None) -> dict:
        self.queries.append(query)
        if "or on() vector(0)" not in query:
            return {"data": {"result": []}}
        return {"data": {"result": [{"metric": {}, "value": [123.0, "0"]}]}}

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        if "or on() vector(0)" not in query:
            return {"data": {"result": []}}
        first = int(start)
        spacing = int(step)
        values = [[first + index * spacing, "0"] for index in range(8)]
        return {"data": {"result": [{"metric": {}, "values": values}]}}


class CardinalityPrometheus(FakePrometheus):
    def query(self, query: str, time: str | None = None) -> dict:
        self.queries.append(query)
        return {
            "data": {
                "result": [
                    {"metric": {"pod": "one"}, "value": [123.0, "0.1"]},
                    {"metric": {"pod": "two"}, "value": [123.0, "0.2"]},
                ]
            }
        }


class GapPrometheus(FakePrometheus):
    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        self.range_queries.append((query, start, end, step))
        first = int(start)
        return {"data": {"result": [{"metric": {}, "values": [[first, "1"], [first + 2, "2"]]}]}}


class PrometheusCollectorTest(unittest.TestCase):
    def test_collects_runtime_signals_as_observations(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FakePrometheus()
        observations = PrometheusCollector(client, config).collect()

        prometheus_signals = [
            signal
            for signal in config.signals
            if signal.source == "prometheus" and "instant" in config.prometheus_query_specs[signal.query_id].modes
        ]
        signal_query_ids = {signal.query_id for signal in config.signals if signal.source == "prometheus"}
        services_with_metrics = {signal.service for signal in config.signals if signal.query_id.endswith(".error_rate_5m")}

        self.assertTrue(signal_query_ids.issubset(config.prometheus_queries))
        self.assertCountEqual(client.queries, [config.prometheus_queries[signal.query_id] for signal in prometheus_signals])
        self.assertTrue(services_with_metrics.issubset(config.prometheus_services))
        self.assertEqual(len(observations), len(signal_query_ids))
        self.assertEqual(observations[0].value, 0.2)
        checkout_slo = next(item for item in observations if item.signal_id == "checkout_bad_ratio_24h")
        payment_dependency = next(item for item in observations if item.signal_id == "checkout_payment_error_rate_5m")
        self.assertEqual(checkout_slo.labels["query_id"], "checkout.bad_ratio.24h")
        self.assertEqual(payment_dependency.labels["dependency"], "payment")
        self.assertEqual(observations[0].quality, SignalQuality.UNQUALIFIED)

    def test_collects_runtime_anomaly_inputs_as_metric_series(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FakePrometheus()
        captured_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

        series = PrometheusCollector(client, config, captured_at=captured_at).collect_metric_series()

        anomaly_signals = [signal for signal in config.signals if signal.source == "prometheus" and signal.feature_role == "anomaly_input"]
        self.assertEqual([item.signal_id for item in series], [signal.id for signal in anomaly_signals])
        self.assertCountEqual(client.range_queries, [(config.prometheus_queries[signal.query_id], "1784199600", "1784203200", "1") for signal in anomaly_signals])
        self.assertTrue(all(len(item.points) == 8 for item in series))
        self.assertTrue(all(item.step_seconds == 1 for item in series))
        self.assertTrue(all(item.detector_bucket_seconds == 30 for item in series))
        self.assertIn("p95_latency_5m", {item.metric for item in series})
        self.assertIn("p99_latency_5m", {item.metric for item in series})
        self.assertIn("cpu_millicores", {item.metric for item in series})

    def test_runtime_metric_series_query_failure_returns_empty_series(self):
        config = load_runtime_config(Path("config/runtime.json"))
        client = FailingRangePrometheus()

        series = PrometheusCollector(client, config).collect_metric_series()

        self.assertEqual(len(series), len(client.range_queries))
        self.assertTrue(all(item.points == [] for item in series))
        self.assertTrue(all(item.quality == SignalQuality.MISSING for item in series))

    def test_raw_empty_api_result_remains_missing(self):
        config = load_runtime_config(Path("config/runtime.json"))
        observations = PrometheusCollector(EmptyPrometheus(), config).collect()

        self.assertTrue(all(item.value is None for item in observations))
        self.assertTrue(all(item.quality == SignalQuality.MISSING for item in observations))

    def test_registry_zero_fallback_returns_numeric_zero(self):
        config = load_runtime_config(Path("config/runtime.json"))
        collector = PrometheusCollector(ZeroFallbackPrometheus(), config)
        observations = collector.collect()
        series = collector.collect_metric_series()

        self.assertTrue(observations)
        self.assertTrue(all(item.value == 0 for item in observations))
        self.assertTrue(all(item.quality == SignalQuality.UNQUALIFIED for item in observations))
        self.assertTrue(series)
        self.assertTrue(all(point.value == 0 for item in series for point in item.points))
        self.assertTrue(all(item.quality == SignalQuality.VERIFIED for item in series))

    def test_unexpected_cardinality_is_invalid(self):
        config = load_runtime_config(Path("config/runtime.json"))
        observations = PrometheusCollector(CardinalityPrometheus(), config).collect()

        self.assertTrue(all(item.quality == SignalQuality.INVALID for item in observations))
        self.assertTrue(all(item.labels["error"] == "CardinalityExceeded" for item in observations))

    def test_one_second_series_rejects_a_two_second_gap(self):
        config = load_runtime_config(Path("config/runtime.json"))
        series = PrometheusCollector(GapPrometheus(), config).collect_metric_series()

        self.assertTrue(all(item.quality == SignalQuality.INVALID for item in series))
        self.assertTrue(all(item.error == "UnexpectedGap:2" for item in series))


if __name__ == "__main__":
    unittest.main()
