"""Eval dataset loader and schema validator (WI-6).

Reads JSONL eval cases from an external file, validates each case against
the eval-case JSON Schema, and routes cases by surface type.

Public API:
    load_dataset(path, surface_filter=None) -> list[dict]
"""

import json
import logging
from pathlib import Path

import jsonschema

logger = logging.getLogger("eval.loader")

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "eval-case.schema.json"
_schema_cache = None


def _load_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


def validate_case(case: dict) -> list[str]:
    """Validate a single eval case against the JSON Schema.

    Returns a list of error messages (empty if valid).
    """
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(p) for p in err.absolute_path)}: {err.message}"
        if err.absolute_path
        else err.message
        for err in validator.iter_errors(case)
    ]


def load_dataset(
    path: str | Path,
    surface_filter: str | None = None,
) -> list[dict]:
    """Load and validate eval cases from a JSONL file.

    Args:
        path: Path to the JSONL file.
        surface_filter: Optional filter — "summary", "copilot", or None for all.

    Returns:
        List of validated eval case dicts.

    Raises:
        FileNotFoundError: if the dataset file doesn't exist.
        ValueError: if any case fails schema validation (logs all errors first).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    cases: list[dict] = []
    errors: list[str] = []

    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_num}: Invalid JSON — {exc}")
                continue

            case_id = case.get("case_id", f"<line {line_num}>")

            validation_errors = validate_case(case)
            if validation_errors:
                for err in validation_errors:
                    errors.append(f"Line {line_num} [{case_id}]: {err}")
                continue

            if surface_filter and case.get("surface") != surface_filter:
                continue

            cases.append(case)

    if errors:
        for err in errors:
            logger.error(err)
        raise ValueError(
            f"Dataset validation failed with {len(errors)} error(s): "
            + " | ".join(errors)
        )

    logger.info(
        "Loaded %d eval cases from %s (filter=%s)",
        len(cases), path, surface_filter or "all",
    )
    return cases
