from __future__ import annotations

import argparse
import json
from pathlib import Path

from e2e_pipeline import ROOT, expected_metric_family, expected_service, list_case_dirs, read_series, rca_hit, score_report
from aiops.anomaly.stats import robust_score
from aiops.config import Settings
from aiops.schemas import MetricSeries
from incident_labels import IncidentLabel, label_for_case, load_label_sheet, validate_dataset_coverage


def metric_score(series: MetricSeries) -> float:
    values = [point.value for point in series.points]
    return robust_score(values[:-1], values[-1:])


def rank_roots(series: list[MetricSeries], top_k: int) -> list[dict[str, object]]:
    services: dict[str, dict[str, object]] = {}
    for metric in series:
        score = metric_score(metric)
        root = services.setdefault(metric.service, {"service": metric.service, "metrics": [], "score": score})
        root["metrics"].append(metric.metric)
        root["score"] = max(float(root["score"]), score)
    ranked = sorted(services.values(), key=lambda item: float(item["score"]), reverse=True)[:top_k]
    return [{"service": item["service"], "metrics": item["metrics"]} for item in ranked]


def evaluate_case(path: Path, dataset: Path, labels: dict[str, IncidentLabel] | None, top_k: int, max_metrics: int, threshold: float) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    roots = rank_roots(series, top_k)
    label = label_for_case(path, dataset, labels) if labels is not None else None
    expected_root = label.expected_root_service if label else expected_service(path)
    expected_metric = label.expected_root_metric if label else expected_metric_family(path)
    return {"case_id": label.case_id if label else str(path.relative_to(dataset)), "expected_incident": label.expected_incident if label else True,
            "predicted_incident": any(metric_score(metric) >= threshold for metric in series),
            "expected_root_service": expected_root, "expected_root_metric": expected_metric,
            "expected_root_causes": [expected_root] if expected_root else [],
            "expected_action": label.expected_action if label else None,
            "predicted_root_causes": roots,
            "predicted_root_services": [root["service"] for root in roots],
            "rca_top_k_hit": rca_hit(expected_root, expected_metric, roots)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Naive last-point robust-score baseline (no BARO).")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--incident-threshold", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--labels", type=Path, default=None)
    args = parser.parse_args()
    top_k = args.top_k or Settings().rca_top_k
    dataset = args.dataset.resolve()
    paths = list_case_dirs(dataset)
    if args.limit:
        paths = paths[:args.limit]
    labels = load_label_sheet(args.labels) if args.labels else None
    if labels is not None:
        validate_dataset_coverage(dataset, labels)
    cases = [evaluate_case(path, dataset, labels, top_k, args.max_metrics, args.incident_threshold) for path in paths]
    report = {"metrics": score_report(cases), "top_k": top_k, "incident_threshold": args.incident_threshold, "case_count": len(cases), "cases": cases}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
