#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiops.collectors.static import StaticCollector
from aiops.config import Settings, build_detectors, load_hyperparameters, load_runtime_config
from aiops.enrichment import Enricher
from aiops.normalization import load_normalization_schema
from aiops.pipeline import AiopsPipeline
from aiops.qualification import load_qualification_schema
from aiops.remediation import PolicyEngine
from aiops.schemas import MetricSeries, Observation, SignalQuality
from aiops.storage import SQLiteIncidentStore
from aiops.topology import TopologyGraph
from evaluate.e2e_pipeline import binary_scores, hit_scores, label_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate live mandate datasets through the current notification pipeline.")
    parser.add_argument("--dataset", type=Path, action="append", default=None)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluate" / "live_notification_eval_report.json")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    datasets = args.dataset or [
        ROOT / "evaluate" / "dataset" / "mandate15_live",
        ROOT / "evaluate" / "dataset" / "mandate7b_live",
    ]
    settings = Settings(qualification_gate_dev=True)
    settings = resolve_settings_paths(settings)
    runtime_config = load_runtime_config(settings.runtime_config_path)
    hyperparameters = load_hyperparameters(settings.hyperparameters_path)
    cases = []
    for dataset in datasets:
        for path in case_dirs(dataset):
            case = evaluate_case(path, settings, runtime_config, hyperparameters)
            cases.append(case)
            if args.progress:
                print(f"{case['case_id']} expected={case['expected_incident']} predicted={case['predicted_notification']} skipped={case['skipped']}", flush=True)

    report = {"metrics": score_report(cases), "case_count": len(cases), "cases": cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


def case_dirs(dataset: Path) -> list[Path]:
    return sorted(path for path in dataset.iterdir() if path.is_dir() and (path / "label.json").exists())


def resolve_settings_paths(settings: Settings) -> Settings:
    updates = {}
    for field in ("runtime_config_path", "hyperparameters_path", "qualification_schema_path", "normalization_schema_path"):
        path = getattr(settings, field)
        if not path.is_absolute() and not path.exists():
            updates[field] = ROOT / path
    return settings.model_copy(update=updates)


def evaluate_case(path: Path, settings: Settings, runtime_config, hyperparameters: dict) -> dict[str, object]:
    label = json.loads((path / "label.json").read_text(encoding="utf-8"))
    expected_incident = bool(label.get("expected_incident"))
    metric_path = path / "metric_series.json"
    if not metric_path.exists():
        return case_row(path, label, expected_incident, skipped="missing_metric_series")

    series = [MetricSeries.model_validate(item) for item in json.loads(metric_path.read_text(encoding="utf-8"))]
    observations = observations_from_series(series, runtime_config)
    with TemporaryDirectory() as tmp:
        store = SQLiteIncidentStore(
            Path(tmp) / "aiops.sqlite3",
            environment=settings.environment,
            notification_cooldown_seconds=int(hyperparameters["incident"]["notification_cooldown_seconds"]),
            slo_dedup_seconds=int(hyperparameters["incident"]["slo_dedup_seconds"]),
            rca_dedup_seconds=int(hyperparameters["incident"]["rca_dedup_seconds"]),
            incident_count_reset_seconds=int(hyperparameters["incident"]["count_reset_seconds"]),
            notification_retry_base_seconds=int(hyperparameters["incident"]["notification_retry_base_seconds"]),
            notification_retry_max_seconds=int(hyperparameters["incident"]["notification_retry_max_seconds"]),
            notification_error_max_chars=int(hyperparameters["incident"]["notification_error_max_chars"]),
            topology_graph=TopologyGraph(runtime_config),
        )
        pipeline = AiopsPipeline(
            collector=StaticCollector(observations),
            detectors=build_detectors(runtime_config, hyperparameters["no_data"], hyperparameters["detectors"]),
            store=store,
            policy=PolicyEngine(
                mode=settings.policy_mode,
                protected_targets=runtime_config.policy.protected_targets,
                stateful_kinds=runtime_config.policy.stateful_kinds,
                non_actionable_flows=runtime_config.policy.non_actionable_flows,
                action_type=settings.action_type_restart,
                target_kind=settings.action_target_kind_deployment,
                default_replicas=settings.default_action_replicas,
            ),
            runtime_config=runtime_config,
            qualification_schema=load_qualification_schema(settings.qualification_schema_path),
            normalization_schema=load_normalization_schema(settings.normalization_schema_path),
            qualification_dev=True,
            qualification_max_sample_age_seconds=int(hyperparameters["qualification"]["max_sample_age_seconds"]),
            rca_hyperparameters=hyperparameters["rca"],
            correlation_hyperparameters=hyperparameters["correlation"],
            enricher=Enricher(runtime_config=runtime_config, hyperparameters=hyperparameters["enrichment"]),
        )
        result = pipeline.run_once(metric_series=series)
        store.close()

    notifications = result.notifications
    notified_ids = {message.incident_id for message in notifications}
    notified_incidents = [incident for incident in result.incidents if incident.incident_id in notified_ids]
    capture_end_ts = max((point.timestamp for item in series for point in item.points), default=None)
    detect_ts = min((event.timestamp for incident in notified_incidents for event in incident.events if event.timestamp > 0), default=None)
    if detect_ts is None and notifications:
        detect_ts = capture_end_ts
    start_ts = label.get("incident_start_ts")
    expected_root = expected_root_service(path, label) if expected_incident else None
    predicted_roots = [root.service for root in result.rca_result.root_causes[:1]]
    return case_row(
        path,
        label,
        expected_incident,
        predicted_notification=bool(notifications),
        notification_count=len(notifications),
        notification_titles=[message.title for message in notifications],
        notification_services=[message.service for message in notifications],
        root_causes=[root.model_dump(mode="json") for root in result.rca_result.root_causes],
        expected_root_service=expected_root,
        predicted_root_services=predicted_roots,
        root_hit=bool(expected_root and expected_root in predicted_roots),
        detection_timestamp=detect_ts,
        detection_latency_seconds=(detect_ts - int(start_ts)) if detect_ts is not None and start_ts is not None else None,
        early_by_seconds=(int(start_ts) - detect_ts) if detect_ts is not None and start_ts is not None else None,
    )


def observations_from_series(series: list[MetricSeries], runtime_config) -> list[Observation]:
    signal_by_id = {signal.id: signal for signal in runtime_config.signals}
    observations = []
    for metric in series:
        if not metric.points:
            continue
        signal = signal_by_id.get(metric.signal_id)
        observations.append(
            Observation(
                signal_id=metric.signal_id,
                value=metric.points[-1].value,
                unit=signal.unit if signal else "",
                window=signal.window if signal else "",
                quality=metric.quality if isinstance(metric.quality, SignalQuality) else SignalQuality(metric.quality),
                labels={**metric.labels, "service": metric.service, "sample_timestamp": str(metric.points[-1].timestamp)},
            )
        )
    return observations


def expected_root_service(path: Path, label: dict) -> str | None:
    for key in ("expected_root_service", "root_service", "service"):
        if label.get(key):
            return str(label[key])
    name = path.name
    notes = str(label.get("notes", ""))
    if "paymentFailure" in notes:
        return "payment"
    if "cartFailure" in notes:
        return "cart"
    if name.startswith("checkout"):
        return "checkout"
    if name.startswith("cart"):
        return "cart"
    return None


def case_row(path: Path, label: dict, expected_incident: bool, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": str(path.relative_to(ROOT / "evaluate" / "dataset")),
        "scenario_type": label.get("scenario_type"),
        "expected_incident": expected_incident,
        "predicted_notification": False,
        "notification_count": 0,
        "skipped": None,
    }
    row.update(overrides)
    return row


def score_report(cases: list[dict[str, object]]) -> dict[str, object]:
    runnable = [case for case in cases if not case.get("skipped")]
    incident_pairs = [(bool(case["expected_incident"]), bool(case["predicted_notification"])) for case in runnable]
    root_cases = [case for case in runnable if case.get("expected_root_service")]
    latencies = [case["detection_latency_seconds"] for case in runnable if case.get("detection_latency_seconds") is not None]
    early = [case["early_by_seconds"] for case in runnable if case.get("early_by_seconds") is not None]
    return {
        "notification": binary_scores(incident_pairs),
        "root_top1": label_scores([([str(case["expected_root_service"])], list(case.get("predicted_root_services") or [])) for case in root_cases]),
        "root_top1_hit": hit_scores([bool(case.get("root_hit")) for case in root_cases]),
        "timing": {
            "evaluated_cases": len(latencies),
            "avg_detection_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
            "avg_early_by_seconds": sum(early) / len(early) if early else None,
            "min_detection_latency_seconds": min(latencies) if latencies else None,
            "max_detection_latency_seconds": max(latencies) if latencies else None,
        },
        "skipped_cases": [case["case_id"] for case in cases if case.get("skipped")],
    }


if __name__ == "__main__":
    main()
