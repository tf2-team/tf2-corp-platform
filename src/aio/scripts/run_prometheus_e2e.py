#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the complete AIOps pipeline against real Prometheus metrics in enforced dry-run mode."
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.live")
    parser.add_argument("--plan", type=Path, default=ROOT / "config" / "prometheus_e2e.json")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    os.environ["AIOPS_ENV_FILE"] = str(args.env_file.resolve())

    from aiops.api.app import configure_logging
    from aiops.config import Settings
    from aiops.e2e import execute_prometheus_e2e

    configure_logging()
    settings = Settings()
    report_dir = args.out_dir or settings.evidence_dir / "e2e"
    report = execute_prometheus_e2e(settings, args.plan, report_dir)
    summary = {
        "run_id": report["run_id"],
        "status": report["status"],
        "report": report["artifact"]["path"],
        "acceptance_criteria": {
            name: item["passed"] for name, item in report["acceptance_criteria"].items()
        },
    }
    if "error" in report:
        summary["error"] = report["error"]
    print(json.dumps(summary, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
