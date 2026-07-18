import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluate"))

from aiops.schemas import MetricPoint, MetricSeries
from service_change_score_baseline import rank_roots


def metric(service: str, name: str, values: list[float]) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=name,
        signal_id=f"{service}_{name}",
        points=[MetricPoint(timestamp=index, value=value) for index, value in enumerate(values)],
    )


class ServiceChangeScoreBaselineTest(unittest.TestCase):
    def test_sum_of_changes_can_outrank_largest_single_metric(self):
        series = [
            metric("single-spike", "latency", [0, 0, 0, 0, 10]),
            metric("multi-change", "latency", [0, 0, 0, 0, 6]),
            metric("multi-change", "error", [0, 0, 0, 0, 6]),
        ]

        roots = rank_roots(series, top_k=2)

        self.assertEqual(roots[0]["service"], "multi-change")
        self.assertEqual(roots[0]["score"], 12.0)
        self.assertEqual(roots[1]["service"], "single-spike")
        self.assertEqual(roots[1]["score"], 10.0)

    def test_metrics_are_ordered_by_change_contribution(self):
        roots = rank_roots(
            [
                metric("payment", "cpu", [1, 1, 1, 1, 3]),
                metric("payment", "latency", [1, 1, 1, 1, 8]),
            ],
            top_k=1,
        )

        self.assertEqual(roots[0]["metrics"], ["latency", "cpu"])
        self.assertEqual(roots[0]["score"], 9.0)

    def test_short_series_has_zero_change(self):
        roots = rank_roots([metric("payment", "latency", [9])], top_k=1)

        self.assertEqual(roots[0]["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
