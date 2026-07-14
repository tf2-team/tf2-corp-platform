from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"
REQUIRED_FILES = (
    "environments/tf2.yaml",
    "queries/official_slos.yaml",
    "queries/checkout.yaml",
    "queries/postgresql.yaml",
    "queries/kafka.yaml",
    "queries/llm.yaml",
    "queries/runtime.yaml",
    "signals/official_slos.yaml",
    "signals/checkout.yaml",
    "signals/postgresql.yaml",
    "signals/runtime.yaml",
    "signals/kafka.yaml",
    "signals/llm.yaml",
    "detectors/official_slos.yaml",
    "detectors/no_data.yaml",
    "detectors/checkout_dependency.yaml",
    "detectors/db_pressure.yaml",
    "detectors/anomalies.yaml",
    "detectors/flag_signatures.yaml",
    "detectors/kafka.yaml",
    "detectors/llm.yaml",
    "topology/services.yaml",
    "policies/actions.yaml",
    "notification/routes.yaml",
)
PLACEHOLDER_PATTERN = re.compile(r"(<[^>]+>|\bTODO\b|\bTBD\b|REPLACE_ME|CHANGE_ME)", re.IGNORECASE)
FORBIDDEN_RUNTIME_REFERENCES = ("tests/", "tests\\", "docs/aiops", "docs\\aiops")
IDENTITY_KEYS = {"signal_id", "detector_id", "query_id", "route_id", "policy_id"}
SOURCE_ADAPTERS = {"prometheus", "grafana", "jaeger", "opensearch", "kubernetes", "aie-status", "cost-status"}
QUERY_MODES = {"instant", "range", "event"}
RESULT_SHAPES = {"scalar", "vector", "matrix", "event"}
SIGNAL_QUALITIES = {"unqualified", "verified", "fallback-only", "missing", "stale", "invalid"}
SIGNAL_PURPOSES = {"official-sli", "diagnostic", "fallback"}
QUERY_STATUSES = {"unqualified", "verified", "fallback-only", "disabled"}
QUERY_REQUIRED = {
    "query_id",
    "source_adapter",
    "mode",
    "window",
    "unit",
    "result_shape",
    "status",
    "expression",
}
SIGNAL_REQUIRED = {
    "signal_id",
    "owner",
    "source_adapter",
    "query_ref",
    "unit",
    "shape",
    "cadence",
    "window",
    "freshness_limit",
    "qualification_state",
    "evidence_ref",
    "purpose",
}
DETECTOR_REQUIRED = {
    "detector_id",
    "type",
    "enabled",
    "signal_refs",
    "runbook_ref",
    "recovery",
    "evidence_ref",
}


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _walk(value: Any, location: str, errors: list[str], identities: dict[tuple[str, str], str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key in IDENTITY_KEYS and isinstance(item, str):
                identity = (key, item)
                previous = identities.get(identity)
                if previous is not None:
                    errors.append(f"duplicate {key}={item!r}: {previous} and {child}")
                else:
                    identities[identity] = child
            _walk(item, child, errors, identities)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{location}[{index}]", errors, identities)
        return
    if not isinstance(value, str):
        return

    if PLACEHOLDER_PATTERN.search(value):
        errors.append(f"placeholder value at {location}: {value!r}")
    lowered = value.lower()
    if "localhost" in lowered or ".example" in lowered:
        errors.append(f"non-production endpoint at {location}: {value!r}")
    if any(fragment in lowered for fragment in FORBIDDEN_RUNTIME_REFERENCES):
        errors.append(f"forbidden runtime reference at {location}: {value!r}")


def _require_keys(document: dict[str, Any], required: set[str], location: str, errors: list[str]) -> None:
    missing = sorted(required - set(document))
    for key in missing:
        errors.append(f"missing required key at {location}: {key}")


def _require_type(value: Any, expected: type | tuple[type, ...], location: str, errors: list[str]) -> None:
    if not isinstance(value, expected):
        if isinstance(expected, tuple):
            names = "|".join(t.__name__ for t in expected)
        else:
            names = expected.__name__
        errors.append(f"invalid type at {location}: expected {names}, got {type(value).__name__}")


def _require_enum(value: Any, allowed: set[str], location: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"invalid value at {location}: {value!r}; allowed={sorted(allowed)}")


def _collect_query_ids(documents: dict[str, Any], errors: list[str]) -> set[str]:
    query_ids: set[str] = set()
    for relative, document in documents.items():
        if not relative.startswith("queries/"):
            continue
        if not isinstance(document, dict):
            errors.append(f"query document must be an object: {relative}")
            continue
        queries = document.get("queries", [])
        _require_type(queries, list, f"{relative}.queries", errors)
        if not isinstance(queries, list):
            continue
        for index, query in enumerate(queries):
            location = f"{relative}.queries[{index}]"
            if not isinstance(query, dict):
                errors.append(f"query definition must be an object: {location}")
                continue
            _require_keys(query, QUERY_REQUIRED, location, errors)
            query_id = query.get("query_id")
            if isinstance(query_id, str):
                query_ids.add(query_id)
            _require_enum(query.get("source_adapter"), SOURCE_ADAPTERS, f"{location}.source_adapter", errors)
            _require_enum(query.get("mode"), QUERY_MODES, f"{location}.mode", errors)
            _require_enum(query.get("result_shape"), RESULT_SHAPES, f"{location}.result_shape", errors)
            _require_enum(query.get("status"), QUERY_STATUSES, f"{location}.status", errors)
            _require_type(query.get("expression"), str, f"{location}.expression", errors)
    return query_ids


def _collect_signal_ids(documents: dict[str, Any], query_ids: set[str], errors: list[str]) -> set[str]:
    signal_ids: set[str] = set()
    for relative, document in documents.items():
        if not relative.startswith("signals/"):
            continue
        if not isinstance(document, dict):
            errors.append(f"signal document must be an object: {relative}")
            continue
        signals = document.get("signals", [])
        _require_type(signals, list, f"{relative}.signals", errors)
        if not isinstance(signals, list):
            continue
        for index, signal in enumerate(signals):
            location = f"{relative}.signals[{index}]"
            if not isinstance(signal, dict):
                errors.append(f"signal definition must be an object: {location}")
                continue
            _require_keys(signal, SIGNAL_REQUIRED, location, errors)
            signal_id = signal.get("signal_id")
            if isinstance(signal_id, str):
                signal_ids.add(signal_id)
            _require_enum(signal.get("source_adapter"), SOURCE_ADAPTERS, f"{location}.source_adapter", errors)
            _require_enum(signal.get("shape"), RESULT_SHAPES, f"{location}.shape", errors)
            _require_enum(signal.get("qualification_state"), SIGNAL_QUALITIES, f"{location}.qualification_state", errors)
            _require_enum(signal.get("purpose"), SIGNAL_PURPOSES, f"{location}.purpose", errors)

            query_ref = signal.get("query_ref")
            if isinstance(query_ref, str):
                if "#" not in query_ref:
                    errors.append(f"query_ref must include '#query_id' at {location}.query_ref: {query_ref!r}")
                else:
                    query_file, query_id = query_ref.rsplit("#", 1)
                    if not query_file.startswith("queries/"):
                        errors.append(f"query_ref must point under queries/ at {location}.query_ref: {query_ref!r}")
                    if query_id not in query_ids:
                        errors.append(f"broken query_ref at {location}.query_ref: query_id {query_id!r} was not found")

            if signal.get("purpose") == "official-sli" and signal.get("qualification_state") == "fallback-only":
                errors.append(f"official SLI cannot be fallback-only at {location}")
            if signal.get("purpose") == "official-sli" and signal.get("window") != "24h":
                errors.append(f"official SLI must use a 24h window at {location}")
            if signal.get("purpose") == "official-sli" and signal.get("unit") not in {"ratio", "seconds"}:
                errors.append(f"official SLI unit must be ratio or seconds at {location}")
    return signal_ids


def _validate_detector_refs(documents: dict[str, Any], signal_ids: set[str], errors: list[str]) -> None:
    for relative, document in documents.items():
        if not relative.startswith("detectors/"):
            continue
        if not isinstance(document, dict):
            errors.append(f"detector document must be an object: {relative}")
            continue
        detectors = document.get("detectors", [])
        _require_type(detectors, list, f"{relative}.detectors", errors)
        if not isinstance(detectors, list):
            continue
        for index, detector in enumerate(detectors):
            location = f"{relative}.detectors[{index}]"
            if not isinstance(detector, dict):
                errors.append(f"detector definition must be an object: {location}")
                continue
            _require_keys(detector, DETECTOR_REQUIRED, location, errors)
            signal_refs = detector.get("signal_refs", [])
            _require_type(signal_refs, list, f"{location}.signal_refs", errors)
            if isinstance(signal_refs, list):
                for signal_ref in signal_refs:
                    if signal_ref not in signal_ids:
                        errors.append(f"broken signal_ref at {location}.signal_refs: {signal_ref!r} was not found")


def canonical_digest(config_root: Path = CONFIG_ROOT) -> str:
    documents: dict[str, Any] = {}
    for path in sorted(config_root.rglob("*.yaml")):
        relative = path.relative_to(config_root).as_posix()
        documents[relative] = _load(path)
    payload = json.dumps(documents, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_documents(config_root: Path = CONFIG_ROOT) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    documents: dict[str, Any] = {}

    for relative in REQUIRED_FILES:
        if not (config_root / relative).is_file():
            errors.append(f"missing required configuration file: {relative}")

    for path in sorted((*config_root.rglob("*.yaml"), *config_root.rglob("*.json"))):
        try:
            document = _load(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"cannot parse {path.relative_to(config_root)}: {exc}")
            continue
        if document is None:
            errors.append(f"empty configuration document: {path.relative_to(config_root)}")
            continue
        relative = path.relative_to(config_root).as_posix()
        documents[relative] = document
    return documents, errors


def validate_documents(documents: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    identities: dict[tuple[str, str], str] = {}

    for relative in REQUIRED_FILES:
        if relative not in documents:
            errors.append(f"missing required configuration file: {relative}")

    for relative, document in sorted(documents.items()):
        _walk(document, relative, errors, identities)

    query_ids = _collect_query_ids(documents, errors)
    signal_ids = _collect_signal_ids(documents, query_ids, errors)
    _validate_detector_refs(documents, signal_ids, errors)

    actions = documents.get("policies/actions.yaml")
    if isinstance(actions, dict):
        if actions.get("runtime_mode") != "dry-run":
            errors.append("policies/actions.yaml must keep the P0 runtime_mode set to dry-run")
        if actions.get("live_actions"):
            errors.append("policies/actions.yaml must not enable live actions in the P0 scaffold")

    return errors


def validate(config_root: Path = CONFIG_ROOT) -> list[str]:
    documents, errors = load_documents(config_root)
    if errors:
        return errors
    return validate_documents(documents)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Configuration scaffold valid: {CONFIG_ROOT}")
    print(f"Configuration digest: {canonical_digest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
