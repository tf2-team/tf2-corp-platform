#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse

from aiops import capture as capture_module
from aiops import replay as replay_module
from aiops.api.app import run_live_pipeline
from aiops.config import Settings
from aiops.schemas import Incident
from aiops.storage import SQLiteIncidentStore
from pydantic import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m aiops.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-live", help="run the live pipeline once")
    subparsers.add_parser("list", help="list stored incidents")
    replay_parser = subparsers.add_parser(
        "replay",
        help="AI MANDATE #15: replay an external labeled scenario set through the detector",
        description=replay_module.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    replay_module.add_arguments(replay_parser)
    capture_parser = subparsers.add_parser(
        "capture",
        help="AI MANDATE #15: capture a real live-Prometheus scenario into a case folder for replay",
        description=capture_module.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    capture_module.add_arguments(capture_parser)

    args = parser.parse_args()

    if args.command == "replay":
        replay_module.run_from_args(args)
        return
    if args.command == "capture":
        capture_module.run_from_args(args)
        return

    settings = Settings()
    if args.command == "run-live":
        print(format_incidents(run_live_pipeline(settings).incidents))
        return
    store = SQLiteIncidentStore(settings.state_store_path, settings.environment)
    try:
        print(format_incidents(load_incidents_for_cli(store)))
    finally:
        store.close()


def load_incidents_for_cli(store: SQLiteIncidentStore) -> list[Incident]:
    incidents: list[Incident] = []
    for row in store._connection.execute("SELECT incident_json FROM incidents ORDER BY fingerprint").fetchall():
        try:
            incidents.append(Incident.model_validate_json(row[0]))
        except ValidationError:
            continue
    return incidents


def format_incidents(incidents: list[Incident]) -> str:
    incidents = list({incident.fingerprint: incident for incident in incidents}.values())
    if not incidents:
        return "No incidents."
    rows = [
        ["incident_id", "sev", "state", "service", "dependency", "count", "reason", "last_seen"],
        *[
            [
                item.incident_id,
                item.severity,
                item.state,
                item.service,
                item.likely_dependency,
                str(item.occurrence_count),
                item.events[-1].reason if item.events else "",
                item.last_seen or "",
            ]
            for item in incidents
        ],
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    return "\n".join("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in rows)


if __name__ == "__main__":
    main()
