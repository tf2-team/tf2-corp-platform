from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"
RUNBOOK_ROOT = Path(__file__).resolve().parents[1] / "runbooks"
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
    "runbooks/index.yaml",
    "schemas/runbook.schema.json",
    "schemas/runbook_index.schema.json",
)
PLACEHOLDER_PATTERN = re.compile(r"(<[^>]+>|\bTODO\b|\bTBD\b|REPLACE_ME|CHANGE_ME)", re.IGNORECASE)
FORBIDDEN_RUNTIME_REFERENCES = ("tests/", "tests\\", "docs/aiops", "docs\\aiops")
IDENTITY_KEYS = {"signal_id", "detector_id", "query_id", "route_id", "policy_id"}
IDENTITY_SCOPES = {
    "signal_id": ("signals/",),
    "detector_id": ("detectors/",),
    "query_id": ("queries/",),
    "route_id": ("notification/",),
    "policy_id": ("policies/",),
}
SOURCE_ADAPTERS = {"prometheus", "grafana", "jaeger", "opensearch", "kubernetes", "aie-status", "cost-status"}
QUERY_MODES = {"instant", "range", "event"}
RESULT_SHAPES = {"scalar", "vector", "matrix", "event"}
SIGNAL_QUALITIES = {"unqualified", "verified", "fallback-only", "missing", "stale", "invalid"}
SIGNAL_PURPOSES = {"official-sli", "diagnostic", "fallback"}
QUERY_STATUSES = {"unqualified", "verified", "fallback-only", "disabled"}
DETECTOR_TYPES = {"official-slo", "no-data", "dependency", "saturation", "robust-anomaly", "signature", "kafka-lag", "llm-visibility"}
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
RUNBOOK_REQUIRED = {
    "runbook_id",
    "version",
    "title",
    "severity",
    "owner",
    "escalation",
    "flows",
    "services",
    "detector_types",
    "signal_refs",
    "allowed_runtime_mode",
    "evidence_required",
    "prohibited_actions",
    "verification",
    "communication_template",
}
RUNBOOK_INDEX_REQUIRED = {"runbook_id", "path", "priority", "matches", "sample_incident"}
RUNBOOK_MATCH_REQUIRED = {"detector_ids", "detector_types", "flows", "services", "signal_ids"}
SAMPLE_INCIDENT_REQUIRED = {"incident_id", "detector_id", "detector_type", "flow", "service", "signal_id", "severity", "runbook_id"}
RUNBOOK_REQUIRED_SECTIONS = (
    "## Impact",
    "## Preconditions and signal quality",
    "## Evidence to collect",
    "## First response",
    "## Prohibited actions",
    "## Dry-run recommendation",
    "## Verification",
    "## Rollback and escalation",
    "## Communication template",
)


def _front_matter(text: str, location: str, errors: list[str]) -> dict[str, Any]:
    if not text.startswith("---\n"):
        errors.append(f"missing YAML front matter: {location}")
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append(f"unterminated YAML front matter: {location}")
        return {}
    try:
        parsed = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        errors.append(f"cannot parse runbook front matter {location}: {exc}")
        return {}
    if not isinstance(parsed, dict):
        errors.append(f"runbook front matter must be an object: {location}")
        return {}
    return parsed


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _walk(value: Any, location: str, errors: list[str], identities: dict[tuple[str, str], str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key in IDENTITY_KEYS and isinstance(item, str) and any(location.startswith(scope) for scope in IDENTITY_SCOPES[key]):
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


def _require_non_empty_list(value: Any, location: str, errors: list[str]) -> None:
    _require_type(value, list, location, errors)
    if isinstance(value, list) and not value:
        errors.append(f"empty list at {location}")


def _matches(matchers: dict[str, Any], incident: dict[str, Any]) -> bool:
    checks = (
        ("detector_ids", "detector_id"),
        ("detector_types", "detector_type"),
        ("flows", "flow"),
        ("services", "service"),
        ("signal_ids", "signal_id"),
    )
    for matcher_key, incident_key in checks:
        accepted = matchers.get(matcher_key, [])
        value = incident.get(incident_key)
        if not isinstance(accepted, list) or value not in accepted:
            return False
    return True


def match_runbook(index_document: dict[str, Any], incident: dict[str, Any]) -> str | None:
    entries = index_document.get("runbooks", [])
    if not isinstance(entries, list):
        return None
    for entry in sorted(entries, key=lambda item: item.get("priority", 1000) if isinstance(item, dict) else 1000):
        if not isinstance(entry, dict):
            continue
        matchers = entry.get("matches", {})
        if isinstance(matchers, dict) and _matches(matchers, incident):
            return entry.get("runbook_id")
    return None


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


def load_runbooks(runbook_root: Path = RUNBOOK_ROOT) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    runbooks: dict[str, dict[str, Any]] = {}

    if not runbook_root.is_dir():
        return runbooks, [f"missing runbook directory: {runbook_root}"]

    for path in sorted(runbook_root.glob("*.md")):
        relative = path.relative_to(runbook_root.parent).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read runbook {relative}: {exc}")
            continue
        runbooks[relative] = {"front_matter": _front_matter(text, relative, errors), "text": text}
    return runbooks, errors


def _validate_runbook_files(runbooks: dict[str, dict[str, Any]], signal_ids: set[str], errors: list[str]) -> set[str]:
    runbook_ids: set[str] = set()
    for relative, runbook in sorted(runbooks.items()):
        front_matter = runbook.get("front_matter", {})
        text = runbook.get("text", "")
        if not isinstance(front_matter, dict):
            errors.append(f"runbook front matter must be an object: {relative}")
            continue
        _require_keys(front_matter, RUNBOOK_REQUIRED, f"{relative}.front_matter", errors)

        runbook_id = front_matter.get("runbook_id")
        if isinstance(runbook_id, str):
            if runbook_id in runbook_ids:
                errors.append(f"duplicate runbook_id={runbook_id!r}: {relative}")
            runbook_ids.add(runbook_id)
            if relative != f"runbooks/{runbook_id}.md":
                errors.append(f"runbook_id must match file name at {relative}: {runbook_id!r}")

        _require_enum(front_matter.get("severity"), {"P0"}, f"{relative}.front_matter.severity", errors)
        _require_enum(front_matter.get("allowed_runtime_mode"), {"dry-run"}, f"{relative}.front_matter.allowed_runtime_mode", errors)
        for key in ("flows", "services", "detector_types", "signal_refs", "evidence_required", "prohibited_actions"):
            _require_non_empty_list(front_matter.get(key), f"{relative}.front_matter.{key}", errors)
        for detector_type in front_matter.get("detector_types", []):
            if isinstance(detector_type, str):
                _require_enum(detector_type, DETECTOR_TYPES, f"{relative}.front_matter.detector_types", errors)
        for signal_ref in front_matter.get("signal_refs", []):
            if signal_ref not in signal_ids:
                errors.append(f"broken runbook signal_ref at {relative}.front_matter.signal_refs: {signal_ref!r} was not found")

        verification = front_matter.get("verification", {})
        _require_type(verification, dict, f"{relative}.front_matter.verification", errors)
        if isinstance(verification, dict):
            _require_keys(verification, {"signal_refs", "consecutive_cycles"}, f"{relative}.front_matter.verification", errors)
            _require_non_empty_list(verification.get("signal_refs"), f"{relative}.front_matter.verification.signal_refs", errors)
            for signal_ref in verification.get("signal_refs", []):
                if signal_ref not in signal_ids:
                    errors.append(f"broken verification signal_ref at {relative}.front_matter.verification.signal_refs: {signal_ref!r} was not found")
            cycles = verification.get("consecutive_cycles")
            if not isinstance(cycles, int) or cycles < 1:
                errors.append(f"invalid verification consecutive_cycles at {relative}: {cycles!r}")

        for section in RUNBOOK_REQUIRED_SECTIONS:
            if section not in text:
                errors.append(f"missing runbook section at {relative}: {section}")
    return runbook_ids


def _validate_runbook_index(
    documents: dict[str, Any],
    runbooks: dict[str, dict[str, Any]],
    runbook_ids: set[str],
    signal_ids: set[str],
    errors: list[str],
) -> None:
    index = documents.get("runbooks/index.yaml")
    if not isinstance(index, dict):
        errors.append("runbooks/index.yaml must be an object")
        return
    entries = index.get("runbooks", [])
    _require_type(entries, list, "runbooks/index.yaml.runbooks", errors)
    if not isinstance(entries, list):
        return

    indexed_ids: set[str] = set()
    for index_number, entry in enumerate(entries):
        location = f"runbooks/index.yaml.runbooks[{index_number}]"
        if not isinstance(entry, dict):
            errors.append(f"runbook index entry must be an object: {location}")
            continue
        _require_keys(entry, RUNBOOK_INDEX_REQUIRED, location, errors)
        runbook_id = entry.get("runbook_id")
        path = entry.get("path")
        if isinstance(runbook_id, str):
            if runbook_id in indexed_ids:
                errors.append(f"duplicate runbook index entry: {runbook_id!r}")
            indexed_ids.add(runbook_id)
            if runbook_id not in runbook_ids:
                errors.append(f"runbook index references missing runbook_id at {location}: {runbook_id!r}")
        if isinstance(path, str):
            if path not in runbooks:
                errors.append(f"runbook index path does not exist at {location}.path: {path!r}")
            if isinstance(runbook_id, str) and path != f"runbooks/{runbook_id}.md":
                errors.append(f"runbook index path must match runbook_id at {location}.path: {path!r}")
        if not isinstance(entry.get("priority"), int):
            errors.append(f"runbook index priority must be an integer: {location}.priority")

        matches = entry.get("matches", {})
        _require_type(matches, dict, f"{location}.matches", errors)
        if isinstance(matches, dict):
            _require_keys(matches, RUNBOOK_MATCH_REQUIRED, f"{location}.matches", errors)
            for key in RUNBOOK_MATCH_REQUIRED:
                _require_non_empty_list(matches.get(key), f"{location}.matches.{key}", errors)
            for detector_type in matches.get("detector_types", []):
                if isinstance(detector_type, str):
                    _require_enum(detector_type, DETECTOR_TYPES, f"{location}.matches.detector_types", errors)
            for signal_id in matches.get("signal_ids", []):
                if signal_id not in signal_ids:
                    errors.append(f"runbook index signal_id was not found at {location}.matches.signal_ids: {signal_id!r}")

        sample = entry.get("sample_incident", {})
        _require_type(sample, dict, f"{location}.sample_incident", errors)
        if isinstance(sample, dict):
            _require_keys(sample, SAMPLE_INCIDENT_REQUIRED, f"{location}.sample_incident", errors)
            if sample.get("runbook_id") != runbook_id:
                errors.append(f"sample incident runbook_id must match index entry at {location}.sample_incident")
            matched_runbook = match_runbook(index, sample)
            if matched_runbook != runbook_id:
                errors.append(f"sample incident did not match expected runbook at {location}: expected {runbook_id!r}, got {matched_runbook!r}")

    missing_from_index = sorted(runbook_ids - indexed_ids)
    for runbook_id in missing_from_index:
        errors.append(f"runbook missing from index: {runbook_id}")


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


def validate_documents(documents: dict[str, Any], runbooks: dict[str, dict[str, Any]] | None = None) -> list[str]:
    errors: list[str] = []
    identities: dict[tuple[str, str], str] = {}
    if runbooks is None:
        runbooks, runbook_errors = load_runbooks()
        errors.extend(runbook_errors)

    for relative in REQUIRED_FILES:
        if relative not in documents:
            errors.append(f"missing required configuration file: {relative}")

    for relative, document in sorted(documents.items()):
        _walk(document, relative, errors, identities)

    query_ids = _collect_query_ids(documents, errors)
    signal_ids = _collect_signal_ids(documents, query_ids, errors)
    _validate_detector_refs(documents, signal_ids, errors)
    runbook_ids = _validate_runbook_files(runbooks, signal_ids, errors)
    _validate_runbook_index(documents, runbooks, runbook_ids, signal_ids, errors)

    actions = documents.get("policies/actions.yaml")
    if isinstance(actions, dict):
        if actions.get("runtime_mode") != "dry-run":
            errors.append("policies/actions.yaml must keep the P0 runtime_mode set to dry-run")
        if actions.get("live_actions"):
            errors.append("policies/actions.yaml must not enable live actions in the P0 scaffold")

    return errors


def validate(config_root: Path = CONFIG_ROOT) -> list[str]:
    documents, errors = load_documents(config_root)
    runbooks, runbook_errors = load_runbooks(RUNBOOK_ROOT)
    errors.extend(runbook_errors)
    if errors:
        return errors
    return validate_documents(documents, runbooks)


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
