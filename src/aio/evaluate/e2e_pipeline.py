from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.anomaly.stats import robust_score
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricPoint, MetricSeries


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AIOps anomaly -> RCA on dataset folders.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--incident-threshold", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    top_k = args.top_k or int(hyperparameters["rca"]["top_k"])
    case_dirs = list_case_dirs(args.dataset)
    if args.limit:
        case_dirs = case_dirs[: args.limit]

    rca = V001RcaEngine(load_runtime_config(settings.runtime_config_path), hyperparameters["rca"]["graph"], hyperparameters["rca"]["combined"])
    cases = []
    for index, path in enumerate(case_dirs, start=1):
        case = evaluate_case(path, rca, top_k, args.max_metrics, args.incident_threshold)
        cases.append(case)
        if args.progress:
            print(f"{index}/{len(case_dirs)} {case['case_id']} hit={case['rca_top_k_hit']}", flush=True)
    report = {
        "metrics": score_report(cases),
        "top_k": top_k,
        "incident_threshold": args.incident_threshold,
        "case_count": len(cases),
        "cases": cases,
    }

    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


def list_case_dirs(dataset: Path) -> list[Path]:
    return sorted(path.parent for path in dataset.glob("*/*/*/simple_metrics.csv"))


def evaluate_case(path: Path, rca: V001RcaEngine, top_k: int, max_metrics: int, anomaly_threshold: float) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    findings = anomaly_findings(series, anomaly_threshold)
    result = rca.rank(findings, series, top_k)
    predicted_roots = [
        {"service": root.service, "metrics": root.root_cause_metrics}
        for root in result.root_causes[:top_k]
    ]
    expected_root = expected_service(path)
    expected_metric = expected_metric_family(path)
    return {
        "case_id": str(path.relative_to(ROOT / "evaluate" / "dataset")),
        "expected_incident": True,
        "predicted_incident": bool(findings),
        "expected_root_service": expected_root,
        "expected_root_metric": expected_metric,
        "expected_root_causes": [expected_root],
        "predicted_root_causes": predicted_roots,
        "predicted_root_services": [root["service"] for root in predicted_roots],
        "rca_top_k_hit": rca_hit(expected_root, expected_metric, predicted_roots),
    }


def anomaly_findings(series: list[MetricSeries], threshold: float) -> list[AnomalyFinding]:
    findings = []
    for metric in series:
        values = [point.value for point in metric.points]
        score = robust_score(values[:-1], values[-1:])
        if score >= threshold:
            findings.append(
                AnomalyFinding(
                    algorithm="legacy_robust_score",
                    service=metric.service,
                    metric=metric.metric,
                    signal_id=metric.signal_id,
                    score=score,
                    timestamp=metric.points[-1].timestamp,
                )
            )
    return sorted(findings, key=lambda finding: finding.score, reverse=True)


def read_series(path: Path, max_metrics: int) -> list[MetricSeries]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []

    series = []
    for column in rows[0]:
        if column == "time" or "_" not in column:
            continue
        service, metric = column.split("_", 1)
        points = []
        for index, row in enumerate(rows):
            value = to_float(row.get(column))
            if value is None:
                continue
            points.append(MetricPoint(timestamp=int(to_float(row.get("time")) or index), value=value))
        if points:
            series.append(MetricSeries(service=service, metric=metric, signal_id=column, points=points))
    if max_metrics <= 0:
        return series
    return sorted(series, key=series_change_score, reverse=True)[:max_metrics]


def series_change_score(series: MetricSeries) -> float:
    values = [point.value for point in series.points]
    if len(values) < 3:
        return 0.0
    baseline = values[:-1]
    baseline_mean = sum(baseline) / len(baseline)
    return abs(values[-1] - baseline_mean)


def is_anomalous(series: MetricSeries, threshold: float) -> bool:
    values = [point.value for point in series.points]
    return robust_score(values[:-1], values[-1:]) >= threshold


def expected_service(path: Path) -> str:
    fault_name = path.parent.name
    for suffix in ("_cpu", "_mem", "_disk", "_delay", "_loss", "_socket", "_f1", "_f2", "_f3", "_f4"):
        if fault_name.endswith(suffix):
            return fault_name[: -len(suffix)]
    return fault_name.split("_", 1)[0]


def expected_metric_family(path: Path) -> str | None:
    fault_name = path.parent.name
    suffix = fault_name.rsplit("_", 1)[-1]
    return {
        "cpu": "cpu",
        "mem": "mem",
        "disk": "disk",
        "delay": "latency",
        "loss": "error",
        "socket": "socket",
    }.get(suffix)


def rca_hit(expected_service: str, expected_metric: str | None, predicted_roots: list[dict[str, object]]) -> bool:
    for root in predicted_roots:
        if root["service"] != expected_service:
            continue
        if expected_metric is None:
            return True
        return any(expected_metric in metric for metric in root["metrics"])
    return False


def to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def score_report(cases: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    return {
        "incident": binary_scores(
            [(bool(case["expected_incident"]), bool(case["predicted_incident"])) for case in cases],
        ),
        "rca_top_k": label_scores(
            [
                (list(case["expected_root_causes"]), list(case["predicted_root_services"]))
                for case in cases
            ],
        ),
        "rca_top_k_hit": hit_scores([bool(case["rca_top_k_hit"]) for case in cases]),
    }


def binary_scores(pairs: list[tuple[bool, bool]]) -> dict[str, float]:
    tp = sum(expected and predicted for expected, predicted in pairs)
    fp = sum(not expected and predicted for expected, predicted in pairs)
    tn = sum(not expected and not predicted for expected, predicted in pairs)
    fn = sum(expected and not predicted for expected, predicted in pairs)
    return prf(tp, fp, tn, fn)


def hit_scores(hits: list[bool]) -> dict[str, float]:
    tp = sum(hits)
    fn = len(hits) - tp
    score = sum(hits) / len(hits) if hits else 0.0
    return {"precision": score, "recall": score, "f1": score, "tp": tp, "fp": 0, "tn": 0, "fn": fn}


def label_scores(pairs: list[tuple[list[str], list[str]]]) -> dict[str, float]:
    tp = fp = fn = 0
    for expected, predicted in pairs:
        expected_set = set(expected)
        predicted_set = set(predicted)
        tp += len(expected_set & predicted_set)
        fp += len(predicted_set - expected_set)
        fn += len(expected_set - predicted_set)
    return prf(tp, fp, 0, fn)


def prf(tp: int, fp: int, tn: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "tn": tn, "fn": fn}


if __name__ == "__main__":
    main()
