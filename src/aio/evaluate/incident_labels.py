from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


KNOWN_METRIC_FAMILIES = {"cpu", "disk", "error", "latency", "mem", "socket"}


@dataclass(frozen=True)
class IncidentLabel:
    case_id: str
    expected_incident: bool
    expected_root_service: str | None
    expected_root_metric: str | None
    expected_action: str | None


def normalize_case_id(case_id: str) -> str:
    normalized = PurePosixPath(case_id.replace("\\", "/")).as_posix().strip("/")
    if not normalized or normalized == "." or ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"invalid case_id: {case_id!r}")
    return normalized


def parse_bool(value: str, *, case_id: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"case {case_id!r}: expected_incident must be true or false")


def optional(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


def load_label_sheet(path: Path) -> dict[str, IncidentLabel]:
    required = {
        "case_id",
        "expected_incident",
        "expected_root_service",
        "expected_root_metric",
        "expected_action",
    }
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"label sheet missing columns: {', '.join(sorted(missing))}")

        labels: dict[str, IncidentLabel] = {}
        for row_number, row in enumerate(reader, start=2):
            case_id = normalize_case_id(row.get("case_id", ""))
            if case_id in labels:
                raise ValueError(f"duplicate case_id at row {row_number}: {case_id}")
            expected_incident = parse_bool(row.get("expected_incident", ""), case_id=case_id)
            root_service = optional(row.get("expected_root_service"))
            root_metric = optional(row.get("expected_root_metric"))
            action = optional(row.get("expected_action"))
            if expected_incident and root_service is None:
                raise ValueError(f"case {case_id!r}: incident label requires expected_root_service")
            if root_metric is not None and root_metric not in KNOWN_METRIC_FAMILIES:
                raise ValueError(f"case {case_id!r}: unknown metric family {root_metric!r}")
            labels[case_id] = IncidentLabel(case_id, expected_incident, root_service, root_metric, action)
    return labels


def case_id_for(path: Path, dataset: Path) -> str:
    return normalize_case_id(path.resolve().relative_to(dataset.resolve()).as_posix())


def label_for_case(path: Path, dataset: Path, labels: dict[str, IncidentLabel]) -> IncidentLabel:
    case_id = case_id_for(path, dataset)
    try:
        return labels[case_id]
    except KeyError as error:
        raise ValueError(f"label sheet has no row for dataset case: {case_id}") from error


def validate_dataset_coverage(dataset: Path, labels: dict[str, IncidentLabel]) -> None:
    dataset_cases = {
        case_id_for(csv_path.parent, dataset)
        for csv_path in dataset.glob("*/*/*/simple_metrics.csv")
    }
    missing = sorted(dataset_cases - labels.keys())
    extra = sorted(labels.keys() - dataset_cases)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing labels: {', '.join(missing)}")
        if extra:
            details.append(f"labels without dataset cases: {', '.join(extra)}")
        raise ValueError("; ".join(details))

