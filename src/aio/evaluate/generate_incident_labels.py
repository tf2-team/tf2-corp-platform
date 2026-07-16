from __future__ import annotations

import argparse
import csv
from pathlib import Path

from e2e_pipeline import ROOT, expected_metric_family, expected_service, list_case_dirs
from incident_labels import case_id_for


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate initial incident labels from dataset folder names.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluate" / "dataset")
    parser.add_argument("--out", type=Path, default=ROOT / "evaluate" / "incident_labels.csv")
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    rows = [
        {
            "case_id": case_id_for(path, dataset),
            "expected_incident": "true",
            "expected_root_service": expected_service(path),
            "expected_root_metric": expected_metric_family(path) or "",
            "expected_action": "",
        }
        for path in list_case_dirs(dataset)
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} labels to {args.out}")


if __name__ == "__main__":
    main()

