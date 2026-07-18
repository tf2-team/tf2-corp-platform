from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.anomaly import V001AnomalyEngine
from aiops.anomaly.stats import robust_score
from aiops.config import Settings, load_runtime_config
from aiops.rca import V001RcaEngine
from aiops.schemas import AnomalyFinding, MetricPoint, MetricSeries
from incident_labels import IncidentLabel, label_for_case, load_label_sheet, validate_dataset_coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AIOps anomaly -> RCA on dataset folders.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--incident-threshold", type=float, default=1.0)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument(
        "--component-audit",
        action="store_true",
        help="Include a detector-by-detector summary in the report.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    settings = Settings()
    top_k = args.top_k or settings.rca_top_k
    dataset = args.dataset.resolve()
    case_dirs = list_case_dirs(dataset)
    if args.limit:
        case_dirs = case_dirs[: args.limit]

    rca = V001RcaEngine(load_runtime_config(settings.runtime_config_path), settings.rca_fallback_split_ratio)
    anomaly_engine = V001AnomalyEngine(
        ewma_alpha=settings.rca_ewma_alpha,
        ewma_z_threshold=settings.rca_ewma_z_threshold,
        isolation_score_threshold=settings.rca_isolation_score_threshold,
        bocpd_score_threshold=settings.rca_bocpd_score_threshold,
        min_points=settings.rca_min_points,
        seasonal_period=settings.rca_seasonal_period,
    )
    labels = load_label_sheet(args.labels) if args.labels else None
    if labels is not None:
        validate_dataset_coverage(dataset, labels)
    cases = [
        evaluate_case(path, dataset, labels, rca, anomaly_engine, top_k, args.max_metrics, args.incident_threshold)
        for path in case_dirs
    ]
    report = {
        "metrics": score_report(cases),
        "top_k": top_k,
        "incident_threshold": args.incident_threshold,
        "case_count": len(cases),
        "component_audit": summarize_component_audit(cases, settings) if args.component_audit else None,
        "cases": cases,
    }

    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


def list_case_dirs(dataset: Path) -> list[Path]:
    return sorted(path.parent for path in dataset.glob("*/*/*/simple_metrics.csv"))


def evaluate_case(
    path: Path,
    dataset: Path,
    labels: dict[str, IncidentLabel] | None,
    rca: V001RcaEngine,
    anomaly_engine: V001AnomalyEngine,
    top_k: int,
    max_metrics: int,
    anomaly_threshold: float,
) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    detector_findings = anomaly_engine.evaluate(series)
    result = rca.rank(detector_findings, series, top_k)
    predicted_roots = [
        {"service": root.service, "metrics": root.root_cause_metrics}
        for root in result.root_causes[:top_k]
    ]
    label = label_for_case(path, dataset, labels) if labels is not None else None
    expected_incident = label.expected_incident if label else True
    expected_root = label.expected_root_service if label else expected_service(path)
    expected_metric = label.expected_root_metric if label else expected_metric_family(path)
    expected_roots = [expected_root] if expected_root else []
    return {
        "case_id": label.case_id if label else str(path.relative_to(dataset)),
        "expected_incident": expected_incident,
        "predicted_incident": any(is_anomalous(metric, anomaly_threshold) for metric in series),
        "expected_root_service": expected_root,
        "expected_root_metric": expected_metric,
        "expected_root_causes": expected_roots,
        "expected_action": label.expected_action if label else None,
        "detector_findings": [finding.model_dump(mode="json") for finding in detector_findings],
        "predicted_root_causes": predicted_roots,
        "predicted_root_services": [root["service"] for root in predicted_roots],
        "rca_top_k_hit": rca_hit(expected_root, expected_metric, predicted_roots),
    }


def summarize_component_audit(cases: list[dict[str, object]], settings: Settings) -> dict[str, object]:
    expected_algorithms = ("ewma_stl", "isolation_forest", "baro_bocpd")
    by_algorithm: dict[str, list[AnomalyFinding]] = defaultdict(list)
    for case in cases:
        for raw_finding in case.get("detector_findings", []):
            finding = AnomalyFinding.model_validate(raw_finding)
            validate_finding_contract(finding)
            by_algorithm[finding.algorithm].append(finding)

    components = {}
    for algorithm in expected_algorithms:
        findings = by_algorithm[algorithm]
        scores = [finding.score for finding in findings]
        timestamps = [finding.timestamp for finding in findings]
        components[algorithm] = {
            "finding_count": len(findings),
            "case_count": sum(
                any(raw["algorithm"] == algorithm for raw in case.get("detector_findings", []))
                for case in cases
            ),
            "score_range": {
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "mean": mean(scores) if scores else None,
            },
            "timestamp_range": {
                "min": min(timestamps) if timestamps else None,
                "max": max(timestamps) if timestamps else None,
            },
        }
    return {
        "stage": "hybrid-detector-component-audit",
        "normalization_applied": False,
        "fusion_applied": True,
        "findings_used_for_rca": True,
        "configuration": {
            "ewma_alpha": settings.rca_ewma_alpha,
            "ewma_z_threshold": settings.rca_ewma_z_threshold,
            "isolation_score_threshold": settings.rca_isolation_score_threshold,
            "bocpd_score_threshold": settings.rca_bocpd_score_threshold,
            "min_points": settings.rca_min_points,
            "seasonal_period": settings.rca_seasonal_period,
        },
        "components": components,
    }


def validate_finding_contract(finding: AnomalyFinding) -> None:
    if finding.algorithm not in {"ewma_stl", "isolation_forest", "baro_bocpd"}:
        raise ValueError(f"unexpected detector algorithm: {finding.algorithm}")
    if not finding.service or not finding.metric or not finding.signal_id:
        raise ValueError(f"incomplete anomaly finding identity: {finding.model_dump()}")
    if finding.score < 0:
        raise ValueError(f"negative anomaly score: {finding.model_dump()}")


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
