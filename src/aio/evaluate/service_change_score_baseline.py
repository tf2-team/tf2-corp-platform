from __future__ import annotations

import argparse
import json
from pathlib import Path

from e2e_pipeline import (
    ROOT,
    expected_metric_family,
    expected_service,
    is_anomalous,
    list_case_dirs,
    rca_hit,
    read_series,
    score_report,
    series_change_score,
)
from aiops.config import Settings
from aiops.schemas import MetricSeries


def rank_roots(series: list[MetricSeries], top_k: int) -> list[dict[str, object]]:
    """Rank services by the sum of last-point changes across their metrics."""
    services: dict[str, dict[str, object]] = {}
    for metric in series:
        score = series_change_score(metric)
        root = services.setdefault(
            metric.service,
            {"service": metric.service, "metrics": [], "score": 0.0},
        )
        root["metrics"].append((metric.metric, score))
        root["score"] = float(root["score"]) + score

    ranked = sorted(services.values(), key=lambda item: float(item["score"]), reverse=True)[:top_k]
    return [
        {
            "service": item["service"],
            "metrics": [name for name, _ in sorted(item["metrics"], key=lambda pair: pair[1], reverse=True)],
            "score": item["score"],
        }
        for item in ranked
    ]


def evaluate_case(
    path: Path,
    dataset: Path,
    top_k: int,
    max_metrics: int,
    incident_threshold: float,
) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    predicted_roots = rank_roots(series, top_k)
    expected_root = expected_service(path)
    expected_metric = expected_metric_family(path)
    return {
        "case_id": str(path.relative_to(dataset)),
        "expected_incident": True,
        "predicted_incident": any(is_anomalous(metric, incident_threshold) for metric in series),
        "expected_root_service": expected_root,
        "expected_root_metric": expected_metric,
        "expected_root_causes": [expected_root],
        "predicted_root_causes": predicted_roots,
        "predicted_root_services": [root["service"] for root in predicted_roots],
        "rca_top_k_hit": rca_hit(expected_root, expected_metric, predicted_roots),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Service aggregated last-point change RCA baseline.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--incident-threshold", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    top_k = args.top_k or Settings().rca_top_k
    paths = list_case_dirs(dataset)
    if args.limit:
        paths = paths[: args.limit]
    cases = [
        evaluate_case(path, dataset, top_k, args.max_metrics, args.incident_threshold)
        for path in paths
    ]
    report = {
        "pipeline": "service-change-score-baseline",
        "change_score": "abs(last_value - mean(previous_values))",
        "service_aggregation": "sum",
        "metrics": score_report(cases),
        "top_k": top_k,
        "incident_threshold": args.incident_threshold,
        "case_count": len(cases),
        "cases": cases,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
