#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""AI MANDATE #15 live capture helper.

Captures a snapshot of REAL live Prometheus metric series -- the same
signals the continuously-running detector already watches, compiled from
`config/runtime.json` + `config/prometheus_queries.json` -- into a case
folder that `python -m aiops.cli replay` can score. Use this to build the
"bo su co co nhan" (labeled scenario set) mandate #15 requires from real
telemetry instead of hand-made numbers.

Writes two files with the same data:

    metric_series.json   Full fidelity. Each signal keeps its own timestamp
                          grid (services/queries can have different
                          step_seconds/lookback_seconds), so nothing is
                          interpolated or dropped. This is what `replay`
                          prefers to read.
    simple_metrics.csv   Spreadsheet-friendly outer join of every signal on
                          a shared `time` column (one column per
                          `<service>_<metric>`); cells are blank where a
                          signal has no sample at that exact timestamp.
                          Handy to eyeball in Excel/Sheets or diff by hand;
                          `replay` can also read this format on its own if
                          `metric_series.json` is ever missing.

Typical flow for one real-incident case (see
docs/mandates/15/LIVE-CAPTURE-RUNBOOK.md for the full runbook):

    1. `kubectl port-forward` to the configured runtime environment is
       running and AIOPS_PROMETHEUS_BASE_URL points at the configured local
       Prometheus endpoint (see the operator runbook and port-forward script).
    2. Keep normal traffic running (loadgen/Locust) for a few minutes so
       there is a real baseline before the fault.
    3. Note the wall-clock unix timestamp the moment you toggle the flagd
       fault ON -- this becomes --incident-start-ts.
    4. Let the fault run for a few minutes (so it is visible in the metric
       window), then run this command.
    5. Toggle the flagd fault back OFF.

Run once per scenario type: one real incident, one masking case (toggle a
"noisy but harmless" flag plus a real fault together), one high-load
window from Locust alone with no fault, and ideally one plain normal
window (no load ramp, no fault) to anchor "before" MTTD.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from aiops.collectors.prometheus import PrometheusCollector
from aiops.config import Settings, load_runtime_config
from aiops.integrations import PrometheusClient
from aiops.schemas import MetricSeries, SignalQuality


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, required=True, help="Case folder to write metric_series.json + label.json into.")
    parser.add_argument(
        "--scenario-type",
        required=True,
        choices=["real_incident", "masking", "high_load_healthy", "normal"],
        help="Which of the mandate's hidden-set case types this capture represents.",
    )
    parser.add_argument("--expected-incident", required=True, choices=["true", "false"], help="Ground truth label: is there really an incident in this window?")
    parser.add_argument("--incident-start-ts", type=int, default=None, help="Unix timestamp (seconds) when you toggled the fault ON. Omit for healthy/normal captures.")
    parser.add_argument("--notes", default="", help="Free-text note: which flagd flag, which service, what you did, Locust RPS, etc.")


def run_from_args(args: argparse.Namespace) -> dict:
    settings = Settings()
    runtime_config = load_runtime_config(settings.runtime_config_path)
    client = PrometheusClient(settings)
    captured_at = datetime.now(UTC)
    collector = PrometheusCollector(client, runtime_config, captured_at=captured_at)
    series = collector.collect_metric_series()

    verified = [item for item in series if item.quality == SignalQuality.VERIFIED and item.points]
    skipped = [item for item in series if item.quality != SignalQuality.VERIFIED or not item.points]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "metric_series.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in verified], indent=2),
        encoding="utf-8",
    )
    _write_simple_metrics_csv(args.out / "simple_metrics.csv", verified)
    label = {
        "scenario_type": args.scenario_type,
        "expected_incident": args.expected_incident == "true",
        "incident_start_ts": args.incident_start_ts,
        "captured_at": captured_at.isoformat(),
        "notes": args.notes,
        "source": "live_prometheus_capture",
        "prometheus_base_url_host": _redact(settings.prometheus_base_url),
    }
    (args.out / "label.json").write_text(json.dumps(label, indent=2), encoding="utf-8")

    print(
        f"Captured {len(verified)} verified series, skipped {len(skipped)} (missing/invalid) -> "
        f"{args.out}/metric_series.json + {args.out}/simple_metrics.csv"
    )
    if not verified:
        print("WARNING: zero verified series. Check .env AIOPS_PROMETHEUS_BASE_URL and that port-forward is running.")
    if skipped:
        print("Skipped signal_ids (check Prometheus connectivity/labels if this list is large):")
        for item in skipped:
            print(f"  - {item.signal_id} service={item.service} quality={item.quality} error={item.error}")
    return {"verified": len(verified), "skipped": len(skipped), "out": str(args.out)}


def _write_simple_metrics_csv(path: Path, series: list[MetricSeries]) -> None:
    """Outer-join every verified series on a shared `time` column.

    Each series can have its own step/lookback (see module docstring), so a
    timestamp that only one signal sampled at just leaves the other columns
    blank for that row instead of interpolating a fake value.
    """
    columns: dict[str, dict[int, float]] = {}
    all_timestamps: set[int] = set()
    for item in series:
        column = f"{item.service}_{item.metric}"
        by_timestamp = {point.timestamp: point.value for point in item.points}
        columns[column] = by_timestamp
        all_timestamps.update(by_timestamp.keys())

    fieldnames = ["time", *sorted(columns)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for timestamp in sorted(all_timestamps):
            row: dict[str, object] = {"time": timestamp}
            for column, by_timestamp in columns.items():
                if timestamp in by_timestamp:
                    row[column] = by_timestamp[timestamp]
            writer.writerow(row)


def _redact(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0] if url else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    run_from_args(parser.parse_args())


if __name__ == "__main__":
    main()
