from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.anomaly import V001AnomalyEngine
from aiops.config import Settings, load_hyperparameters, load_runtime_config
from aiops.rca import V001RcaEngine
from evaluate.e2e_pipeline import (
    expected_metric_family,
    expected_service,
    list_case_dirs,
    rca_hit,
    read_series,
    score_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the current anomaly -> RCA pipeline on dataset folders.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-metrics", type=int, default=40)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    config = hyperparameters["rca"]
    top_k = args.top_k or int(config["top_k"])
    runtime_config = load_runtime_config(settings.runtime_config_path)
    rca = V001RcaEngine(runtime_config, config["graph"], config["combined"])
    case_dirs = list_case_dirs(args.dataset)
    if args.limit:
        case_dirs = case_dirs[: args.limit]
    cases = []
    for index, path in enumerate(case_dirs, start=1):
        case = evaluate_case(path, config, rca, top_k, args.max_metrics)
        cases.append(case)
        if args.progress:
            print(f"{index}/{len(case_dirs)} {case['case_id']} anomalies={case['anomaly_count']} hit={case['rca_top_k_hit']}", flush=True)
    report = {"metrics": score_report(cases), "top_k": top_k, "case_count": len(cases), "cases": cases}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


def evaluate_case(path: Path, config: dict, rca: V001RcaEngine, top_k: int, max_metrics: int) -> dict[str, object]:
    series = read_series(path / "simple_metrics.csv", max_metrics)
    findings = anomaly_engine(config).evaluate(series)
    result = rca.rank(findings, series, top_k)
    predicted_roots = [{"service": root.service, "metrics": root.root_cause_metrics} for root in result.root_causes[:top_k]]
    expected_root = expected_service(path)
    expected_metric = expected_metric_family(path)
    return {
        "case_id": str(path.relative_to(ROOT / "evaluate" / "dataset")),
        "expected_incident": True,
        "predicted_incident": bool(findings),
        "anomaly_count": len(findings),
        "expected_root_service": expected_root,
        "expected_root_metric": expected_metric,
        "expected_root_causes": [expected_root],
        "predicted_root_causes": predicted_roots,
        "predicted_root_services": [root["service"] for root in predicted_roots],
        "rca_top_k_hit": rca_hit(expected_root, expected_metric, predicted_roots),
    }


def anomaly_engine(config: dict) -> V001AnomalyEngine:
    anomaly = config["anomaly"]
    return V001AnomalyEngine(
        ewma_alpha=float(config["ewma_alpha"]),
        ewma_z_threshold=float(config["ewma_z_threshold"]),
        isolation_score_threshold=float(config["isolation_score_threshold"]),
        min_points=int(config["min_points"]),
        seasonal_period=int(config["seasonal_period"]),
        algorithm_weights=anomaly["algorithm_weights"],
        weighted_score_threshold=float(anomaly["weighted_score_threshold"]),
        drain3_config_path=anomaly.get("drain3_config_path", "config/drain3.ini"),
        log_bucket_seconds=int(anomaly.get("log_bucket_seconds", 60)),
        log_history_buckets=int(anomaly.get("log_history_buckets", config["min_points"])),
        log_max_templates_per_service=int(anomaly.get("log_max_templates_per_service", 20)),
        log_min_nonzero_buckets=int(anomaly.get("log_min_nonzero_buckets", 2)),
        log_correlation_window_seconds=int(anomaly.get("log_correlation_window_seconds", 300)),
        single_algorithm_min_normalized_score=float(anomaly["single_algorithm_min_normalized_score"]),
        robust_drift_threshold=float(anomaly["robust_drift_threshold"]),
        robust_drift_min_baseline_points=int(anomaly["robust_drift_min_baseline_points"]),
        suppress_cpu_robust_threshold=float(anomaly["suppress_cpu_robust_threshold"]),
    )


if __name__ == "__main__":
    main()
