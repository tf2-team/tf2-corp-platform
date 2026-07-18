from __future__ import annotations

import argparse
import csv
import json
import sys
from statistics import mean, median
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.anomaly import V001AnomalyEngine
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.rca import V001RcaEngine
from aiops.schemas import MetricPoint, MetricSeries


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AIOps anomaly -> RCA on dataset folders.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    settings = Settings()
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    top_k = args.top_k or int(hyperparameters["rca"]["top_k"])
    case_dirs = list_case_dirs(args.dataset)
    if not case_dirs:
        raise ValueError(f"no evaluation cases found under {args.dataset}")
    if args.limit:
        case_dirs = case_dirs[: args.limit]

    labels_path = args.labels or args.dataset / "labels.json"
    labels = load_labels(labels_path)
    case_ids = [str(path.relative_to(args.dataset)).replace("\\", "/") for path in case_dirs]
    missing_labels = sorted(set(case_ids) - set(labels))
    if missing_labels:
        raise ValueError(f"missing explicit labels for cases: {missing_labels}")

    rca = V001RcaEngine(load_runtime_config(settings.runtime_config_path), hyperparameters["rca"]["graph"], hyperparameters["rca"]["combined"])
    anomaly = build_anomaly_engine(hyperparameters["rca"])
    cases = [
        evaluate_case(path, args.dataset, labels[case_id], anomaly, rca, top_k, args.max_metrics)
        for path, case_id in zip(case_dirs, case_ids)
    ]
    report = {
        "metrics": score_report(cases),
        "top_k": top_k,
        "case_count": len(cases),
        "labels_path": str(labels_path),
        "cases": cases,
    }
    report["valid_for_mandate_7b"] = validation_summary(cases)

    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


def list_case_dirs(dataset: Path) -> list[Path]:
    return sorted(path.parent for path in dataset.rglob("simple_metrics.csv"))


def load_labels(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"explicit evaluation labels are required: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, dict):
        raise ValueError("labels file must contain an object named 'cases'")
    return cases


def build_anomaly_engine(config: dict) -> V001AnomalyEngine:
    anomaly = config["anomaly"]
    return V001AnomalyEngine(
        ewma_alpha=float(config["ewma_alpha"]),
        ewma_z_threshold=float(config["ewma_z_threshold"]),
        isolation_score_threshold=float(config["isolation_score_threshold"]),
        min_points=int(config["min_points"]),
        seasonal_period=int(config["seasonal_period"]),
        minimum_deviation_default=float(anomaly["minimum_deviation_default"]),
        minimum_deviation_by_signal={key: float(value) for key, value in anomaly["minimum_deviation_by_signal"].items()},
        algorithm_weights=anomaly["algorithm_weights"],
        weighted_score_threshold=float(anomaly["weighted_score_threshold"]),
        single_algorithm_min_normalized_score=float(anomaly["single_algorithm_min_normalized_score"]),
        confirmation_points=int(anomaly["confirmation_points"]),
    )


def evaluate_case(
    path: Path,
    dataset: Path,
    label: dict[str, object],
    anomaly: V001AnomalyEngine,
    rca: V001RcaEngine,
    top_k: int,
    max_metrics: int,
) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    findings = anomaly.evaluate(series)
    result = rca.rank(findings, series, top_k)
    predicted_roots = [
        {"service": root.service, "metrics": root.root_cause_metrics}
        for root in result.root_causes[:top_k]
    ]
    expected_incident = bool(label.get("expected_incident"))
    expected_root = str(label.get("expected_root_service") or "")
    expected_metric = str(label.get("expected_root_metric") or "") or None
    incident_start = int(label["incident_start_timestamp"]) if label.get("incident_start_timestamp") is not None else None
    fire_timestamp = min((finding.timestamp for finding in findings), default=None)
    return {
        "case_id": str(path.relative_to(dataset)).replace("\\", "/"),
        "expected_incident": expected_incident,
        "predicted_incident": bool(findings),
        "incident_start_timestamp": incident_start,
        "detector_fire_timestamp": fire_timestamp,
        "lead_time_seconds": fire_timestamp - incident_start if fire_timestamp is not None and incident_start is not None else None,
        "expected_root_service": expected_root,
        "expected_root_metric": expected_metric,
        "expected_root_causes": [expected_root] if expected_incident and expected_root else [],
        "predicted_root_causes": predicted_roots,
        "predicted_root_services": [root["service"] for root in predicted_roots],
        "rca_top_k_hit": rca_hit(expected_root, expected_metric, predicted_roots) if expected_incident and expected_root else False,
    }


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


def score_report(cases: list[dict[str, object]]) -> dict[str, object]:
    incident_cases = [case for case in cases if bool(case["expected_incident"])]
    lead_times = [float(case["lead_time_seconds"]) for case in incident_cases if case["lead_time_seconds"] is not None and bool(case["predicted_incident"])]
    return {
        "incident": binary_scores(
            [(bool(case["expected_incident"]), bool(case["predicted_incident"])) for case in cases],
        ),
        "rca_top_k": label_scores(
            [
                (list(case["expected_root_causes"]), list(case["predicted_root_services"]))
                for case in incident_cases
            ],
        ),
        "rca_top_k_hit": hit_scores([bool(case["rca_top_k_hit"]) for case in incident_cases]),
        "lead_time": {
            "count": len(lead_times),
            "mean_seconds": mean(lead_times) if lead_times else None,
            "median_seconds": median(lead_times) if lead_times else None,
        },
    }


def validation_summary(cases: list[dict[str, object]]) -> dict[str, object]:
    positive_count = sum(bool(case["expected_incident"]) for case in cases)
    normal_count = len(cases) - positive_count
    detected_positive_count = sum(bool(case["expected_incident"]) and bool(case["predicted_incident"]) for case in cases)
    timed_detection_count = sum(
        bool(case["expected_incident"])
        and bool(case["predicted_incident"])
        and case["lead_time_seconds"] is not None
        for case in cases
    )
    reasons = []
    if positive_count == 0:
        reasons.append("no_labeled_incident_cases")
    if normal_count == 0:
        reasons.append("no_labeled_normal_cases")
    if timed_detection_count != detected_positive_count:
        reasons.append("detected_incidents_missing_timing_labels")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "positive_count": positive_count,
        "normal_count": normal_count,
        "timed_detection_count": timed_detection_count,
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
